"""Shared pothole pins: one engineer pins a spot, every user on this server sees it.

Unlike chat (end-to-end encrypted, two people), pins are shared data kept on the company
server. Others can confirm a pin ("I see it too"), which raises its priority, and mark it
fixed. Pins take part in the repair ranking with severity x traffic.
"""

from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, catalog, db

router = APIRouter(prefix="/api/pins")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pins (
  id TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL, type TEXT NOT NULL, severity TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', reporter TEXT NOT NULL, company_id TEXT NOT NULL, created REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', resolved_by TEXT, resolved_at REAL, traffic TEXT
);
CREATE TABLE IF NOT EXISTS pin_confirms (
  pin_id TEXT NOT NULL REFERENCES pins(id) ON DELETE CASCADE, username TEXT NOT NULL, created REAL NOT NULL,
  PRIMARY KEY (pin_id, username)
);
"""
STATES = ("open", "fixed", "dismissed")


def ensure_schema() -> None:
    con = db.connect()
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pins)")}
    if "size" not in cols:  # added later: optional size an engineer measured on site, JSON {width_cm, length_cm, depth_cm}
        con.execute("ALTER TABLE pins ADD COLUMN size TEXT")
    if "source" not in cols:  # 'map' (tapped on the map) or 'device' (the reporter's GPS, with its accuracy)
        con.execute("ALTER TABLE pins ADD COLUMN source TEXT NOT NULL DEFAULT 'map'")
        con.execute("ALTER TABLE pins ADD COLUMN accuracy_m REAL")
    if "measure" not in cols:  # measured on a photo with a reference object (civil/measure_api.py), JSON
        con.execute("ALTER TABLE pins ADD COLUMN measure TEXT")


class SizeIn(BaseModel):
    width_cm: float = Field(gt=0, le=5000)
    length_cm: float = Field(gt=0, le=5000)
    depth_cm: float = Field(gt=0, le=200)


def size_metrics(size: dict | None) -> dict:
    """A typed-in size as the same metrics a 3D survey measures (rectangle area, depth)."""
    if not size:
        return {}
    w, l, d = size["width_cm"] / 100, size["length_cm"] / 100, size["depth_cm"] / 100
    return {"area_m2": round(w * l, 3), "width_m": round(min(w, l), 3), "length_m": round(max(w, l), 3),
            "depth_max_m": round(d, 3), "volume_m3": round(w * l * d, 4), "diameter_m": round(max(w, l), 2)}


def _metrics(p: dict) -> tuple[dict, dict | None, bool]:
    """A reference-object measurement wins over a typed size: (metrics, measurement record, can undo)."""
    if p.get("measure"):
        mm = json.loads(p["measure"])
        return mm.get("metrics") or {}, mm.get("measurement"), mm.get("prev") is not None
    return (size_metrics(json.loads(p["size"])) if p.get("size") else {}), None, False


class PinIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    type: str = "pothole"
    severity: str = "medium"
    note: str = Field(default="", max_length=500)
    size: SizeIn | None = None
    source: str = "map"                                       # map | device
    accuracy_m: float | None = Field(default=None, ge=0, le=5000)  # GPS accuracy (68 %), device pins only


class PinPatch(BaseModel):
    status: str | None = None
    severity: str | None = None
    note: str | None = Field(default=None, max_length=500)
    size: SizeIn | None = None


def _out(p: dict) -> dict:
    confirms = [auth.person(c["username"]) for c in db.all_("SELECT username FROM pin_confirms WHERE pin_id=?", p["id"])]
    rep = auth.person(p["reporter"]) or {}
    res = auth.person(p["resolved_by"]) if p.get("resolved_by") else None
    from .measure_api import photo_info, pin_photo_path, summary  # late import: measure_api imports this module

    metrics, rec, can_undo = _metrics(p)
    return {**{k: p[k] for k in ("id", "lat", "lon", "type", "severity", "note", "created", "status", "resolved_at")},
            "source": p.get("source") or "map", "accuracy_m": p.get("accuracy_m"),
            "reporter": rep.get("username"), "resolved_by": res["username"] if res else None,
            "label": catalog.CATALOG[p["type"]].label if p["type"] in catalog.CATALOG else p["type"],
            "reporter_name": rep.get("display_name"), "reporter_company": rep.get("company"),
            "confirmations": [c["username"] for c in confirms if c],
            "traffic": json.loads(p["traffic"]) if p.get("traffic") else None,
            "size": json.loads(p["size"]) if p.get("size") else None,
            "metrics": metrics, "measured": summary(rec), "can_undo_measure": can_undo,
            "photo": photo_info(pin_photo_path(p["id"]), f"/api/pins/{p['id']}/photo", "Photo added to this pin"),
            "maps_url": maps_url(p["lat"], p["lon"])}


def maps_url(lat: float, lon: float) -> str:
    """Google Maps at this spot with the traffic layer on (Maps URLs, no key needed)."""
    return f"https://www.google.com/maps/@?api=1&map_action=map&center={lat:.6f},{lon:.6f}&zoom=18&layer=traffic"


def list_pins(status: str | None = "open", bbox: tuple[float, float, float, float] | None = None) -> list[dict]:
    ensure_schema()
    sql, args = "SELECT * FROM pins WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if bbox:
        sql += " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        args += [bbox[0], bbox[2], bbox[1], bbox[3]]
    return [_out(p) for p in db.all_(sql + " ORDER BY created DESC LIMIT 2000", *args)]


@router.get("")
def get_pins(request: Request, status: str = "open", since: float = 0):
    from . import jobcard, materials  # late import: jobcard imports this module

    me = auth.require(request)
    pins = list_pins(status if status in STATES else None)
    cfg = materials.config(me["company_id"])
    for p in pins:
        p["cost"] = jobcard.cost_summary(p, cfg)
    if since:
        pins = [p for p in pins if p["created"] > since or (p["resolved_at"] or 0) > since]
    return {"pins": pins, "now": time.time()}


@router.post("")
def add_pin(body: PinIn, request: Request):
    me = auth.require(request)
    ensure_schema()
    if body.type not in catalog.CATALOG:
        raise HTTPException(400, "unknown type")
    if body.severity not in catalog.SEVERITIES:
        raise HTTPException(400, "bad severity")
    if body.source not in ("map", "device"):
        raise HTTPException(400, "source must be map or device")
    if body.source == "device":
        from . import location

        location.require_enabled(me)  # a GPS pin records where the person stood: needs their agreement
    acc = round(body.accuracy_m, 1) if body.source == "device" and body.accuracy_m is not None else None
    recent = db.one("SELECT COUNT(*) AS n FROM pins WHERE reporter=? AND created>?", me["uid"], time.time() - 60)["n"]
    if recent >= 30:
        raise HTTPException(429, "too many pins; wait a minute")
    # a pin within 5 m of an open pin of the same type is a confirmation, not a new pin
    for p in db.all_("SELECT * FROM pins WHERE status='open' AND type=? AND abs(lat-?)<0.0001 AND abs(lon-?)<0.0001",
                     body.type, body.lat, body.lon):
        from .pointcloud import latlon_to_enu

        dx, dy = latlon_to_enu(p["lat"], p["lon"], body.lat, body.lon)
        if (dx * dx + dy * dy) ** 0.5 <= 5.0:
            db.run("INSERT OR IGNORE INTO pin_confirms(pin_id,username,created) VALUES(?,?,?)", p["id"], me["uid"], time.time())
            return {**_out(db.one("SELECT * FROM pins WHERE id=?", p["id"])), "merged": True}
    pid = secrets.token_hex(5)
    db.run("INSERT INTO pins(id,lat,lon,type,severity,note,reporter,company_id,created,size,source,accuracy_m) "
           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
           pid, body.lat, body.lon, body.type, body.severity, body.note.strip(), me["uid"], me["company_id"], time.time(),
           json.dumps(body.size.model_dump()) if body.size else None, body.source, acc)
    return {**_out(db.one("SELECT * FROM pins WHERE id=?", pid)), "merged": False}


@router.post("/{pin_id}/confirm")
def confirm(pin_id: str, request: Request):
    me = auth.require(request)
    ensure_schema()
    if not db.one("SELECT 1 AS x FROM pins WHERE id=?", pin_id):
        raise HTTPException(404, "no such pin")
    db.run("INSERT OR IGNORE INTO pin_confirms(pin_id,username,created) VALUES(?,?,?)", pin_id, me["uid"], time.time())
    return _out(db.one("SELECT * FROM pins WHERE id=?", pin_id))


@router.patch("/{pin_id}")
def patch_pin(pin_id: str, body: PinPatch, request: Request):
    me = auth.require(request)
    ensure_schema()
    p = db.one("SELECT * FROM pins WHERE id=?", pin_id)
    if not p:
        raise HTTPException(404, "no such pin")
    if body.status is not None:
        if body.status not in STATES:
            raise HTTPException(400, "bad status")
        if body.status == "dismissed" and me["uid"] != p["reporter"] and me["role"] != "admin":
            raise HTTPException(403, "only the reporter or an admin can dismiss a pin")
        db.run("UPDATE pins SET status=?, resolved_by=?, resolved_at=? WHERE id=?", body.status,
               me["uid"] if body.status != "open" else None, time.time() if body.status != "open" else None, pin_id)
    if body.severity is not None:
        if body.severity not in catalog.SEVERITIES:
            raise HTTPException(400, "bad severity")
        db.run("UPDATE pins SET severity=? WHERE id=?", body.severity, pin_id)
    if body.size is not None:  # a typed size replaces a photo measurement
        db.run("UPDATE pins SET size=?, measure=NULL WHERE id=?", json.dumps(body.size.model_dump()), pin_id)
    if body.note is not None and (me["uid"] == p["reporter"] or me["role"] == "admin"):
        db.run("UPDATE pins SET note=? WHERE id=?", body.note.strip(), pin_id)
    return _out(db.one("SELECT * FROM pins WHERE id=?", pin_id))

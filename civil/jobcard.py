"""Pothole job card: everything a crew needs about one pothole, in four parts.

  location  photo from the drive, address, coordinates, navigation link, size and depth
  cost      materials-only bill of materials (civil/materials.py)
  timing    suggested repair window from the road class (config/repair_timing.json),
            plus Google live congestion when it was fetched in the last few minutes
  plan      urgency, repair method and steps with this pothole's quantities

Works for survey findings and for shared pins (pins carry an optional size an engineer typed).
Outside calls: OpenStreetMap Nominatim for the street address (cached in the database, can be
switched off with the OpenStreetMap setting in Settings > Traffic). Only coordinates are sent.
"""

from __future__ import annotations

import json
import math
import threading
import time
from functools import lru_cache

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import auth, catalog, db, materials, pins, store, traffic
from .config import CONFIG_DIR

router = APIRouter(prefix="/api")

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_geo_lock = threading.Lock()
_geo_last = [0.0]
_geo_failed: dict[str, float] = {}   # key -> retry-after time (memory only)
URGENCY = {"high": ("Fix first", "immediate"), "medium": ("Schedule soon", "soon"), "low": ("Monitor", "monitor")}


# --- address -------------------------------------------------------------------------------------------------
def _geo_schema() -> None:
    db.connect().execute("CREATE TABLE IF NOT EXISTS geocode (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL)")


def address(lat: float, lon: float, company_id: str, lang: str = "en") -> dict | None:
    """Street address for a point: Nominatim reverse, cached (Nominatim asks for at most 1 request/s)."""
    lang = (lang or "en").split(",")[0].split(";")[0].strip()[:8] or "en"
    key = f"{lat:.5f},{lon:.5f},{lang}"
    _geo_schema()
    row = db.one("SELECT value FROM geocode WHERE key=?", key)
    if row:
        return json.loads(row["value"])
    if not traffic.settings(company_id)["osm"]:
        return None
    if time.time() < _geo_failed.get(key, 0):
        return None  # failed recently: don't make every card wait for the timeout again
    # Nominatim allows 1 request/s: reserve a time slot under the lock, then wait and call without holding it
    with _geo_lock:
        slot = max(time.time(), _geo_last[0] + 1.05)
        if slot - time.time() > 5:
            return None  # queue too long; the address fills in on a later open
        _geo_last[0] = slot
    time.sleep(max(0.0, slot - time.time()))
    try:
        r = httpx.get(NOMINATIM, params={"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "zoom": 18,
                                         "addressdetails": 1}, headers={"User-Agent": traffic.USER_AGENT,
                                                                        "Accept-Language": lang}, timeout=6)
        r.raise_for_status()
        j = r.json()
    except (httpx.HTTPError, ValueError):
        _geo_failed[key] = time.time() + 300
        return None
    a = j.get("address") or {}
    road = a.get("road") or a.get("pedestrian") or a.get("residential")
    area = a.get("suburb") or a.get("village") or a.get("quarter") or a.get("neighbourhood")
    city = a.get("city") or a.get("town") or a.get("county") or a.get("municipality")
    region = a.get("state") or a.get("province")
    out = {"road": road, "line1": road or (j.get("name") or None),
           "line2": ", ".join(x for x in (area, city, region) if x) or None,
           "full": j.get("display_name"), "source": "OpenStreetMap Nominatim"}
    db.run("INSERT OR REPLACE INTO geocode(key,value,created) VALUES(?,?,?)", key, json.dumps(out), time.time())
    return out


# --- photo -----------------------------------------------------------------------------------------------------
@lru_cache(maxsize=16)
def _poses(path: str, mtime: float) -> np.ndarray | None:
    with np.load(path, allow_pickle=False) as z:
        return np.asarray(z["poses"], dtype=np.float64) if "poses" in z.files else None


def best_frame(pid: str, sid: str, f: dict) -> dict | None:
    """The drive frame that shows this finding best: camera 2-10 m behind it, looking most directly at it."""
    sdir = store.survey_dir(pid, sid)
    frames = sdir / "input" / "frames"
    rp = store.recon_path(pid, sid)
    if not frames.is_dir() or not rp.is_file():
        return None
    poses = _poses(str(rp), rp.stat().st_mtime)
    if poses is None or not len(poses):
        return None
    files = sorted(frames.glob("*.jpg"))
    if len(files) != len(poses):
        return None
    p = np.array([f["x"], f["y"], f.get("z", 0.0)])
    cam = poses[:, :3, 3]
    fwd = poses[:, :3, 2]                                   # camera looks along +z (OpenCV convention)
    v = p - cam
    dist = np.linalg.norm(v[:, :2], axis=1)
    fh = fwd[:, :2] / np.maximum(np.linalg.norm(fwd[:, :2], axis=1, keepdims=True), 1e-9)
    cosang = np.einsum("ij,ij->i", v[:, :2], fh) / np.maximum(dist, 1e-9)
    ok = (dist > 2.0) & (dist < 10.0) & (cosang > math.cos(math.radians(35)))
    if not ok.any():
        return None
    meta = {}
    bj = sdir / "input" / "boxes.json"
    if bj.is_file():
        meta = json.loads(bj.read_text())
    all_boxes = meta.get("boxes") or {}
    has_box = np.array([str(k) in all_boxes for k in range(len(poses))])
    # frames where the detector drew a box are preferred: the pothole is visibly there
    score = np.where(ok, np.degrees(np.arccos(np.clip(cosang, -1, 1))) + 6 * np.abs(dist - 4.5) - 10 * has_box, np.inf)
    i = int(np.argmin(score))
    geo = meta.get("geometry")
    boxes = [_box_to_frame(b, geo) for b in all_boxes.get(str(i), [])]
    return {"url": f"/api/projects/{pid}/surveys/{sid}/frames/{i}", "frame": i, "distance_m": round(float(dist[i]), 1),
            "boxes": boxes, "note": f"Video frame {i}, taken about {dist[i]:.0f} m before the pothole"}


def _box_to_frame(b: list[float], geo: dict | None) -> list[float]:
    """Detector boxes are saved in LingBot's model-image pixels (civil/video/frames.box_to_model); undo that."""
    if not geo:
        return [round(v, 1) for v in b]
    fy = lambda y: (y + geo["crop_top"]) / geo["sy"] + geo["y0"]  # noqa: E731
    return [round(b[0] / geo["sx"], 1), round(fy(b[1]), 1), round(b[2] / geo["sx"], 1), round(fy(b[3]), 1)]


@router.get("/projects/{pid}/surveys/{sid}/frames/{n}")
def frame_image(pid: str, sid: str, n: int):
    if not 0 <= n < 100_000:
        raise HTTPException(404, "not found")
    f = store.survey_dir(pid, sid) / "input" / "frames" / f"{n:06d}.jpg"
    if not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# --- timing ----------------------------------------------------------------------------------------------------
def timing_rules() -> dict:
    return json.loads((CONFIG_DIR / "repair_timing.json").read_text())


def timing(t: dict | None) -> dict:
    t = t or {}
    hw = t.get("highway")
    rules = timing_rules()["classes"]
    cls = next((k for k, c in rules.items() if hw and hw in c["roads"]), "unknown")
    r = rules[cls]
    out = {"window": r["window"], "days": r["days"], "level": r["level"], "reason": r["reason"], "road_class": cls,
           "road": hw, "road_name": t.get("road_name"), "factor": t.get("factor"),
           "basis": "rule of thumb for this road type (OpenStreetMap)" if hw else "default rule (road type not known yet)"}
    ratio = t.get("ratio")
    if ratio:
        out["now"] = {"ratio": round(ratio, 2), "level": "heavy" if ratio >= 1.5 else ("moderate" if ratio >= 1.15 else "light"),
                      "source": "Google live traffic, last few minutes"}
    return out


# --- card ------------------------------------------------------------------------------------------------------
def _nav_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}&travelmode=driving"


def _warning(b: dict, f_type: str) -> str:
    if not b.get("available"):
        return ""
    return (f"{b['area_m2']:.2f} m² damaged, {b['depth_m'] * 100:.0f} cm deep. "
            + ("A hazard for motorcycles and tyres." if b["depth_m"] >= 0.05 and f_type == "pothole"
               else "Water gets in and the edges break up further if it is left."))


def build(kind: str, f: dict, *, company_id: str, lang: str, photo: dict | None, t: dict | None,
          reported: float | None, survey_name: str | None = None) -> dict:
    cfg = materials.config(company_id)
    b = materials.bill(f.get("metrics"), cfg, f.get("bbox"))
    sev = f.get("severity") or "low"
    urg, urg_code = URGENCY.get(sev, URGENCY["low"])
    it = catalog.CATALOG.get(f["type"])
    m = f.get("metrics") or {}
    tiles = [(k, lbl, unit) for k, lbl, unit in (("area_m2", "Size", "m²"), ("depth_max_m", "Depth", "m"),
                                                  ("volume_m3", "Volume", "m³"), ("diameter_m", "Width", "m")) if m.get(k) is not None]
    return {
        "kind": kind, "id": f["id"], "type": f["type"], "label": it.label if it else f["type"], "severity": sev,
        "status": f.get("status", "open"),
        "location": {
            "lat": f["lat"], "lon": f["lon"], "address": address(f["lat"], f["lon"], company_id, lang),
            "road_name": (t or {}).get("road_name"), "nav_url": _nav_url(f["lat"], f["lon"]),
            "maps_url": pins.maps_url(f["lat"], f["lon"]), "photo": photo, "reported": reported, "survey": survey_name,
            "tiles": [{"key": k, "label": lbl, "value": m[k], "unit": unit} for k, lbl, unit in tiles],
            "evidence": f.get("evidence") or f.get("note") or "",
        },
        "cost": b,
        "timing": timing(t),
        "plan": {"urgency": urg, "urgency_code": urg_code, "warning": _warning(b, f["type"]),
                 "method": b.get("method_label"), "steps": materials.steps(b),
                 "materials": [ln["label"] for ln in b.get("lines", [])],
                 "mass_kg": b.get("mix_kg")},
    }


def _lang(request: Request) -> str:
    return request.headers.get("accept-language", "en")


@router.get("/projects/{pid}/surveys/{sid}/findings/{fid}/card")
def finding_card(pid: str, sid: str, fid: str, request: Request):
    me = auth.require(request)
    an = store.get_analysis(pid, sid)
    f = next((x for x in an["findings"] if x["id"] == fid), None)
    if f is None:
        raise HTTPException(404, "not found")
    seg = next((s for s in an["segments"] if s["id"] == f.get("segment_id")), None)
    t = traffic.live_info(f["lat"], f["lon"], (seg or {}).get("traffic")) if seg and seg.get("traffic") else None
    sv = store.get_survey(pid, sid)
    try:
        photo = best_frame(pid, sid, f)
    except (OSError, ValueError, KeyError):
        photo = None
    return build("finding", f, company_id=me["company_id"], lang=_lang(request), photo=photo, t=t,
                 reported=sv.get("created"), survey_name=sv.get("name"))


@router.get("/pins/{pin_id}/card")
def pin_card(pin_id: str, request: Request):
    me = auth.require(request)
    pins.ensure_schema()
    row = db.one("SELECT * FROM pins WHERE id=?", pin_id)
    if row is None:
        raise HTTPException(404, "not found")
    p = pins._out(row)
    f = {"id": p["id"], "type": p["type"], "severity": p["severity"], "status": p["status"], "lat": p["lat"], "lon": p["lon"],
         "metrics": p.get("metrics") or {}, "note": p["note"], "evidence": p["note"]}
    t = traffic.live_info(p["lat"], p["lon"], p["traffic"]) if p.get("traffic") else None
    card = build("pin", f, company_id=me["company_id"], lang=_lang(request), photo=None, t=t, reported=p["created"])
    card["location"]["reporter"] = p.get("reporter_name")
    return card


def cost_summary(f: dict, cfg: dict) -> dict | None:
    """Short form for lists: total materials cost and method, or None when it can't be estimated."""
    it = catalog.CATALOG.get(f["type"])
    if not it or it.kind != "defect" or f["type"] not in COSTED:
        return None
    b = materials.bill(f.get("metrics"), cfg, f.get("bbox"))
    if not b.get("available"):
        return None
    return {"materials_cost": b["subtotal"], "method": b["method"], "symbol": b["symbol"], "currency": b["currency"],
            "missing_prices": bool(b["missing_prices"])}


# defect types that are repaired by filling (the bill of materials applies)
COSTED = {"pothole", "depression"}

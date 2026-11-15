"""Opt-in device location ("Use my location"), with an agreement the person accepts or declines.

Location is used only while iScale is open and only on the person's own device:
  * a "you are here" dot on the map (never sent to the server)
  * "Pin where I stand": the pin keeps the GPS position and its accuracy
  * "Record a drive": the phone records video and a GPS track together; the track is uploaded
    with the video as gps.csv and gives the LingBot-Map survey its real position and scale
  * "Share location" in chat (a one-off message, end-to-end encrypted)
Nobody else sees a person's live position, and the server never receives it except as a pin
position or a recorded drive's track.

The agreement text is config/location_agreement.md. Its `version:` line is the version people
accept; change it whenever the text changes and everyone is asked again. Each answer is kept
in consent_log (who, what, which version, when) so the company can show when consent was given
or withdrawn. The current state is the person's latest row.
"""

from __future__ import annotations

import json
import re
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, db, store
from .config import CONFIG_DIR

router = APIRouter(prefix="/api/location")

PURPOSE = "location"
DECISIONS = ("accepted", "declined", "withdrawn")
AGREEMENT_FILE = CONFIG_DIR / "location_agreement.md"        # English
AGREEMENT_FILE_TH = CONFIG_DIR / "location_agreement.th.md"  # Thai (PDPA s.19: plain Thai); same version line
MAX_TRACK_ACCURACY_M = 30.0  # recorded-drive positions less accurate than this are dropped

SCHEMA = """
CREATE TABLE IF NOT EXISTS consent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, purpose TEXT NOT NULL,
  decision TEXT NOT NULL, version TEXT NOT NULL, at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS consent_log_user ON consent_log (username, purpose, id);
"""


def ensure_schema() -> None:
    db.connect().executescript(SCHEMA)


def _read(path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\s*version:\s*(\S+)\s*\n", text)
    if not m:
        raise RuntimeError(f"{path.name} must start with a 'version: ...' line")
    return m.group(1), text[m.end():]


def agreement(lang: str = "en") -> tuple[str, str]:
    """(version, markdown body) of the current agreement in English or Thai, with the controller filled in.
    The English file's version is the one people accept; the Thai file must carry the same version."""
    version, body = _read(AGREEMENT_FILE)
    th = False
    if lang == "th" and AGREEMENT_FILE_TH.is_file():
        v_th, body_th = _read(AGREEMENT_FILE_TH)
        if v_th == version:  # never show an out-of-date translation as the current text
            body, th = body_th, True
    host = db.one("SELECT name FROM companies WHERE is_host=1 ORDER BY created LIMIT 1") or {}
    contact = (db.get_setting("server", "privacy_contact", "") or "").strip()
    address = (db.get_setting("server", "privacy_address", "") or "").strip()
    missing = "ยังไม่ได้ตั้งค่า โปรดสอบถามผู้ดูแลระบบ iScale" if th else "not set yet; ask your iScale admin"
    body = (body.replace("{controller}", host.get("name") or ("บริษัทที่ดำเนินการเซิร์ฟเวอร์ iScale นี้" if th else "the company that runs this iScale server"))
            .replace("{contact}", contact or missing).replace("{address}", address or missing))
    return version, body.strip()


def current(uid: str) -> dict | None:
    ensure_schema()
    return db.one("SELECT decision, version, at FROM consent_log WHERE username=? AND purpose=? ORDER BY id DESC LIMIT 1",
                  uid, PURPOSE)


def enabled(uid: str) -> bool:
    """True only if the person's latest answer is 'accepted' for the current agreement version."""
    c = current(uid)
    return bool(c) and c["decision"] == "accepted" and c["version"] == agreement()[0]


def require_enabled(me: dict) -> None:
    if not enabled(me["uid"]):
        raise HTTPException(403, "location is off for your account; turn it on in Settings, Location, and accept the agreement")


def _state(me: dict) -> dict:
    version, text = agreement()
    c = current(me["uid"])
    return {"version": version, "text": text, "text_th": agreement("th")[1], "enabled": enabled(me["uid"]),
            "decision": c["decision"] if c else None, "decided_version": c["version"] if c else None,
            "decided_at": c["at"] if c else None,
            # ask on entry when there is no answer yet, or the agreement changed since an "accepted"
            "ask": c is None or (c["decision"] == "accepted" and c["version"] != version),
            "privacy_contact": db.get_setting("server", "privacy_contact", "") or "",
            "privacy_address": db.get_setting("server", "privacy_address", "") or "",
            "contact_editable": auth.public_user(me)["host_admin"],
            "my_tracks": len(_my_tracks(me))}


class ConsentIn(BaseModel):
    decision: str
    version: str = Field(max_length=40)


class ContactIn(BaseModel):
    contact: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=400)


@router.get("")
def get_state(request: Request):
    return _state(auth.require(request))


@router.post("/consent")
def post_consent(body: ConsentIn, request: Request):
    me = auth.require(request)
    if body.decision not in DECISIONS:
        raise HTTPException(400, "decision must be accepted, declined or withdrawn")
    version = agreement()[0]
    if body.decision == "accepted" and body.version != version:
        raise HTTPException(409, "the agreement changed while it was open; read the new version")
    was_on = enabled(me["uid"])
    ensure_schema()
    db.run("INSERT INTO consent_log(username,purpose,decision,version,at) VALUES(?,?,?,?,?)",
           me["uid"], PURPOSE, body.decision, version, time.time())
    deleted = 0
    if body.decision != "accepted":
        # PDPA s.19/s.33: data held on consent is deleted when consent ends (any earlier acceptance counts,
        # also one for an older agreement version that was never renewed)
        deleted = _delete_tracks(me)
    return {**_state(me), "tracks_deleted": deleted, "was_on": was_on}


@router.get("/history")
def history(request: Request):
    """The person's own answers, newest first (what they agreed to, and when)."""
    me = auth.require(request)
    ensure_schema()
    return db.all_("SELECT decision, version, at FROM consent_log WHERE username=? AND purpose=? ORDER BY id DESC",
                   me["uid"], PURPOSE)


@router.put("/contact")
def put_contact(body: ContactIn, request: Request):
    """Who people contact about their location data (shown in the agreement). Host company admin only."""
    me = auth.require_admin(request)
    if not auth.public_user(me)["host_admin"]:
        raise HTTPException(403, "only the admin of the company that set up this server can change this")
    db.set_setting("server", "privacy_contact", body.contact.strip())
    db.set_setting("server", "privacy_address", body.address.strip())
    return _state(me)


# --- recorded drive tracks -------------------------------------------------------------------
def _my_tracks(me: dict) -> list:
    """GPS track files from drives this person recorded in iScale, in their company's projects."""
    out = []
    for p in store.list_projects(me["company_id"]):
        for sv in store.list_surveys(p["id"]):
            prm = sv.get("params") or {}
            if prm.get("device_gps_by") != me["uid"] and not (prm.get("parent") and _parent_by(p["id"], prm["parent"]) == me["uid"]):
                continue
            f = store.survey_dir(p["id"], sv["id"]) / "input" / "gps.csv"
            if f.is_file():
                out.append(f)
    return out


def _parent_by(pid: str, sid: str):
    try:
        return (store.get_survey(pid, sid).get("params") or {}).get("device_gps_by")
    except Exception:  # noqa: BLE001 - a deleted parent
        return None


@router.post("/forget-tracks")
def forget_tracks(request: Request):
    """Delete the GPS tracks of drives this person recorded. Survey results already computed stay."""
    me = auth.require(request)
    return {"deleted": _delete_tracks(me), **_state(me)}


def _delete_tracks(me: dict) -> int:
    files = _my_tracks(me)
    for f in files:
        f.unlink(missing_ok=True)
    return len(files)


def write_track(target_dir, rows: list) -> None:
    """Save a recorded track as gps.csv (t seconds from the video start, lat, lon, accuracy_m)."""
    lines = ["t,lat,lon,accuracy_m"]
    for r in rows:
        lines.append(f"{float(r[0]):.3f},{float(r[1]):.7f},{float(r[2]):.7f},{float(r[3]) if len(r) > 3 and r[3] is not None else ''}")
    (target_dir / "gps.csv").write_text("\n".join(lines) + "\n")


def parse_track(raw: str) -> list:
    """The browser's track JSON [[t, lat, lon, acc], ...] -> validated rows (sorted, deduplicated)."""
    try:
        rows = json.loads(raw)
        assert isinstance(rows, list)
    except (ValueError, AssertionError):
        raise HTTPException(400, "the GPS track is not valid")
    out, seen = [], set()
    for r in rows[:20000]:
        try:
            t, lat, lon = float(r[0]), float(r[1]), float(r[2])
            acc = float(r[3]) if len(r) > 3 and r[3] is not None else None
        except (TypeError, ValueError, IndexError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= t <= 24 * 3600) or t in seen:
            continue
        if acc is not None and acc > MAX_TRACK_ACCURACY_M:
            continue  # a poor fix (tunnel, under a flyover, cold start) would bend the survey's scale
        seen.add(t)
        out.append((t, lat, lon, acc))
    return sorted(out)

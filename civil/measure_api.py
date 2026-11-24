"""HTTP routes for measuring a pothole with a reference object (the math is in civil/measure.py).

  GET  /api/measure/refs                          reference presets
  POST /api/measure/preview                       metrics, ranges, warnings and the materials bill; stores nothing
  POST /api/projects/{pid}/surveys/{sid}/findings/{fid}/measurement        save on a survey finding
  POST /api/projects/{pid}/surveys/{sid}/findings/{fid}/measurement/undo   back to the previous metrics
  POST|GET /api/projects/{pid}/surveys/{sid}/findings/{fid}/photo          an on-site photo of the finding
  POST|GET /api/pins/{pin_id}/photo                                        one photo per shared pin
  POST /api/pins/{pin_id}/measurement (+ /undo)                            save on a pin

Saving replaces the finding's metrics with the measured ones and keeps the old ones under
metrics_prev (one step of undo). The analysis' own 3D metrics are kept once under metrics_3d, so
"rescale the 3D depth" and the 3D check keep working after a measurement. Everything that prices a
pothole (job card, cost chips, Repairs plan, exports) reads `metrics`, so it follows automatically.

Access is the same as the job card: /api/projects/... routes are checked against the signed-in
user's company by the API guard; pins are shared by everyone on the server. Writes need a signed-in
staff account (admin or engineer).
"""

from __future__ import annotations

import copy
import io
import json
import re
import time

import cv2
import numpy as np
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import auth, db, images, materials, measure, pins, store
from .config import DATA_DIR

router = APIRouter(prefix="/api")

MAX_PHOTO_BYTES = 15 * 1024 * 1024   # a phone photo; the browser shrinks it to <= 3000 px before upload
MAX_PHOTO_SIDE = 4096
FILE_RE = re.compile(r"^t[0-9_]+\.jpg$")


def require_staff(request: Request) -> dict:
    """A signed-in member of a company (admin or engineer): the people who may change findings."""
    me = auth.require(request)
    if me.get("role") not in auth.ROLES:
        raise HTTPException(403, "only staff can save measurements")
    return me


# --- request bodies ------------------------------------------------------------------------------------
Coord = Annotated[float, Field(ge=-100_000, le=100_000, allow_inf_nan=False)]   # image pixels, a little off-image allowed
Point = Annotated[list[Coord], Field(min_length=2, max_length=2)]              # [x, y]
class Target(BaseModel):
    kind: str                       # finding | pin
    id: str = Field(max_length=64)
    project: str | None = Field(default=None, max_length=40)
    survey: str | None = Field(default=None, max_length=40)


class ImageRef(BaseModel):
    kind: str = "frame"             # frame (job card video frame) | photo (uploaded) | detection (Video view)
    frame: int | None = Field(default=None, ge=0, le=100_000)
    survey: str | None = Field(default=None, max_length=40)
    file: str | None = Field(default=None, max_length=64)
    t: float | None = Field(default=None, ge=0, le=86_400)


class MeasureIn(BaseModel):
    image_w: int = Field(gt=0, le=30_000)
    image_h: int = Field(gt=0, le=30_000)
    ref_type: str = Field(max_length=20)
    ref_width_cm: float | None = Field(default=None, gt=0, le=10_000)
    ref_length_cm: float | None = Field(default=None, gt=0, le=10_000)
    ref_points: list[Point] = Field(min_length=2, max_length=4)
    first_edge: str | None = None    # width | length | None (automatic)
    outline: list[Point] | None = Field(default=None, max_length=200)
    box: list[Coord] | None = Field(default=None, min_length=4, max_length=4)
    tol_px: float = Field(default=measure.TOL_PX, ge=0, le=50)
    depth_cm: float | None = Field(default=None, gt=0, le=200)
    rescale_3d: bool = False
    target: Target | None = None
    image: ImageRef | None = None


# --- helpers ---------------------------------------------------------------------------------------------
def three_d(f: dict | None) -> dict | None:
    """The 3D metrics of a finding (the analysis' own, before any reference measurement) if they have
    an area and a depth to rescale, else None."""
    if not f:
        return None
    m = f.get("metrics_3d") if "metrics_3d" in f else (None if f.get("measurement") else f.get("metrics"))
    m = m or {}
    d = m.get("depth_max_m") if m.get("depth_max_m") is not None else m.get("depth_median_m")
    if not m.get("area_m2") or d is None or float(d) <= 0:
        return None
    return {k: m.get(k) for k in ("area_m2", "depth_max_m", "depth_median_m", "volume_m3")}


def _finding_for(me: dict, t: Target) -> dict:
    if not (t.project and t.survey):
        raise HTTPException(400, "a finding target needs project and survey")
    try:
        proj = store.get_project(t.project)
    except KeyError:
        raise HTTPException(404, "not found") from None
    if proj.get("company_id") != me["company_id"]:
        raise HTTPException(404, "not found")
    an = store.get_analysis(t.project, t.survey)
    f = next((x for x in an["findings"] if x["id"] == t.id), None)
    if f is None:
        raise HTTPException(404, "finding not found")
    return f


def compute(body: MeasureIn, m3d: dict | None, company_id: str | None) -> dict:
    """Everything the measuring sheet shows: size, ranges, warnings, depth, metrics and the bill."""
    try:
        ref = measure.reference(body.ref_type, body.ref_width_cm, body.ref_length_cm)
        if body.first_edge not in (None, "width", "length"):
            raise measure.MeasureError("first_edge must be width or length")
        r = measure.measure((body.image_w, body.image_h), ref, body.ref_points, outline=body.outline, box=body.box,
                            tol_px=body.tol_px, first_edge=body.first_edge)
        rescale, depth_err = None, None
        if body.depth_cm is None and body.rescale_3d:
            try:
                rescale = measure.rescale_depth(r, m3d or {})
            except measure.MeasureError as e:
                depth_err = str(e)
        metrics = measure.finding_metrics(r, depth_cm=body.depth_cm, rescale=rescale)
    except measure.MeasureError as e:
        raise HTTPException(400, str(e)) from None
    depth = ({"source": "typed", "depth_m": metrics["depth_max_m"]} if body.depth_cm is not None
             else {"source": "3d_rescaled", **rescale} if rescale else {"source": None, "error": depth_err})
    if "volume_m3" in metrics:
        dm = metrics["depth_max_m"]
        lo, hi = r["ranges"]["area_m2"]
        if depth["source"] == "3d_rescaled":
            depth["volume_range"] = [round(metrics["volume_m3"] * (lo / r["area_m2"]) ** 1.5, 5),
                                     round(metrics["volume_m3"] * (hi / r["area_m2"]) ** 1.5, 5)]
        else:
            depth["volume_range"] = [round(lo * dm, 5), round(hi * dm, 5)]
    bill = materials.bill(metrics, materials.config(company_id))
    return {"result": r, "metrics": metrics, "depth": depth, "bill": bill,
            "three_d": m3d, "rescale_available": m3d is not None}


def _record(body: MeasureIn, out: dict, me: dict) -> dict:
    r = out["result"]
    ref = {k: r["ref"][k] for k in ("type", "label", "kind", "width_m", "length_m", "first_edge")}
    d = {k: v for k, v in out["depth"].items() if k != "error"}
    return {"source": "reference", "ref": ref, "ref_points": r["ref"]["points"], "outline": r["outline_px"],
            "outline_from": r["outline_from"], "image": {**(body.image.model_dump() if body.image else {"kind": "frame"}),
                                                         "w": body.image_w, "h": body.image_h},
            "tol_px": r["tol_px"], "ranges": r["ranges"], "pct": r["pct"], "warnings": r["warnings"],
            "distance_m": r["distance_m"], "ref_px": r["ref_px"], "longest_m": r["longest_m"], "depth": d,
            "by": me["uid"], "at": time.time()}


def summary(rec: dict | None) -> dict | None:
    """Short form for cards and lists: 'measured with A4 sheet ±4 %'."""
    if not rec:
        return None
    who = auth.person(rec.get("by")) or {}
    pct = (rec.get("pct") or {}).get("area_m2")
    return {"ref": rec["ref"]["label"], "ref_type": rec["ref"]["type"], "pct": pct, "at": rec.get("at"),
            "by": who.get("username"), "by_name": who.get("display_name"), "warnings": rec.get("warnings") or [],
            "depth_source": (rec.get("depth") or {}).get("source"), "k": (rec.get("depth") or {}).get("k"),
            "ranges": rec.get("ranges"), "image": rec.get("image")}


def _check_image(body: MeasureIn) -> None:
    im = body.image
    if im is None:
        return
    if im.kind not in ("frame", "photo", "detection"):
        raise HTTPException(400, "image.kind must be frame, photo or detection")
    if im.file is not None and not FILE_RE.match(im.file):
        raise HTTPException(400, "bad image file name")


# --- preview -----------------------------------------------------------------------------------------------
@router.get("/measure/refs")
def refs(request: Request):
    auth.require(request)
    p = measure.presets()
    return {"refs": p["refs"], "tol_px": measure.TOL_PX, "k_range": list(measure.K_RANGE)}


@router.post("/measure/preview")
def preview(body: MeasureIn, request: Request):
    me = auth.require(request)
    m3d = None
    if body.target is not None and body.target.kind == "finding":
        m3d = three_d(_finding_for(me, body.target))
    elif body.target is not None and body.target.kind != "pin":
        raise HTTPException(400, "target.kind must be finding or pin")
    return compute(body, m3d, me["company_id"])


# --- survey findings -------------------------------------------------------------------------------------------
def _rescore(an: dict) -> None:
    from .analysis.condition import score_segments

    score_segments(an["segments"], an["findings"])


def _finding_out(pid: str, sid: str, f: dict, company_id: str) -> dict:
    from . import jobcard

    return {**f, "cost": jobcard.cost_summary(f, materials.config(company_id)), "measured": summary(f.get("measurement"))}


@router.post("/projects/{pid}/surveys/{sid}/findings/{fid}/measurement")
def save_finding(pid: str, sid: str, fid: str, body: MeasureIn, request: Request):
    me = require_staff(request)
    _check_image(body)
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        f = next((x for x in an["findings"] if x["id"] == fid), None)
        if f is None:
            raise HTTPException(404, "finding not found")
        out = compute(body, three_d(f), me["company_id"])
        if "metrics_3d" not in f and not f.get("measurement"):
            f["metrics_3d"] = copy.deepcopy(f.get("metrics") or {})   # the analysis' own numbers, kept once
        f["metrics_prev"] = copy.deepcopy(f.get("metrics") or {})
        f["measurement_prev"] = f.get("measurement")
        f["metrics"] = out["metrics"]
        f["measurement"] = _record(body, out, me)
        f.setdefault("history", []).append({"t": time.time(), "event": f"measured with {out['result']['ref']['label']}",
                                            "by": me["uid"]})
        _rescore(an)
        store.save_analysis(pid, sid, an)
    return {"finding": _finding_out(pid, sid, f, me["company_id"]), "bill": out["bill"]}


@router.post("/projects/{pid}/surveys/{sid}/findings/{fid}/measurement/undo")
def undo_finding(pid: str, sid: str, fid: str, request: Request):
    me = require_staff(request)
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        f = next((x for x in an["findings"] if x["id"] == fid), None)
        if f is None:
            raise HTTPException(404, "finding not found")
        if "metrics_prev" not in f:
            raise HTTPException(409, "nothing to undo")
        f["metrics"] = f.pop("metrics_prev")
        prev = f.pop("measurement_prev", None)
        if prev:
            f["measurement"] = prev
        else:
            f.pop("measurement", None)
        f.setdefault("history", []).append({"t": time.time(), "event": "measurement undone", "by": me["uid"]})
        _rescore(an)
        store.save_analysis(pid, sid, an)
    return {"finding": _finding_out(pid, sid, f, me["company_id"])}


# --- photos ----------------------------------------------------------------------------------------------------
def _safe(fid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in fid)[:64]


def finding_photo_path(pid: str, sid: str, fid: str):
    return store.survey_dir(pid, sid) / "photos" / f"{_safe(fid)}.jpg"


def pin_photo_path(pin_id: str):
    return DATA_DIR / "pins" / store.check_id(pin_id) / "photo.jpg"


def photo_info(path, url: str, note: str) -> dict | None:
    """The card's photo entry for an uploaded photo, or None."""
    if not path.is_file():
        return None
    return {"url": f"{url}?v={int(path.stat().st_mtime)}", "kind": "photo", "boxes": [], "note": note}


async def _save_photo(up: UploadFile, path) -> dict:
    data = bytearray()
    while chunk := await up.read(1 << 20):
        data += chunk
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, f"the photo is larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
    try:
        images.check_pixels(io.BytesIO(bytes(data)))
    except ValueError as e:
        raise HTTPException(413, f"the photo is too large: {e}") from None
    img = cv2.imdecode(np.frombuffer(bytes(data), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "not a JPEG, PNG or WebP photo")
    h, w = img.shape[:2]
    s = MAX_PHOTO_SIDE / max(h, w)
    if s < 1:
        img = cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])   # re-encoded: no EXIF (no GPS, no camera data)
    if not ok:
        raise HTTPException(400, "could not read the photo")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(jpg.tobytes())
    tmp.replace(path)
    return {"w": int(img.shape[1]), "h": int(img.shape[0]), "bytes": len(jpg)}


@router.post("/projects/{pid}/surveys/{sid}/findings/{fid}/photo")
async def put_finding_photo(pid: str, sid: str, fid: str, request: Request, file: UploadFile = File(...)):
    require_staff(request)
    an = store.get_analysis(pid, sid)
    if not any(x["id"] == fid for x in an["findings"]):
        raise HTTPException(404, "finding not found")
    path = finding_photo_path(pid, sid, fid)
    info = await _save_photo(file, path)
    return {**info, "url": f"/api/projects/{pid}/surveys/{sid}/findings/{fid}/photo?v={int(path.stat().st_mtime)}"}


@router.get("/projects/{pid}/surveys/{sid}/findings/{fid}/photo")
def get_finding_photo(pid: str, sid: str, fid: str):
    path = finding_photo_path(pid, sid, fid)
    if not path.is_file():
        raise HTTPException(404, "no photo")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _pin_row(pin_id: str) -> dict:
    pins.ensure_schema()
    row = db.one("SELECT * FROM pins WHERE id=?", pin_id)
    if row is None:
        raise HTTPException(404, "no such pin")
    return row


@router.post("/pins/{pin_id}/photo")
async def put_pin_photo(pin_id: str, request: Request, file: UploadFile = File(...)):
    require_staff(request)
    _pin_row(pin_id)
    path = pin_photo_path(pin_id)
    info = await _save_photo(file, path)
    return {**info, "url": f"/api/pins/{pin_id}/photo?v={int(path.stat().st_mtime)}"}


@router.get("/pins/{pin_id}/photo")
def get_pin_photo(pin_id: str, request: Request):
    auth.require(request)
    _pin_row(pin_id)
    path = pin_photo_path(pin_id)
    if not path.is_file():
        raise HTTPException(404, "no photo")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# --- pins ----------------------------------------------------------------------------------------------------------
@router.post("/pins/{pin_id}/measurement")
def save_pin(pin_id: str, body: MeasureIn, request: Request):
    me = require_staff(request)
    _check_image(body)
    row = _pin_row(pin_id)
    out = compute(body, None, me["company_id"])
    m = out["metrics"]
    old = json.loads(row["measure"]) if row.get("measure") else None
    prev = {"size": row.get("size"), "measure": {k: old[k] for k in ("metrics", "measurement")} if old else None}  # one step
    size = row.get("size")
    if "depth_max_m" in m:  # the typed-size form shows the same numbers
        size = json.dumps({"width_cm": round(m["width_m"] * 100, 1), "length_cm": round(m["length_m"] * 100, 1),
                           "depth_cm": round(m["depth_max_m"] * 100, 1)})
    rec = {"metrics": m, "measurement": _record(body, out, me), "prev": prev}
    db.run("UPDATE pins SET size=?, measure=? WHERE id=?", size, json.dumps(rec), pin_id)
    return {"pin": pins._out(db.one("SELECT * FROM pins WHERE id=?", pin_id)), "bill": out["bill"]}


@router.post("/pins/{pin_id}/measurement/undo")
def undo_pin(pin_id: str, request: Request):
    require_staff(request)
    row = _pin_row(pin_id)
    if not row.get("measure"):
        raise HTTPException(409, "nothing to undo")
    prev = json.loads(row["measure"]).get("prev")
    if prev is None:
        raise HTTPException(409, "nothing to undo")
    db.run("UPDATE pins SET size=?, measure=? WHERE id=?", prev.get("size"),
           json.dumps(prev["measure"]) if prev.get("measure") else None, pin_id)
    return {"pin": pins._out(db.one("SELECT * FROM pins WHERE id=?", pin_id))}

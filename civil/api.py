"""HTTP API + static UI."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import re
import time

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from . import auth, catalog, chat, check3d, helper, worker, groups, jobcard, location, materials, pins, pipeline, planning, priority, settings, store, xmpp
from .analysis.condition import score_segments
from .config import ALLOWED_HOSTS, DEFAULT_ORIGIN, MAX_UPLOAD_BYTES, STATIC_DIR, unit_costs
from .decoders import registry
from .pointcloud import Reconstruction, enu_to_latlon, voxel_downsample
from .verify import verify as run_verify

@contextlib.asynccontextmanager
async def _lifespan(_app):
    yield
    # `civil serve` starts ejabberd before uvicorn; stop it here, because uvicorn re-raises SIGTERM
    # after shutting down and a `finally` in the CLI would never run. No-op if we didn't start it.
    await asyncio.to_thread(xmpp.stop)


app = FastAPI(title="iScale", version="0.3.0", lifespan=_lifespan)
app.include_router(auth.router)
app.include_router(pins.router)
app.include_router(priority.router)
app.include_router(helper.router)
app.include_router(groups.router)
app.include_router(settings.router)
app.include_router(jobcard.router)
app.include_router(xmpp.router)
app.include_router(location.router)
app.include_router(check3d.router)
app.include_router(worker.router)

# A web page on another site must not drive this local API:
# - Host check stops DNS-rebinding (a hostile domain resolving to 127.0.0.1);
# - every state-changing /api call must carry the X-Civil-Scan header, which a browser
#   only lets other origins send after a CORS preflight that this server never grants.
CSRF_HEADER = "x-civil-scan"


PUBLIC_API = ("/api/auth/state", "/api/auth/setup", "/api/auth/register", "/api/auth/challenge", "/api/auth/login", "/api/auth/logout")
PROJECT_PATH = re.compile(r"^/api/projects/([^/]+)")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "missing X-Civil-Scan header"}, status_code=403)
            size = request.headers.get("content-length")
            if size and size.isdigit() and int(size) > MAX_UPLOAD_BYTES + 1_000_000:
                return JSONResponse({"detail": "upload too large"}, status_code=413)
        if path not in PUBLIC_API and not path.startswith("/api/worker/"):  # the worker routes check their own token
            user = auth.session_user(request)
            if user is None:
                return JSONResponse({"detail": "sign in first"}, status_code=401)
            request.state.user = user
            m = PROJECT_PATH.match(path)
            if m:  # every project URL is checked against the signed-in user's company
                try:
                    proj = store.get_project(m.group(1))
                except KeyError:
                    return JSONResponse({"detail": "not found"}, status_code=404)
                if proj.get("company_id") != user["company_id"]:
                    return JSONResponse({"detail": "not found"}, status_code=404)
    response = await call_next(request)
    if path == "/" or (path.startswith("/static/") and not path.startswith("/static/vendor/")):
        # app code changes between versions: let the browser keep it but revalidate every load
        response.headers["Cache-Control"] = "no-cache"
    return response


PERMISSIONS = "camera=(self), geolocation=(self), microphone=(), payment=(), usb=(), interest-cohort=()"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Browser hardening on every response (registered after `guard`, so it also covers its 401/403s)."""
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")  # no clickjacking: never framed (CSP frame-ancestors for new browsers)
    h.setdefault("Referrer-Policy", "same-origin")  # project/survey ids in URLs never leak to tile or map hosts
    h.setdefault("Permissions-Policy", PERMISSIONS)
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        # API answers are data, never documents: nothing may run or load if one is opened directly
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if h.get("content-type", "").startswith("application/json"):
            h.setdefault("Cache-Control", "no-store")  # personal and company data: not kept in shared or disk caches
    else:
        h.setdefault("Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
    if request.url.scheme == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.exception_handler(KeyError)
async def _not_found(_: Request, exc: KeyError):
    return JSONResponse({"detail": str(exc).strip("'\"") or "not found"}, status_code=404)


@app.exception_handler(ValueError)
async def _bad(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# --- models ----------------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str = Field(max_length=120)
    origin_lat: float = DEFAULT_ORIGIN[0]
    origin_lon: float = DEFAULT_ORIGIN[1]


class FindingIn(BaseModel):
    type: str
    x: float
    y: float
    z: float = 0.0
    severity: str | None = None
    note: str = Field(default="", max_length=500)
    size_m: float = Field(default=0.5, gt=0, le=20)


class FindingPatch(BaseModel):
    status: str | None = None
    severity: str | None = None
    type: str | None = None
    note: str | None = Field(default=None, max_length=500)


class WorkOrderIn(BaseModel):
    survey_id: str
    finding_ids: list[str] = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=120)


class WorkOrderPatch(BaseModel):
    status: str


class VerifyIn(BaseModel):
    before: str
    after: str
    workorder_id: str | None = None


class ChatIn(BaseModel):
    message: str = Field(max_length=2000)
    survey_id: str | None = None


FINDING_STATES = {"open", "planned", "fixed", "verified", "not_fixed", "dismissed"}
WO_STATES = {"open", "scheduled", "completed", "verified", "partially_verified", "cancelled"}


# --- meta -----------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    costs = unit_costs()
    return {"catalog": catalog.as_list(), "severities": list(catalog.SEVERITIES),
            "decoders": [d.describe() for d in registry().values()],
            "currency": costs.get("currency", "USD"), "default_origin": DEFAULT_ORIGIN}


# --- projects -----------------------------------------------------------------------------
@app.get("/api/projects")
def projects(request: Request):
    return store.list_projects(auth.require(request)["company_id"])


@app.post("/api/projects")
def create_project(p: ProjectIn, request: Request):
    return store.create_project(p.name, p.origin_lat, p.origin_lon, auth.require(request)["company_id"])


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    proj = store.get_project(pid)
    proj["survey_list"] = store.list_surveys(pid)
    return proj


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, request: Request):
    auth.require_admin(request)
    store.get_project(pid)
    store.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/baseline/{sid}")
def set_baseline(pid: str, sid: str):
    with store.lock(pid):
        proj = store.get_project(pid)
        if sid not in proj["surveys"]:
            raise KeyError("survey not in project")
        proj["baseline"] = sid
        store.save_project(proj)
    return proj


@app.post("/api/demo")
def demo(request: Request):
    proj = store.create_project("Demo district (synthetic)", *DEFAULT_ORIGIN, auth.require(request)["company_id"])
    a = store.create_survey(proj["id"], "Baseline drive", "demo", {"repaired": False})
    b = store.create_survey(proj["id"], "After repairs", "demo", {"repaired": True})
    pipeline.submit(proj["id"], a["id"])
    pipeline.submit(proj["id"], b["id"])
    proj = store.get_project(proj["id"])
    proj["baseline"] = a["id"]
    store.save_project(proj)
    return proj


# --- surveys ---------------------------------------------------------------------------------
@app.post("/api/projects/{pid}/surveys")
async def create_survey(pid: str, request: Request, name: str = Form(...), decoder: str = Form(...), params: str = Form("{}"),
                        files: list[UploadFile] | None = File(default=None), recorded: bool = Form(False),
                        device_track: str = Form("", max_length=2_000_000)):
    """`recorded`: the video was recorded in iScale's browser recorder. `device_track`: the GPS track
    this device logged during that recording, JSON [[t_s, lat, lon, accuracy_m], ...]; accepted only
    when the uploader has location on (agreement accepted)."""
    me = auth.require(request)
    store.get_project(pid)
    track = None
    if device_track:
        location.require_enabled(me)
        track = location.parse_track(device_track)
        if len(track) < 2:
            track = None  # too short to use; the survey falls back to camera height
    decs = registry()
    if decoder not in decs:
        raise HTTPException(400, f"unknown decoder {decoder}")
    if decs[decoder].internal:
        raise HTTPException(400, "this decoder is used internally by video jobs")
    ok, why = decs[decoder].available()
    if not ok:
        raise HTTPException(400, f"decoder unavailable: {why}")
    try:
        prm = json.loads(params or "{}")
        if not isinstance(prm, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "params must be a JSON object")
    allowed = {"repaired", "density", "seed", "metric", "up_axis", "camera_height_m", "heading_deg",
               "start_east_m", "start_north_m", "analysis"}
    prm = {k: v for k, v in prm.items() if k in allowed}
    if recorded:
        prm["recorded"] = True
    if track:
        prm["device_gps_by"] = me["uid"]  # whose location this is (Settings, Location, Delete my tracks)
    sv = store.create_survey(pid, name, decoder, prm)
    d = store.survey_dir(pid, sv["id"]) / "input"
    total = 0
    for up in files or []:
        fname = store.safe_filename(up.filename or "upload")
        if track and fname.lower().endswith(".csv"):
            continue  # the device track is the survey's only GPS file
        target = d / fname
        with open(target, "wb") as out:
            while chunk := await up.read(1 << 20):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    out.close()
                    store.update_survey(pid, sv["id"], status="error", error="upload too large")
                    raise HTTPException(413, "upload too large")
                out.write(chunk)
    if track:
        location.write_track(d, track)
    pipeline.submit(pid, sv["id"])
    return sv


@app.get("/api/projects/{pid}/surveys/{sid}")
def get_survey(pid: str, sid: str):
    return store.get_survey(pid, sid)


@app.get("/api/projects/{pid}/surveys/{sid}/video")
def get_video(pid: str, sid: str):
    f = store.survey_dir(pid, sid) / "video.json"
    if not f.is_file():
        raise KeyError("no video job for this survey yet")
    rec = json.loads(f.read_text())
    for c in rec.get("children", []):
        try:
            c["survey"] = store.get_survey(pid, c["survey_id"])
        except KeyError:
            c["survey"] = None
    return rec


@app.get("/api/projects/{pid}/surveys/{sid}/video/image/{name}")
def video_image(pid: str, sid: str, name: str):
    if not re.fullmatch(r"t[0-9_]+(_bev)?\.jpg", name):
        raise KeyError("not found")
    f = store.survey_dir(pid, sid) / "work" / "detections" / name
    if not f.is_file():
        raise KeyError("not found")
    return FileResponse(f, media_type="image/jpeg")


@app.post("/api/projects/{pid}/surveys/{sid}/retry")
def retry_survey(pid: str, sid: str):
    sv = store.get_survey(pid, sid)
    if sv["status"] not in ("error", "done"):
        raise HTTPException(409, "survey is still queued or running")
    if sv["decoder"] == "pothole_video":
        raise HTTPException(400, "retry the failed clips instead of the whole video job")
    sv = store.update_survey(pid, sid, status="queued", stage="", error=None)
    pipeline.submit(pid, sid)
    return sv


@app.get("/api/projects/{pid}/surveys/{sid}/analysis")
def get_analysis(pid: str, sid: str, request: Request):
    an = store.get_analysis(pid, sid)
    an.pop("path", None)
    cfg = materials.config(request.state.user["company_id"])
    for f in an["findings"]:
        f["cost"] = jobcard.cost_summary(f, cfg)
    for s in an["segments"]:
        s.pop("line", None)
    return an


@app.get("/api/projects/{pid}/surveys/{sid}/points.bin")
def points(pid: str, sid: str, max_points: int = 1_500_000, voxel: float = 0.04):
    max_points = int(np.clip(max_points, 10_000, 5_000_000))
    voxel = float(np.clip(voxel, 0.01, 1.0))
    rec = Reconstruction.load(store.recon_path(pid, sid))
    idx = voxel_downsample(rec.points, voxel, max_points)
    from .check3d import pothole_mask

    det = pothole_mask(rec)
    has_labels = det is not None and bool(det.any())
    if has_labels:
        # keep the points inside the detector's boxes even where thinning would drop them, so people
        # can see exactly what the detector marked in 3D (capped so a huge clip stays loadable)
        marked = np.flatnonzero(det)
        if len(marked) > 400_000:
            marked = marked[np.linspace(0, len(marked) - 1, 400_000).astype(int)]
        idx = np.union1d(idx, marked)
    xyz = rec.points[idx].astype("<f4")
    rgb = rec.colors[idx] if rec.colors is not None else np.full((len(idx), 3), 180, np.uint8)
    body = xyz.tobytes() + np.ascontiguousarray(rgb, dtype=np.uint8).tobytes()
    hdr = {"X-Point-Count": str(len(idx))}
    if has_labels:  # one byte per point after the colours: 1 = inside a pothole-detector box
        lab = det[idx].astype(np.uint8)
        body += lab.tobytes()
        hdr["X-Labels"] = "detector"
        hdr["X-Detector-Points"] = str(int(lab.sum()))
    traj = rec.trajectory()
    if traj is not None:
        hdr["X-Trajectory"] = json.dumps(np.round(traj[::4], 2).tolist())[:60000]
    return Response(body, media_type="application/octet-stream", headers=hdr)


# --- findings -----------------------------------------------------------------------------------
def _rescore(an: dict) -> None:
    score_segments(an["segments"], an["findings"])


def _nearest_segment(an: dict, x: float, y: float) -> str | None:
    best, bid = 1e18, None
    for s in an["segments"]:
        line = np.array(s.get("line") or [])
        if len(line):
            d = float(np.min(np.hypot(line[:, 0] - x, line[:, 1] - y)))
            if d < best:
                best, bid = d, s["id"]
    return bid


@app.post("/api/projects/{pid}/surveys/{sid}/findings")
def add_finding(pid: str, sid: str, f: FindingIn):
    if f.type not in catalog.CATALOG:
        raise HTTPException(400, "unknown type")
    if f.severity is not None and f.severity not in catalog.SEVERITIES:
        raise HTTPException(400, "bad severity")
    proj = store.get_project(pid)
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        n = sum(1 for x in an["findings"] if x["id"].startswith("M-")) + 1
        h = f.size_m / 2
        lat, lon = enu_to_latlon(np.array([f.x]), np.array([f.y]), proj["origin_lat"], proj["origin_lon"])
        it = catalog.CATALOG[f.type]
        item = {"id": f"M-{n:04d}", "type": f.type, "severity": f.severity if it.kind == "defect" else None,
                "source": "manual", "x": f.x, "y": f.y, "z": f.z, "lat": float(lat[0]), "lon": float(lon[0]),
                "bbox": [f.x - h, f.y - h, f.z - 0.1, f.x + h, f.y + h, f.z + max(0.2, h)],
                "metrics": {"area_m2": round(f.size_m ** 2, 3)} if it.unit == "m2" else {},
                "evidence": f"tagged manually{': ' + f.note if f.note else ''}", "status": "open",
                "segment_id": _nearest_segment(an, f.x, f.y),
                "history": [{"t": time.time(), "event": "created", "by": "manual"}]}
        an["findings"].append(item)
        _rescore(an)
        store.save_analysis(pid, sid, an)
    return item


@app.patch("/api/projects/{pid}/surveys/{sid}/findings/{fid}")
def patch_finding(pid: str, sid: str, fid: str, patch: FindingPatch):
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        f = next((x for x in an["findings"] if x["id"] == fid), None)
        if f is None:
            raise KeyError("finding not found")
        if patch.status is not None:
            if patch.status not in FINDING_STATES:
                raise HTTPException(400, "bad status")
            f["status"] = patch.status
        if patch.severity is not None:
            if patch.severity not in catalog.SEVERITIES:
                raise HTTPException(400, "bad severity")
            f["severity"] = patch.severity
        if patch.type is not None:
            if patch.type not in catalog.CATALOG:
                raise HTTPException(400, "unknown type")
            f["type"] = patch.type
        if patch.note is not None:
            f["note"] = patch.note
        f.setdefault("history", []).append({"t": time.time(), "event": "edited",
                                            "fields": [k for k, v in patch.model_dump().items() if v is not None]})
        _rescore(an)
        store.save_analysis(pid, sid, an)
    return f


@app.get("/api/projects/{pid}/surveys/{sid}/export.{fmt}")
def export(pid: str, sid: str, fmt: str):
    an = store.get_analysis(pid, sid)
    if fmt == "geojson":
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]},
                  "properties": {k: v for k, v in f.items() if k not in ("history", "bbox")}} for f in an["findings"]]
        feats += [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": s["coords"]},
                   "properties": {k: s.get(k) for k in ("id", "condition", "rating", "length_m", "defect_count")}}
                  for s in an["segments"] if s.get("coords")]
        return Response(json.dumps({"type": "FeatureCollection", "features": feats}), media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="findings-{sid}.geojson"'})
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "type", "label", "severity", "status", "segment", "lat", "lon", "source", "evidence"])
        for f in an["findings"]:
            w.writerow([f["id"], f["type"], catalog.CATALOG[f["type"]].label, f.get("severity") or "", f.get("status"),
                        f.get("segment_id") or "", f"{f['lat']:.7f}", f"{f['lon']:.7f}", f["source"], _csv_text(f["evidence"])])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="findings-{sid}.csv"'})
    if fmt == "ply":
        return _export_ply(pid, sid)
    raise HTTPException(400, "format must be geojson, csv or ply")


def _csv_text(v) -> str:
    """Text a person may have typed: a leading = + - @ (or tab/CR) would make Excel run it as a formula."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _export_ply(pid: str, sid: str):
    """The full LingBot-Map point cloud after alignment, for checking in CloudCompare, MeshLab etc.

    Every point (not the thinned web view), in metres: x east, y north, z up from the project origin.
    `detector` = 1 for points inside the pothole detector's boxes. Cached until the survey is re-run.
    """
    from .check3d import pothole_mask
    from .pointcloud import write_ply

    src = store.recon_path(pid, sid)
    if not src.exists():
        raise HTTPException(404, "this survey has no 3D reconstruction")
    out = store.survey_dir(pid, sid) / "work" / "export" / "cloud.ply"
    with store.lock(pid):
        if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
            rec = Reconstruction.load(src)
            proj = store.get_project(pid)
            sv = store.get_survey(pid, sid)
            det = pothole_mask(rec)
            rgb = rec.colors if rec.colors is not None else np.full((rec.n, 3), 180, np.uint8)
            comments = ["iScale 3D point cloud (LingBot-Map reconstruction, aligned)",
                        f"survey {sid} {' '.join(str(sv.get('name', '')).split())[:80]}",
                        "units metres; x east, y north, z up (ENU)",
                        f"origin_lat {proj['origin_lat']:.7f}", f"origin_lon {proj['origin_lon']:.7f}",
                        "detector 1 = point inside a pothole detector box"]
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            write_ply(tmp, rec.points, rgb, comments=comments,
                      flags={"detector": (det if det is not None else np.zeros(rec.n, bool)).astype(np.uint8)})
            tmp.replace(out)
    return FileResponse(out, media_type="application/octet-stream", filename=f"iscale-3d-{sid}.ply")


# --- planning & work orders -------------------------------------------------------------------------
@app.get("/api/projects/{pid}/surveys/{sid}/plan")
def plan(pid: str, sid: str, mode: str = "spot", budget: float | None = None):
    an = store.get_analysis(pid, sid)
    if budget is not None and budget <= 0:
        budget = None
    if mode == "segment":
        return planning.segment_plan(an["segments"], budget)
    tbs = {s["id"]: s.get("traffic") for s in an["segments"] if s.get("traffic")}
    return planning.spot_plan(an["findings"], budget, traffic_by_segment=tbs)


@app.get("/api/projects/{pid}/workorders")
def workorders(pid: str):
    store.get_project(pid)
    return store.get_workorders(pid)


@app.post("/api/projects/{pid}/workorders")
def create_workorder(pid: str, wo: WorkOrderIn):
    with store.lock(pid):
        an = store.get_analysis(pid, wo.survey_id)
        p = planning.spot_plan(an["findings"], None, ids=wo.finding_ids)
        if not p["items"]:
            raise HTTPException(400, "none of these findings is an open, repairable defect")
        wos = store.get_workorders(pid)
        wid = f"WO-{len(wos) + 1:04d}"
        order = {"id": wid, "title": wo.title or f"{len(p['items'])} repairs", "survey_id": wo.survey_id,
                 "status": "open", "created": time.time(), "items": p["items"], "total": p["total"],
                 "currency": p["currency"], "verification": None}
        ids = {i["finding_id"] for i in p["items"]}
        for f in an["findings"]:
            if f["id"] in ids:
                f["status"] = "planned"
                f["workorder_id"] = wid
                f.setdefault("history", []).append({"t": time.time(), "event": "planned", "workorder": wid})
        store.save_analysis(pid, wo.survey_id, an)
        wos.append(order)
        store.save_workorders(pid, wos)
    return order


@app.patch("/api/projects/{pid}/workorders/{wid}")
def patch_workorder(pid: str, wid: str, patch: WorkOrderPatch):
    if patch.status not in WO_STATES:
        raise HTTPException(400, "bad status")
    with store.lock(pid):
        wos = store.get_workorders(pid)
        wo = next((w for w in wos if w["id"] == wid), None)
        if wo is None:
            raise KeyError("work order not found")
        wo["status"] = patch.status
        if patch.status in ("completed", "cancelled"):
            an = store.get_analysis(pid, wo["survey_id"])
            ids = {i["finding_id"] for i in wo["items"]}
            for f in an["findings"]:
                if f["id"] in ids and f.get("status") in ("planned", "open", "not_fixed"):
                    f["status"] = "fixed" if patch.status == "completed" else "open"
                    f.setdefault("history", []).append({"t": time.time(), "event": f"workorder {patch.status}"})
            _rescore(an)
            store.save_analysis(pid, wo["survey_id"], an)
        store.save_workorders(pid, wos)
    return wo


# --- verification ------------------------------------------------------------------------------------
@app.post("/api/projects/{pid}/verify")
def verify(pid: str, body: VerifyIn):
    with store.lock(pid):
        before = store.get_analysis(pid, body.before)
        after = store.get_analysis(pid, body.after)
        rec = Reconstruction.load(store.recon_path(pid, body.after))
        wos = store.get_workorders(pid)
        only = None
        wo = None
        if body.workorder_id:
            wo = next((w for w in wos if w["id"] == body.workorder_id), None)
            if wo is None:
                raise KeyError("work order not found")
            only = [i["finding_id"] for i in wo["items"]]
        res = run_verify(before["findings"], after["findings"], rec, only)
        res.update({"before": body.before, "after": body.after, "workorder_id": body.workorder_id})
        by_id = {r["finding_id"]: r for r in res["results"]}
        for f in before["findings"]:
            r = by_id.get(f["id"])
            if r and r["status"] in ("verified", "not_fixed"):
                f["status"] = r["status"]
                f["verification"] = {"status": r["status"], "evidence": r["evidence"], "after_survey": body.after}
                f.setdefault("history", []).append({"t": time.time(), "event": f"verification: {r['status']}"})
        _rescore(before)
        store.save_analysis(pid, body.before, before)
        for w in wos:
            if w["survey_id"] != body.before:
                continue
            ids = [i["finding_id"] for i in w["items"]]
            st = [by_id[i]["status"] for i in ids if i in by_id]
            if st and w["status"] in ("open", "scheduled", "completed", "partially_verified"):
                n_ok = st.count("verified")
                w["verification"] = {"verified": n_ok, "total": len(ids), "after_survey": body.after}
                if n_ok == len(ids):
                    w["status"] = "verified"
                elif n_ok:
                    w["status"] = "partially_verified"
        store.save_workorders(pid, wos)
        (store.project_dir(pid) / "verification.json").write_text(json.dumps(res))
    return res


@app.get("/api/projects/{pid}/verification")
def get_verification(pid: str):
    p = store.project_dir(pid) / "verification.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text())


# --- assistant -------------------------------------------------------------------------------------------
@app.post("/api/projects/{pid}/chat")
def chat_endpoint(pid: str, body: ChatIn, request: Request):
    """Survey questions are answered from the data by fixed rules; anything the rules don't
    recognise goes to Civil Helper (RAG over the company library, with this survey as context)."""
    me = auth.require(request)
    proj = store.get_project(pid)
    sid = body.survey_id or proj.get("baseline")
    an = None
    if sid:
        try:
            an = store.get_analysis(pid, sid)
        except KeyError:
            an = None
    ver = get_verification(pid)
    r = chat.answer(body.message, an, store.get_workorders(pid), ver)
    if r.get("matched", True):
        r["by"] = "rules"
        return r
    f = helper.ask(me["company_id"], body.message, pid, sid)
    return {"reply": f["answer"], "highlight": [], "segments": [], "plan": None, "by": "helper",
            "sources": f["sources"], "model": f["model"], "seconds": f["seconds"]}


# --- static UI ----------------------------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

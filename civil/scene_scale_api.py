"""HTTP routes and the survey rescale for scene-reference scaling (the maths is in civil/scene_scale.py).

  GET  /api/scene_scale/refs                                  catalog of standard-size objects (+ custom)
  GET  /api/projects/{pid}/surveys/{sid}/scale                current scale: method, ±, references, undo
  POST /api/projects/{pid}/surveys/{sid}/scale/preview        taps -> 3D points, d3, implied scale ±; stores nothing
  POST /api/projects/{pid}/surveys/{sid}/scale/apply          rescale the clip and re-run the analysis (staff)
  POST /api/projects/{pid}/surveys/{sid}/scale/undo           back to the previous scale (staff)

Apply multiplies the stored recon (points and camera poses) by the combined factor k about the
first camera's foot point (the clip stays put on the map, the ground stays at z = 0), then re-runs
the same analysis as the pipeline (findings, segments, condition); the 3D check reads the recon
afresh. Findings are matched to the previous ones by position (scaled the same way), so ids,
status, work orders, reviews, photos and reference-object measurements stay with the same pothole:

  metrics       analysis numbers: the new ones; a reference-object measurement's numbers stay
  metrics_3d    the analysis' own numbers behind a measurement: the new ones
  metrics_prev  (undo of a measurement) the new 3D numbers when they were the 3D before, else kept
  rescaled depth of a measurement ("3D × k"): recomputed from the new 3D depth and area

survey.json gets `scale` (method, label, ±, the references with their taps, a history used by
undo) and a line in `notes`; params.scene_refs keeps the references so that rebuilding the clip
(Try again) scales it the same way (civil/align.py prefers them to the camera height).
Access: like measure_api, project URLs are checked against the user's company by the API guard;
writes need a staff account.
"""

from __future__ import annotations

import copy
import math
import time

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, measure, scene_scale, store
from .measure_api import require_staff
from .pointcloud import Reconstruction, enu_to_latlon

router = APIRouter(prefix="/api")

PREVIEW_DRAWS = 80
APPLY_DRAWS = 120
MATCH_M = 0.6            # a new finding within this distance (or inside the old box) is the same one
METHOD_TEXT = {"gps": "GPS track", "metric": "metric 3D model", "camera_height": "camera height guess",
               "unknown": "unknown", "scene": "scene references"}


# --- bodies --------------------------------------------------------------------------------------------
class Tap(BaseModel):
    frame: int = Field(ge=0, le=100_000)
    x: float = Field(ge=-1, le=30_000)
    y: float = Field(ge=-1, le=30_000)


class RefIn(BaseModel):
    ref_id: str = Field(default="custom", max_length=60)
    known_m: float | None = Field(default=None, gt=0, le=1000)     # custom distance
    tol_m: float | None = Field(default=None, ge=0, le=100)         # its ±
    points: list[Tap] = Field(min_length=2, max_length=2)


class ScaleIn(BaseModel):
    refs: list[RefIn] = Field(min_length=1, max_length=20)
    tol_px: float = Field(default=scene_scale.TOL_PX, ge=0, le=30)


# --- survey helpers ----------------------------------------------------------------------------------------
def _frames_dir(pid: str, sid: str):
    return store.survey_dir(pid, sid) / "input" / "frames"


def _frame_count(pid: str, sid: str) -> int:
    d = _frames_dir(pid, sid)
    return len(list(d.glob("*.jpg"))) if d.is_dir() else 0


def _intrinsics_fallback(pid: str, sid: str, n: int):
    """Clips decoded before the intrinsics were kept in the recon: read them from the decoder's files."""
    import json

    work = store.survey_dir(pid, sid) / "work"
    pj = work / "decoded" / "poses.json"
    if pj.is_file():
        ks = json.loads(pj.read_text()).get("intrinsics")
        if ks and len(ks) == n:
            return ks
    raw = sorted((work / "lingbot_raw").rglob("frame_*.npz")) if (work / "lingbot_raw").is_dir() else []
    if len(raw) == n:
        out = []
        for f in raw:
            with np.load(f, allow_pickle=False) as z:
                if "intrinsic" not in z.files:
                    return None
                a = np.asarray(z["intrinsic"], dtype=np.float64)
                out.append(a.reshape(-1, 3, 3)[0].tolist())
        return out
    return None


def _geometry(pid: str, sid: str, rec: Reconstruction):
    import json

    if rec.meta.get("frame_geometry"):
        return rec.meta["frame_geometry"]
    bj = store.survey_dir(pid, sid) / "input" / "boxes.json"
    if bj.is_file():
        return json.loads(bj.read_text()).get("geometry")
    return None


def cameras(pid: str, sid: str, rec: Reconstruction) -> list[scene_scale.Camera]:
    n = _frame_count(pid, sid)
    if rec.poses is None or n == 0:
        raise scene_scale.ScaleError("This survey has no video frames with camera poses: scene objects can only fix "
                                     "the scale of a 3D clip from a drive video.")
    if n != len(rec.poses):
        raise scene_scale.ScaleError(f"The clip has {n} frames but {len(rec.poses)} camera poses; rebuild it with Try again.")
    ks = rec.meta.get("intrinsics")
    if ks is None:
        ks = _intrinsics_fallback(pid, sid, n)
    return scene_scale.cameras_from_rec(rec, intrinsics=ks, geo=_geometry(pid, sid, rec))


def _load(pid: str, sid: str) -> tuple[dict, Reconstruction]:
    sv = store.get_survey(pid, sid)
    if sv.get("status") != "done":
        raise HTTPException(409, "the 3D clip is not ready yet")
    path = store.recon_path(pid, sid)
    if not path.is_file():
        raise HTTPException(404, "this survey has no 3D model")
    return sv, Reconstruction.load(path)


def _resolve(body: ScaleIn) -> list[dict]:
    cat = scene_scale.load_catalog()
    out = []
    for i, r in enumerate(body.refs):
        try:
            info = scene_scale.resolve(r.model_dump(), cat)
        except scene_scale.ScaleError as e:
            raise HTTPException(400, f"Reference {i + 1}: {e}") from None
        out.append({"ref_id": info["id"], "label": info["label"], "group": info["group"], "known_m": info["known_m"],
                    "rel_error": info["rel_error"], "rel_unknown": info["rel_unknown"], "tol_m": r.tol_m,
                    "provisional": bool(info.get("provisional")), "vertical": bool(info.get("vertical")),
                    "points": [{"frame": p.frame, "xy": [p.x, p.y]} for p in r.points]})
    return out


def _round(v, n=4):
    return [round(float(x), n) for x in v]


def _ref_out(spec: dict, r: dict) -> dict:
    base = {k: spec.get(k) for k in ("ref_id", "label", "group", "known_m", "rel_error", "rel_unknown", "tol_m", "provisional")}
    base["points"] = spec["points"]
    if "error" in r:
        return {**base, "error": r["error"]}
    return {**base, "scale": round(r["scale"], 5), "pct": r["pct"], "range": _round(r["range"], 5),
            "d3": round(r["d3"], 5), "points_3d": [_round(p) for p in r["points_3d"]], "support": r["support"],
            "method": r["method"], "rel_meas": round(r["rel_meas"], 5), "warnings": r["warnings"],
            "outlier": r.get("outlier", False), "z": r.get("z")}


def scale_summary(sv: dict) -> dict:
    """{method, text, pct, ...} for the clip row, the 3D view and the sheet."""
    sc = sv.get("scale")
    if not sc:
        notes = " | ".join(sv.get("notes") or [])
        if "georeferenced to GPS" in notes:
            sc = {"method": "gps"}
        elif "scene reference" in notes and "scale from" in notes:
            sc = {"method": "scene"}
        elif "scale from camera height" in notes:
            sc = {"method": "camera_height"}
        elif "scale unknown" in notes:
            sc = {"method": "unknown"}
        else:
            sc = {"method": "metric" if sv.get("decoder") in ("demo",) else "unknown"}
    m = sc.get("method", "unknown")
    if m == "scene":
        n = len([r for r in sc.get("refs") or [] if not r.get("outlier") and "error" not in r]) or len(sc.get("refs") or [])
        text = f"{n} scene reference{'s' if n != 1 else ''}" + (f" ±{sc['pct']:.0f}%" if sc.get("pct") is not None else "")
    else:
        text = METHOD_TEXT.get(m, m)
    hist = sc.get("history") or []
    return {"method": m, "text": text, "label": sc.get("label"), "pct": sc.get("pct"), "refs": sc.get("refs") or [],
            "total": sc.get("total", 1.0), "can_undo": bool(hist), "steps": len(hist),
            "at": hist[-1]["at"] if hist else None, "factor": sc.get("factor"), "range": sc.get("range"),
            "provisional": bool(sc.get("provisional")), "mark": scale_mark(sv, sc)}


def scale_mark(sv: dict, sc: dict | None = None) -> str | None:
    """The line shown with a 3D-measured finding (drawer, job card, CSV): where its size comes from.
    None when the scale is real (GPS, metric decoder) and there is nothing to warn about."""
    if sc is None:
        return scale_summary(sv)["mark"]
    m = sc.get("method", "unknown")
    if m == "scene":
        refs = sc.get("refs") or []
        used = [i for i, r in enumerate(refs) if not r.get("outlier") and "error" not in r]
        parts = sc.get("parts") or (scene_scale.describe_parts(refs, used) if refs else "scene references")
        pct = sc.get("pct")
        return (f"Scaled by: {parts}" + (f", ±{pct:.0f}%" if pct is not None else "")
                + (" (provisional sizes)" if sc.get("provisional") else ""))
    if m == "camera_height":
        return "Scale: camera height guess, not measured"
    if m == "unknown":
        return "Scale unknown: sizes are relative"
    return None


def finding_mark(f: dict, mark: str | None) -> str | None:
    """The scale line for one finding: only when its size comes from the 3D clip (not typed, not measured on a photo)."""
    if not mark or f.get("source") == "manual" or f.get("measurement") or not (f.get("metrics") or {}).get("area_m2"):
        return None
    return mark


# --- carrying user data across a re-analysis ----------------------------------------------------------------
ANALYSIS_KEYS = {"id", "type", "x", "y", "z", "bbox", "metrics", "severity", "evidence", "source", "segment_id",
                 "segments", "lat", "lon", "status", "history", "cost", "measured"}
FAMILY = {"pothole": "dep", "depression": "dep", "manhole_sunken": "dep", "sunken_manhole": "dep"}


def scale_metrics(m: dict | None, k: float) -> dict:
    """Lengths × k, areas × k², volumes × k³ (by the key's unit suffix); everything else unchanged."""
    out = {}
    for key, v in (m or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
            if key.endswith("_m3"):
                v = round(v * k ** 3, 6)
            elif key.endswith("_m2"):
                v = round(v * k ** 2, 5)
            elif key.endswith("_m") or key.endswith("_mm"):
                v = round(v * k, 5)
        out[key] = v
    return out


def _user_fields(f: dict) -> set[str]:
    out: set[str] = set()
    for h in f.get("history") or []:
        if h.get("event") == "edited":
            out |= set(h.get("fields") or [])
    return out


def _has_user_data(f: dict) -> bool:
    return bool(f.get("source") == "manual" or f.get("measurement") or f.get("review") or f.get("workorder_id")
                or f.get("status", "open") != "open" or _user_fields(f) or f.get("note") or "metrics_prev" in f)


def _move(f: dict, k: float, pivot: np.ndarray, proj: dict) -> None:
    p = np.array([f["x"], f["y"], f.get("z", 0.0)], dtype=np.float64)
    q = pivot + k * (p - pivot)
    f["x"], f["y"] = round(float(q[0]), 3), round(float(q[1]), 3)
    if "z" in f:
        f["z"] = round(float(q[2]), 3)
    if f.get("bbox"):
        b = np.asarray(f["bbox"], dtype=np.float64)
        f["bbox"] = [round(float(v), 3) for v in np.r_[pivot + k * (b[:3] - pivot), pivot + k * (b[3:] - pivot)]]
    lat, lon = enu_to_latlon(np.array([f["x"]]), np.array([f["y"]]), proj["origin_lat"], proj["origin_lon"])
    f["lat"], f["lon"] = float(lat[0]), float(lon[0])


def _redo_rescaled_depth(f: dict) -> None:
    """A measurement whose depth was the 3D depth × √(area ratio): recompute it from the new 3D numbers."""
    rec = f.get("measurement") or {}
    d = rec.get("depth") or {}
    if d.get("source") != "3d_rescaled":
        return
    m = f.get("metrics") or {}
    try:
        r = measure.rescale_depth({"area_m2": m["area_m2"], "ranges": rec["ranges"]}, f.get("metrics_3d") or {})
    except (measure.MeasureError, KeyError, TypeError, ZeroDivisionError):
        return   # keep the saved depth; the 3D no longer supports a rescale here
    m["depth_max_m"] = r["depth_m"]
    m["volume_m3"] = r["volume_m3"] if r.get("volume_m3") else round(m["area_m2"] * r["depth_m"], 5)
    rec["depth"] = {**d, **{k: r[k] for k in ("k", "depth_m", "depth_3d_m", "depth_key", "area_3d_m2", "depth_range")}}


def carry_over(old: dict, new: dict, k: float, pivot: np.ndarray, proj: dict, sid: str, event: str, uid: str | None) -> dict:
    """Give the new analysis the old one's ids and everything people added. Returns counts."""
    now = time.time()
    olds = [copy.deepcopy(f) for f in old.get("findings") or []]
    for f in olds:
        _move(f, k, pivot, proj)
    news = new["findings"]
    pairs = []
    for i, f in enumerate(olds):
        if f.get("source") == "manual":
            continue
        for j, g in enumerate(news):
            if f["type"] != g["type"] and not (FAMILY.get(f["type"]) and FAMILY.get(f["type"]) == FAMILY.get(g["type"])):
                continue
            dist = math.hypot(f["x"] - g["x"], f["y"] - g["y"])
            b = f.get("bbox") or [f["x"], f["y"], 0, f["x"], f["y"], 0]
            inside = b[0] <= g["x"] <= b[3] and b[1] <= g["y"] <= b[4]
            if dist <= MATCH_M or inside:
                pairs.append((dist, i, j))
    pairs.sort()
    used_o, used_n, match = set(), set(), {}
    for _, i, j in pairs:
        if i in used_o or j in used_n:
            continue
        used_o.add(i)
        used_n.add(j)
        match[j] = i
    prefix = "F" + sid[:3].upper() + "-"
    taken = {f["id"] for f in old.get("findings") or []}
    nums = [int(x[len(prefix):]) for x in taken if x.startswith(prefix) and x[len(prefix):].isdigit()]
    nxt = max(nums, default=0) + 1
    out = []
    kept = 0
    for j, g in enumerate(news):
        if j in match:
            f = olds[match[j]]
            merged = {**{kk: v for kk, v in f.items() if kk not in ANALYSIS_KEYS}, **g}
            merged["id"] = f["id"]
            merged["status"] = f.get("status", "open")
            merged["history"] = list(f.get("history") or [])
            for fld in _user_fields(f) & {"severity", "type"}:
                merged[fld] = f.get(fld)
            if f.get("measurement"):
                merged["metrics_3d"] = copy.deepcopy(g.get("metrics") or {})
                merged["metrics"] = copy.deepcopy(f.get("metrics") or {})
                if "metrics_prev" in f:
                    merged["metrics_prev"] = (copy.deepcopy(merged["metrics_3d"]) if not f.get("measurement_prev")
                                              else f["metrics_prev"])
                _redo_rescaled_depth(merged)
            else:
                merged.pop("metrics_3d", None)
                if "metrics_prev" in f:   # only after an undo of a measurement: the 3D numbers again
                    merged["metrics_prev"] = copy.deepcopy(g.get("metrics") or {})
            merged["history"].append({"t": now, "event": event, "by": uid})
            out.append(merged)
        else:
            g["id"] = f"{prefix}{nxt:04d}"
            nxt += 1
            g.setdefault("history", []).append({"t": now, "event": f"found after {event}", "by": uid})
            out.append(g)
    for i, f in enumerate(olds):
        if i in used_o or not _has_user_data(f):
            continue
        # people worked on it but the new analysis does not find it: keep it, scaled, and say so
        if f.get("source") != "manual":
            if f.get("measurement"):
                f["metrics_3d"] = scale_metrics(f.get("metrics_3d"), k)
                if "metrics_prev" in f and not f.get("measurement_prev"):
                    f["metrics_prev"] = scale_metrics(f["metrics_prev"], k)
            else:
                f["metrics"] = scale_metrics(f.get("metrics"), k)
            f["not_redetected"] = True
        f.setdefault("history", []).append({"t": now, "event": f"{event} (kept: not found again by the analysis)"
                                            if f.get("source") != "manual" else event, "by": uid})
        out.append(f)
        kept += 1
    new["findings"] = out
    # traffic data fetched for the old segments: give each new segment the nearest old one's
    old_segs = [s for s in old.get("segments") or [] if s.get("traffic") and s.get("line")]
    if old_segs:
        mids = [pivot[:2] + k * (np.asarray(s["line"], dtype=np.float64)[:, :2].mean(0) - pivot[:2]) for s in old_segs]
        for s in new["segments"]:
            c = np.asarray(s["line"], dtype=np.float64)[:, :2].mean(0)
            s["traffic"] = old_segs[int(np.argmin([np.linalg.norm(c - m) for m in mids]))]["traffic"]
    if old.get("traffic_notes"):
        new["traffic_notes"] = old["traffic_notes"]
    from .analysis.condition import score_segments

    score_segments(new["segments"], new["findings"])
    return {"matched": len(match), "new": len(news) - len(match), "kept": kept,
            "dropped": len(olds) - len(used_o) - kept}


def rescale_survey(pid: str, sid: str, k: float, *, pivot=None, scale: dict, notes: list[str], params_refs,
                   event: str, uid: str | None, expect_steps: int | None = None) -> dict:
    """Rescale the stored clip by k and re-run the analysis; replaces recon, analysis and the survey's scale.

    expect_steps: the number of scale steps the caller's k was measured on. k is relative to the clip as it
    was then, so if someone else applied or undid a scale meanwhile, k would be applied twice: refuse."""
    from .pipeline import analyse, survey_stats

    if not (scene_scale.K_RANGE[0] <= k <= scene_scale.K_RANGE[1]):
        raise HTTPException(400, f"The scale factor {k:.3g} is outside {scene_scale.K_RANGE[0]:g}–{scene_scale.K_RANGE[1]:g}: "
                                 "check the references and the taps.")
    with store.lock(pid):
        proj = store.get_project(pid)
        sv, rec = _load(pid, sid)
        if expect_steps is not None and len((sv.get("scale") or {}).get("history") or []) != expect_steps:
            raise HTTPException(409, "Someone changed this clip's scale meanwhile. Close the sheet, open it again and "
                                     "check the references.")
        piv = scene_scale.rescale(rec, k, pivot)
        if scale.get("history") and len(scale["history"]) > (expect_steps or 0) and scale["history"][-1].get("pivot") is None:
            scale["history"][-1]["pivot"] = piv.tolist()   # undo scales back about the same point
        params = dict(sv.get("params") or {})
        old = store.get_analysis(pid, sid)
        new = analyse(rec, params, proj, sid)
        counts = carry_over(old, new, k, piv, proj, sid, event, uid)
        if params_refs:
            params["scene_refs"] = params_refs
        else:
            params.pop("scene_refs", None)
        rec.meta["scale_info"] = {kk: scale.get(kk) for kk in ("method", "pct", "label")}
        rec.save(store.recon_path(pid, sid))
        store.save_analysis(pid, sid, new)
        stats = {**(sv.get("stats") or {}), **survey_stats(rec, new)}
        store.update_survey(pid, sid, scale=scale, notes=notes, stats=stats, params=params)
        return {"pivot": piv.tolist(), "counts": counts, "stats": stats}


# --- routes ----------------------------------------------------------------------------------------------------
@router.get("/scene_scale/refs")
def refs(request: Request):
    auth.require(request)
    cat = scene_scale.load_catalog()
    return {**cat, "tol_px": scene_scale.TOL_PX}


@router.get("/projects/{pid}/surveys/{sid}/scale")
def get_scale(pid: str, sid: str, request: Request):
    auth.require(request)
    sv = store.get_survey(pid, sid)
    out = scale_summary(sv)
    n = _frame_count(pid, sid)
    out["frames"] = n
    out["available"], out["why"] = False, ""
    if sv.get("status") != "done":
        out["why"] = "The 3D clip is not ready yet."
    elif n == 0:
        out["why"] = "Only 3D clips from a drive video have frames to tap on."
    else:
        try:
            rec = Reconstruction.load(store.recon_path(pid, sid))
            cameras(pid, sid, rec)
            out["available"] = True
            traj = rec.trajectory()
            out["clip_length_m"] = round(float(np.linalg.norm(np.diff(traj, axis=0), axis=1).sum()), 2) if traj is not None else None
        except (scene_scale.ScaleError, OSError, KeyError) as e:
            out["why"] = str(e)
    return out


def _estimate(pid: str, sid: str, body: ScaleIn, draws: int, strict: bool) -> tuple[dict, Reconstruction, list[dict], dict]:
    specs = _resolve(body)
    sv, rec = _load(pid, sid)
    try:
        cams = cameras(pid, sid, rec)
        est = scene_scale.estimate(rec.points, cams, specs, tol_px=body.tol_px, draws=draws, strict=strict)
    except scene_scale.ScaleError as e:
        raise HTTPException(400, str(e)) from None
    return est, rec, specs, sv


@router.post("/projects/{pid}/surveys/{sid}/scale/preview")
def preview(pid: str, sid: str, body: ScaleIn, request: Request):
    auth.require(request)
    est, rec, specs, sv = _estimate(pid, sid, body, PREVIEW_DRAWS, strict=False)
    c = est["combined"]
    traj = rec.trajectory()
    length = float(np.linalg.norm(np.diff(traj, axis=0), axis=1).sum()) if traj is not None and len(traj) > 1 else None
    return {"refs": [_ref_out(s, r) for s, r in zip(specs, est["refs"])],
            "combined": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in c.items() if k != "range"}
            | {"range": _round(c["range"], 5)},
            "current": scale_summary(sv),
            "clip_length_m": round(length, 2) if length else None,
            "clip_length_after_m": round(length * c["scale"], 2) if length else None}


@router.post("/projects/{pid}/surveys/{sid}/scale/apply")
def apply(pid: str, sid: str, body: ScaleIn, request: Request):
    me = require_staff(request)
    est, _, specs, sv = _estimate(pid, sid, body, APPLY_DRAWS, strict=True)
    c = est["combined"]
    k = float(c["scale"])
    prev = sv.get("scale") or {}
    prev_sum = scale_summary(sv)
    used = [r["index"] for r in est["refs"] if not r.get("outlier")]
    text = scene_scale.describe(specs, used)
    stored_refs = [_ref_out(s, r) for s, r in zip(specs, est["refs"])]
    # the references measured on the rescaled clip read k times longer: store them as they will be after
    for r in stored_refs:
        if "d3" in r:
            r["d3"] = round(r["d3"] * k, 5)
            r["points_3d"] = None
    hist = list(prev.get("history") or [])
    hist.append({"at": time.time(), "by": me["uid"], "k": k, "pivot": None,
                 "prev": {kk: prev.get(kk) for kk in ("method", "label", "pct", "refs", "total", "factor", "camera_height_m",
                                                        "range", "parts", "provisional", "warnings")}
                 | {"method": prev_sum["method"]},
                 "notes": list(sv.get("notes") or []), "scene_refs": (sv.get("params") or {}).get("scene_refs")})
    note = (f"scale from {text}: factor {k:.2f} ±{c['pct']:.0f}% on top of the {prev_sum['text']} "
            f"(p10–p90 {c['range'][0]:.2f}–{c['range'][1]:.2f})")
    scale = {"method": "scene", "label": text, "parts": scene_scale.describe_parts(specs, used), "pct": c["pct"],
             "factor": k, "range": _round(c["range"], 5), "total": round(float(prev.get("total", 1.0)) * k, 6),
             "refs": stored_refs, "history": hist, "warnings": c["warnings"],
             "provisional": any(specs[i].get("provisional") for i in used)}
    params_refs = [{kk: s[kk] for kk in ("ref_id", "label", "known_m", "rel_error", "points", "vertical")} for s in specs]
    notes = [n for n in (sv.get("notes") or [])] + [note]
    res = rescale_survey(pid, sid, k, scale=scale, notes=notes, params_refs=params_refs,
                         event=f"rescaled ×{k:.3f} from {text}", uid=me["uid"], expect_steps=len(hist) - 1)
    return {"scale": scale_summary(store.get_survey(pid, sid)), "factor": k, "combined": c, "note": note, **res}


@router.post("/projects/{pid}/surveys/{sid}/scale/undo")
def undo(pid: str, sid: str, request: Request):
    me = require_staff(request)
    sv = store.get_survey(pid, sid)
    sc = sv.get("scale") or {}
    hist = list(sc.get("history") or [])
    if not hist:
        raise HTTPException(409, "nothing to undo")
    last = hist.pop()
    prev = {kk: v for kk, v in (last.get("prev") or {}).items() if v is not None}
    scale = {**prev, "history": hist}
    k = 1.0 / float(last["k"])
    res = rescale_survey(pid, sid, k, pivot=last.get("pivot"), scale=scale, notes=list(last.get("notes") or []),
                         params_refs=last.get("scene_refs"), event=f"scale undone (×{k:.3f})", uid=me["uid"],
                         expect_steps=len(hist) + 1)
    return {"scale": scale_summary(store.get_survey(pid, sid)), "factor": k, **res}

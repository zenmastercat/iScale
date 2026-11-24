"""3D check for one finding: let people see the point cloud behind a pothole and judge it.

The two models work together. The pothole detector draws boxes on the video frames; LingBot-Map
rebuilds the clip in 3D, and every 3D point that came from a pixel inside a box is labelled
"pothole" (adapters/lingbot_map.py). The analysis then measures dips in the road surface and joins
a dip with the detector's points at the same spot (analysis.merge_detector):
  detector+geometry  both agree: detector points and a measured dip
  geometry           a dip the detector did not mark
  detector           detector points but no measurable dip
This module draws the evidence for one finding (photo-coloured top view with the detector's
points, height against a road plane fitted around it, and a cross-section) and records an
engineer's verdict (correct / wrong / unsure) on the finding.

The picture is rendered with OpenCV on the server, so it works on phones without WebGL. Images
are cached in the survey's work/checks folder and rebuilt when the analysis changes.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import auth, store
from .pointcloud import Reconstruction

router = APIRouter(prefix="/api/projects/{pid}/surveys/{sid}/findings/{fid}")

VERDICTS = ("correct", "wrong", "unsure")
SEV_BGR = {"high": (24, 35, 180), "medium": (13, 115, 217), "low": (0, 161, 201)}
MAGENTA = (179, 46, 255)  # BGR of #ff2eb3, the same colour as the 3D view's Detector mode
RENDER_VERSION = 3         # bump when the drawing changes: old cached images are not reused
PANEL = 480               # pixels per panel side (shown at ~half size: sharp on phone screens)
FS = PANEL / 300          # text and line scale
_cache: dict[str, tuple[float, Reconstruction]] = {}


def _finding(pid: str, sid: str, fid: str) -> tuple[dict, dict]:
    an = store.get_analysis(pid, sid)
    f = next((x for x in an["findings"] if x["id"] == fid), None)
    if f is None:
        raise HTTPException(404, "finding not found")
    return an, f


def _recon(pid: str, sid: str) -> Reconstruction:
    path = store.recon_path(pid, sid)
    if not path.is_file():
        raise HTTPException(404, "this survey has no point cloud")
    key, mtime = str(path), path.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    rec = Reconstruction.load(path)
    _cache.clear()  # keep one cloud in memory; clips are millions of points
    _cache[key] = (mtime, rec)
    return rec


def m3(f: dict) -> dict:
    """The finding's 3D metrics: after a reference-object measurement (civil/measure_api.py) they are kept
    under metrics_3d, and this check stays about the 3D."""
    return (f.get("metrics_3d") if "metrics_3d" in f else f.get("metrics")) or {}


def pothole_mask(rec: Reconstruction) -> np.ndarray | None:
    """Points that came from inside the detector's boxes (labels are class ids; -1 = none)."""
    if rec.labels is None:
        return None
    ids = [k for k, v in (rec.label_names or {}).items() if v == "pothole"]
    return np.isin(rec.labels, ids) if ids else None


def _evidence(rec: Reconstruction, f: dict) -> dict:
    """Crop the cloud around the finding, fit the road plane around it, and compute the numbers."""
    m = m3(f)
    diam = float(m.get("diameter_m") or 0) or max(0.3, float(np.hypot(f["bbox"][3] - f["bbox"][0], f["bbox"][4] - f["bbox"][1])))
    half = max(1.0, diam * 1.2 + 0.5)                    # half the side of the square we look at
    cx, cy = float(f["x"]), float(f["y"])
    sel = (np.abs(rec.points[:, 0] - cx) < half) & (np.abs(rec.points[:, 1] - cy) < half)
    idx = np.flatnonzero(sel)
    if len(idx) < 50:
        raise HTTPException(404, "too few 3D points around this finding to show a check")
    p = rec.points[idx].astype(np.float64)
    col = rec.colors[idx] if rec.colors is not None else np.full((len(idx), 3), 150, np.uint8)
    temps = rec.temperatures_c[idx].astype(np.float32) if rec.temperatures_c is not None else None
    det = pothole_mask(rec)
    det = det[idx] if det is not None else np.zeros(len(idx), bool)
    # keep the road surface only: drop cars, poles and stray points far from the finding's height
    road = np.abs(p[:, 2] - float(f.get("z", np.median(p[:, 2])))) < max(0.4, 3 * float(m.get("depth_max_m") or 0.1))
    if road.sum() >= 50:
        p, col, det = p[road], col[road], det[road]
        if temps is not None:
            temps = temps[road]
    r = np.hypot(p[:, 0] - cx, p[:, 1] - cy)
    r_in = max(diam / 2 + 0.15, 0.3)
    ring = (r > r_in) & (r < half)
    if ring.sum() < 30:
        ring = r > r_in * 0.7
    A = np.c_[p[ring, 0] - cx, p[ring, 1] - cy, np.ones(ring.sum())]
    zr = p[ring, 2]
    coef = np.linalg.lstsq(A, zr, rcond=None)[0]
    for _ in range(2):
        res = A @ coef - zr
        keep = np.abs(res) < max(2.5 * np.std(res), 0.01)
        if keep.sum() < 20:
            break
        coef = np.linalg.lstsq(A[keep], zr[keep], rcond=None)[0]
    rel = p[:, 2] - (coef[0] * (p[:, 0] - cx) + coef[1] * (p[:, 1] - cy) + coef[2])
    inside = r <= max(diam / 2, 0.1)
    # LingBot-Map often stacks the same road in thin layers a few cm apart; judge heights by the
    # average per 4 cm cell (as the analysis grid does), not by single points
    cell = 0.04
    key = np.floor((p[:, 0] - cx) / cell).astype(np.int64) * 100003 + np.floor((p[:, 1] - cy) / cell).astype(np.int64)
    uk, inv = np.unique(key, return_inverse=True)
    cmean = np.bincount(inv, weights=rel) / np.bincount(inv)
    c_in = np.bincount(inv, weights=inside.astype(float)) / np.bincount(inv) > 0.5
    c_ring = np.bincount(inv, weights=ring.astype(float)) / np.bincount(inv) > 0.5
    ring_noise = float(np.std(cmean[c_ring])) if c_ring.sum() > 5 else float(np.std(rel[ring])) if ring.any() else 0.0
    dip = float(-np.percentile(cmean[c_in], 5)) if c_in.sum() >= 5 else None  # 5th percentile: ignore stray cells
    thermal_stats = None
    if temps is not None and np.isfinite(temps).sum() < 20:
        temps = None  # thermal camera never saw this spot (NaN = unobserved)
    if temps is not None:
        fin = np.isfinite(temps)
        amb = float(np.median(temps[ring & fin])) if (ring & fin).any() else float(np.median(temps[fin]))
        in_t = temps[inside & fin] if (inside & fin).any() else temps[fin]
        mean_in = float(np.mean(in_t))
        thermal_stats = {
            "min_c": round(float(np.min(temps[fin])), 2),
            "max_c": round(float(np.max(temps[fin])), 2),
            "mean_c": round(mean_in, 2),
            "road_ambient_c": round(amb, 2),
            "delta_c": round(mean_in - amb, 2),
        }
    return {"p": p, "col": col, "det": det, "rel": rel, "temps": temps, "thermal_stats": thermal_stats,
            "cx": cx, "cy": cy, "half": half, "diam": diam,
            "dip_m": dip, "ring_noise_m": ring_noise, "det_points": int(det.sum()),
            "det_inside": int((det & inside).sum()), "points": int(len(p))}


def verdict(f: dict, ev: dict) -> dict:
    src = f.get("source") or ""
    depth = m3(f).get("depth_max_m")
    if src == "detector+geometry":
        code, text = "both", (f"Both agree: the detector marked this spot ({ev['det_points']:,} 3D points from its boxes) "
                              f"and the 3D surface dips {depth * 100:.1f} cm here." if depth else
                              f"Both agree: the detector marked this spot ({ev['det_points']:,} 3D points from its boxes) "
                              "and the 3D surface dips here, but the depth could not be measured.")
    elif src == "detector":
        code, text = "detector_only", (f"Detector only: {ev['det_points']:,} 3D points came from its boxes, but no dip could be "
                                       "measured in 3D. Check the photo or measure on site.")
    elif src in ("geometry", ""):
        code, text = "geometry_only", ("3D only: the surface dips here, but the detector did not mark it. It may be a "
                                       "shadow, a patch or a pothole the detector missed; check the photo.")
    else:
        code, text = "manual", "Tagged by hand in the 3D view."
    warn = []
    if code == "both" and ev["det_inside"] == 0:
        warn.append("None of the detector's points fall inside the measured outline: the two were joined because the dip "
                    "lies within 0.5 m of the detector's area. Check the photo before trusting it.")
    if ev["dip_m"] is not None and depth and abs(ev["dip_m"] - depth) > max(0.03, 0.5 * depth):
        warn.append(f"Re-measured here, the dip is {ev['dip_m'] * 100:.1f} cm against the survey's {depth * 100:.1f} cm.")
    if ev["ring_noise_m"] > 0.03:
        warn.append(f"The road around it is rough or noisy in 3D (±{ev['ring_noise_m'] * 100:.1f} cm), so small depths are uncertain.")
    if m3(f).get("not_measurable"):
        warn.append("Depth was too large to trust (water or stray points); the typical depth is used for cost.")
    return {"code": code, "text": text, "warnings": warn}


# --- drawing ---------------------------------------------------------------------------------
# red (below the road) - yellow - blue (above), the same scale as the document's height maps (RdYlBu)
_ANCH = np.array([[165, 0, 38], [215, 48, 39], [244, 109, 67], [253, 174, 97], [254, 224, 144], [255, 255, 191],
                  [224, 243, 248], [171, 217, 233], [116, 173, 209], [69, 117, 180], [49, 54, 149]], float)
LUT = np.stack([np.interp(np.linspace(0, 10, 256), np.arange(11), _ANCH[:, k]) for k in range(3)], 1)[:, ::-1].astype(np.uint8)


def _coarse(ev: dict, values: np.ndarray, cell: float) -> tuple[np.ndarray, np.ndarray]:
    """Mean of `values` per `cell`-metre square over the view, scaled up to PANEL pixels."""
    n = max(8, int(round(2 * ev["half"] / cell)))
    u = ((ev["p"][:, 0] - ev["cx"] + ev["half"]) / (2 * ev["half"]) * n).astype(int).clip(0, n - 1)
    v = ((ev["half"] - (ev["p"][:, 1] - ev["cy"])) / (2 * ev["half"]) * n).astype(int).clip(0, n - 1)
    flat = v * n + u
    cnt = np.bincount(flat, minlength=n * n)
    vals = values if values.ndim == 2 else values[:, None]
    out = np.stack([np.bincount(flat, weights=vals[:, k], minlength=n * n) for k in range(vals.shape[1])], 1) / np.maximum(cnt, 1)[:, None]
    out = out.reshape(n, n, -1)
    m = (cnt > 0).reshape(n, n).astype(np.uint8)
    # fill one-cell holes from the neighbours, then scale up
    filled = cv2.dilate(out.astype(np.float32), np.ones((3, 3), np.uint8)) if out.shape[2] > 1 else cv2.dilate(out[:, :, 0].astype(np.float32), np.ones((3, 3), np.uint8))[:, :, None]
    grown = cv2.dilate(m, np.ones((3, 3), np.uint8))
    out = np.where(m[:, :, None].astype(bool), out, filled)
    big = cv2.resize(out.astype(np.float32), (PANEL, PANEL), interpolation=cv2.INTER_NEAREST)
    if big.ndim == 2:
        big = big[:, :, None]
    return big, cv2.resize(grown, (PANEL, PANEL), interpolation=cv2.INTER_NEAREST).astype(bool)


def _outline(img: np.ndarray, ev: dict, f: dict) -> None:
    s = PANEL / (2 * ev["half"])
    c = (PANEL // 2, PANEL // 2)
    cv2.circle(img, c, max(3, int(ev["diam"] / 2 * s)), SEV_BGR.get(f.get("severity"), (40, 40, 40)), 3, cv2.LINE_AA)


def _scalebar(img: np.ndarray, ev: dict) -> None:
    s = PANEL / (2 * ev["half"])
    L = 0.5 if ev["half"] < 1.6 else 1.0
    x0, y = 12, PANEL - 14
    cv2.line(img, (x0, y), (x0 + int(L * s), y), (30, 30, 30), 3)
    cv2.putText(img, f"{L:g} m", (x0, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45 * FS, (30, 30, 30), 1, cv2.LINE_AA)


PANELS = ("top", "height", "section")
ALL_PANELS = ("top", "height", "section", "thermal")
_THERM_ANCH = np.array(
    [[20, 11, 52], [84, 15, 109], [140, 41, 129], [196, 60, 117], [237, 105, 37], [251, 180, 26], [252, 255, 164]],
    float,
)
THERMAL_LUT = np.stack(
    [np.interp(np.linspace(0, 6, 256), np.arange(7), _THERM_ANCH[:, k]) for k in range(3)], 1
)[:, ::-1].astype(np.uint8)


def render(f: dict, ev: dict, panel: str = "top") -> bytes:
    if panel == "thermal":
        temps = ev.get("temps")
        if temps is None or len(temps) == 0:
            raise HTTPException(404, "this survey has no radiometric thermal data")
        fin = np.isfinite(temps)
        th, tm = _coarse({**ev, "p": ev["p"][fin]}, temps[fin].astype(float), 0.04)
        tmin = float(np.percentile(temps[fin], 2))
        tmax = max(tmin + 0.5, float(np.percentile(temps[fin], 98)))
        tnorm = np.clip((th[:, :, 0] - tmin) / (tmax - tmin), 0, 1)
        timg = THERMAL_LUT[(tnorm * 255).astype(np.uint8)]
        timg[~tm] = 245
        _outline(timg, ev, f)
        _scalebar(timg, ev)
        tkey = np.full((34, PANEL, 3), 255, np.uint8)
        tkey[6:18, 84:PANEL - 96] = cv2.resize(THERMAL_LUT[None, :, :], (PANEL - 180, 12), interpolation=cv2.INTER_LINEAR)
        cv2.putText(tkey, f"{tmin:.1f} C", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.33 * FS, (80, 80, 80), 1, cv2.LINE_AA)
        cv2.putText(tkey, f"{tmax:.1f} C", (PANEL - 88, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.33 * FS, (80, 80, 80), 1, cv2.LINE_AA)
        ok, png = cv2.imencode(".png", np.vstack([timg, tkey]))
        return png.tobytes()
    depth = m3(f).get("depth_max_m") or 0.0
    lim = max(0.05, 1.4 * max(depth, ev["dip_m"] or 0))
    # 1. photo colour from above, the detector's points on top
    rgb, filled = _coarse(ev, ev["col"][:, ::-1].astype(float), 0.015)       # colours are RGB; OpenCV draws BGR
    a = np.where(filled[:, :, None], rgb, 245).astype(np.uint8)
    if ev["det"].any():
        d = ev["det"]
        s = PANEL / (2 * ev["half"])
        u = ((ev["p"][d, 0] - ev["cx"] + ev["half"]) * s).astype(int).clip(0, PANEL - 1)
        v = ((ev["half"] - (ev["p"][d, 1] - ev["cy"])) * s).astype(int).clip(0, PANEL - 1)
        over = a.copy()
        over[v, u] = MAGENTA
        a = cv2.addWeighted(over, 0.55, a, 0.45, 0)
    _outline(a, ev, f)
    _scalebar(a, ev)
    # 2. height against the fitted road plane (lowest point per cell), red = below the road
    h, hm = _coarse(ev, ev["rel"], 0.04)
    t = np.clip((h[:, :, 0] + lim) / (2 * lim), 0, 1)              # 0 = lim below the road, 1 = lim above
    b = LUT[(t * 255).astype(np.uint8)]
    b[~hm] = 245
    _outline(b, ev, f)
    cv2.line(b, (0, PANEL // 2), (PANEL - 1, PANEL // 2), (255, 255, 255), 1, cv2.LINE_AA)
    cv2.line(b, (0, PANEL // 2), (PANEL - 1, PANEL // 2), (40, 40, 40), 1, cv2.LINE_4)
    # 3. cross-section along the white line in panel 2 (west-east through the centre, 10 cm strip)
    c = np.full((PANEL, int(PANEL * 1.5), 3), 255, np.uint8)
    W = c.shape[1]
    strip = np.abs(ev["p"][:, 1] - ev["cy"]) < 0.05
    xs = ev["p"][strip, 0] - ev["cx"]
    zs = ev["rel"][strip]
    zlim = max(lim, 0.06)
    X = lambda x: int(20 + (x + ev["half"]) / (2 * ev["half"]) * (W - 40))  # noqa: E731
    Z = lambda z: int(PANEL / 2 - z / zlim * (PANEL / 2 - 30))              # noqa: E731
    cv2.line(c, (20, Z(0)), (W - 20, Z(0)), (150, 150, 150), 1, cv2.LINE_AA)
    cv2.putText(c, "road surface", (W - int(130 * FS), Z(0) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4 * FS, (110, 110, 110), 1, cv2.LINE_AA)
    dstrip = ev["det"][strip]
    for x, z, isdet in zip(xs, zs, dstrip):
        cv2.circle(c, (X(x), Z(max(-zlim, min(zlim, z)))), 2, MAGENTA if isdet else (175, 175, 175), -1)
    # median profile in 3 cm steps: what the surface does once the thin layers are averaged
    if len(xs) > 10:
        bins = np.floor(xs / 0.05).astype(int)
        prof = [(b * 0.05 + 0.025, float(np.median(zs[bins == b]))) for b in np.unique(bins) if (bins == b).sum() >= 5]
        pts = np.array([(X(x), Z(max(-zlim, min(zlim, z)))) for x, z in prof], np.int32)
        if len(pts) > 1:
            cv2.polylines(c, [pts], False, (30, 30, 30), 3, cv2.LINE_AA)
    r = ev["diam"] / 2
    cv2.line(c, (X(-r), PANEL - 20), (X(r), PANEL - 20), SEV_BGR.get(f.get("severity"), (40, 40, 40)), 3)
    if depth:
        cv2.line(c, (X(-r), Z(-depth)), (X(r), Z(-depth)), SEV_BGR.get(f.get("severity"), (40, 40, 40)), 1, cv2.LINE_AA)
        cv2.putText(c, f"measured depth {depth * 100:.1f} cm", (X(-r), Z(-depth) + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42 * FS,
                    SEV_BGR.get(f.get("severity"), (40, 40, 40)), 1, cv2.LINE_AA)
    cv2.putText(c, f"+{zlim * 100:.0f} cm", (22, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * FS, (110, 110, 110), 1, cv2.LINE_AA)
    cv2.putText(c, f"-{zlim * 100:.0f} cm", (22, PANEL - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * FS, (110, 110, 110), 1, cv2.LINE_AA)
    # colour key under the height map
    key = np.full((34, PANEL, 3), 255, np.uint8)
    key[6:18, 84:PANEL - 96] = cv2.resize(LUT[None, :, :], (PANEL - 180, 12), interpolation=cv2.INTER_LINEAR)
    cv2.putText(key, f"-{lim * 100:.0f} cm", (0, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.33 * FS, (80, 80, 80), 1, cv2.LINE_AA)
    cv2.putText(key, f"+{lim * 100:.0f} cm", (PANEL - 88, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.33 * FS, (80, 80, 80), 1, cv2.LINE_AA)
    out = {"top": a, "height": np.vstack([b, key]), "section": c}[panel]
    ok, png = cv2.imencode(".png", out)
    return png.tobytes()


# --- routes ----------------------------------------------------------------------------------------
@router.get("/check")
def get_check(pid: str, sid: str, fid: str):
    _, f = _finding(pid, sid, fid)
    ev = _evidence(_recon(pid, sid), f)
    m = m3(f)
    rev = f.get("review")
    if rev:
        who = auth.person(rev.get("by")) or {}
        rev = {**{k: rev[k] for k in ("verdict", "note", "at") if k in rev}, "by": who.get("username"), "by_name": who.get("display_name")}
    has_thermal = ev.get("temps") is not None
    panel_keys = ALL_PANELS if has_thermal else PANELS
    return {"id": f["id"], "type": f["type"], "severity": f.get("severity"), "source": f.get("source"),
            "verdict": verdict(f, ev), "detector_points": ev["det_points"], "detector_points_inside": ev["det_inside"],
            "points": ev["points"], "measured_depth_m": m.get("depth_max_m"), "area_m2": m.get("area_m2"),
            "diameter_m": round(ev["diam"], 2), "lowest_below_plane_m": round(ev["dip_m"], 3) if ev["dip_m"] is not None else None,
            "road_noise_m": round(ev["ring_noise_m"], 3), "view_m": round(2 * ev["half"], 1), "review": rev,
            "has_thermal": has_thermal, "thermal_stats": ev.get("thermal_stats"),
            "images": {k: f"/api/projects/{pid}/surveys/{sid}/findings/{fid}/check.png?panel={k}&v={int(store.recon_path(pid, sid).stat().st_mtime)}-{RENDER_VERSION}"
                       for k in panel_keys}}


@router.get("/check.png")
def get_check_png(pid: str, sid: str, fid: str, panel: str = "top"):
    if panel not in ALL_PANELS:
        raise HTTPException(400, "panel must be top, height, section or thermal")
    an_path = store.survey_dir(pid, sid) / "analysis.json"
    _finding(pid, sid, fid)  # 404 for an unknown finding before touching the cache
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in fid)[:64]
    cache = store.survey_dir(pid, sid) / "work" / "checks" / f"{safe}-{panel}-v{RENDER_VERSION}.png"
    if cache.is_file() and cache.stat().st_mtime >= max(an_path.stat().st_mtime, store.recon_path(pid, sid).stat().st_mtime):
        png = cache.read_bytes()
    else:
        _, f = _finding(pid, sid, fid)
        png = render(f, _evidence(_recon(pid, sid), f), panel)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(png)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


class ReviewIn(BaseModel):
    verdict: str
    note: str = Field(default="", max_length=500)


@router.post("/review")
def post_review(pid: str, sid: str, fid: str, body: ReviewIn, request: Request):
    """An engineer's judgement of the 3D check: correct, wrong (a false pothole) or unsure."""
    me = auth.require(request)
    if body.verdict not in VERDICTS:
        raise HTTPException(400, "verdict must be correct, wrong or unsure")
    with store.lock(pid):
        an, f = _finding(pid, sid, fid)
        f["review"] = {"verdict": body.verdict, "note": body.note.strip(), "by": me["uid"], "at": time.time()}
        f.setdefault("history", []).append({"t": time.time(), "event": f"3D check: {body.verdict}", "by": me["uid"]})
        store.save_analysis(pid, sid, an)
    return get_check(pid, sid, fid)


"""Run the full non-learned analysis on an aligned reconstruction."""

from __future__ import annotations

import time

import numpy as np

from ..config import analysis_params
from ..pointcloud import Reconstruction
from .condition import score_segments
from .detect import SegmentSurface, decoder_labels, detect_objects, detect_surface
from .segments import make_segments, resample_path, station_offset

PATH_STEP = 0.5


def _ground_function(xyz: np.ndarray, cell: float = 0.5):
    """Bare-earth height lookup from per-cell minima, min-filtered over 1.5 m."""
    x0, y0 = xyz[:, 0].min(), xyz[:, 1].min()
    iu = ((xyz[:, 0] - x0) / cell).astype(np.int64)
    iv = ((xyz[:, 1] - y0) / cell).astype(np.int64)
    nu, nv = iu.max() + 1, iv.max() + 1
    g = np.full(nu * nv, np.inf)
    np.minimum.at(g, iu * nv + iv, xyz[:, 2].astype(np.float64))
    g = g.reshape(nu, nv)
    pad = np.pad(g, 1, constant_values=np.inf)
    win = np.lib.stride_tricks.sliding_window_view(pad, (3, 3))
    gf = win.min(axis=(2, 3))
    fill = float(np.median(xyz[:, 2]))
    gf[~np.isfinite(gf)] = fill

    def f(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        a = np.clip(((x - x0) / cell).astype(np.int64), 0, nu - 1)
        b = np.clip(((y - y0) / cell).astype(np.int64), 0, nv - 1)
        return gf[a, b]

    return f


DEPRESSION = {"pothole", "depression", "manhole_sunken"}
SURFACE_FAMILY = {"pothole": "dep", "depression": "dep", "manhole_sunken": "dep", "heave": "heave",
                  "surface_roughness": "rough", "sidewalk_trip_hazard": "trip"}
SEV_ORDER = {"low": 0, "medium": 1, "high": 2}


def merge_split(findings: list[dict], gap: float = 0.3) -> list[dict]:
    """Join pieces of one defect: a defect that straddles a segment boundary is found once
    per segment, and a pothole seen from an approaching camera has an occlusion gap behind
    its near lip. Pieces of the same family whose outlines are within `gap` metres merge."""
    out: list[dict] = []
    for f in findings:
        fam = SURFACE_FAMILY.get(f["type"])
        tgt = None
        if fam:
            b = f["bbox"]
            for g in out:
                c = g["bbox"]
                if SURFACE_FAMILY.get(g["type"]) == fam and b[0] <= c[3] + gap and c[0] <= b[3] + gap \
                        and b[1] <= c[4] + gap and c[1] <= b[4] + gap:
                    tgt = g
                    break
        if tgt is None:
            out.append(f)
            continue
        a1, a2 = tgt["metrics"].get("area_m2", 0.1), f["metrics"].get("area_m2", 0.1)
        w = a1 / max(a1 + a2, 1e-9)
        tgt["x"], tgt["y"] = tgt["x"] * w + f["x"] * (1 - w), tgt["y"] * w + f["y"] * (1 - w)
        tgt["bbox"] = [min(tgt["bbox"][i], f["bbox"][i]) for i in range(3)] + [max(tgt["bbox"][i], f["bbox"][i]) for i in range(3, 6)]
        m, n = tgt["metrics"], f["metrics"]
        for k in ("area_m2", "volume_m3"):
            if k in m or k in n:
                m[k] = round(m.get(k, 0) + n.get(k, 0), 4)
        for k in ("depth_max_m", "height_max_m", "step_m", "texture_std_mm"):
            if k in m or k in n:
                m[k] = max(m.get(k, 0), n.get(k, 0))
        if "diameter_m" in m:
            m["diameter_m"] = round(2 * (m["area_m2"] / 3.14159) ** 0.5, 2)
        if SEV_ORDER.get(f.get("severity"), 0) > SEV_ORDER.get(tgt.get("severity"), 0):
            tgt["severity"] = f["severity"]
        if tgt["type"] != f["type"] and "pothole" in (tgt["type"], f["type"]):
            tgt["type"] = "pothole"
        if f.get("segment_id") and f["segment_id"] != tgt.get("segment_id"):
            tgt["segments"] = sorted({tgt.get("segment_id"), f["segment_id"], *tgt.get("segments", [])})
        if "depth_max_m" in m and "area_m2" in m:
            tgt["evidence"] = (f"depression {m['depth_max_m'] * 100:.1f} cm deep, {m.get('diameter_m', 0):.2f} m across, "
                               f"{m.get('volume_m3', 0) * 1000:.1f} L missing material (joined from pieces)")
        else:
            tgt["evidence"] += " (joined from pieces)"
    return out


def merge_detector(dec: list[dict], geometric: list[dict]) -> list[dict]:
    """A detector box projected into 3D and a measured depression at the same spot are
    one pothole: keep the measured one (it has depth, area, volume) and mark it as
    confirmed by the detector. Detector-only hits are kept, flagged as unmeasured."""
    out = []
    for f in dec:
        if f["type"] != "pothole":
            out.append(f)
            continue
        b = f["bbox"]
        near = [g for g in geometric if g["type"] in DEPRESSION
                and b[0] - 0.5 <= g["x"] <= b[3] + 0.5 and b[1] - 0.5 <= g["y"] <= b[4] + 0.5]
        if near:
            for g in near:
                g["type"] = "pothole"
                g["source"] = "detector+geometry"
                g["metrics"]["detector_points"] = f["metrics"].get("points")
                g["evidence"] += "; confirmed by the video pothole detector"
            continue
        f["evidence"] = (f"detected in the video ({f['metrics'].get('points')} 3D points inside the detector box); "
                         "no depression measurable in 3D here: check the clip or tag it manually")
        f["severity"] = "low"
        f["source"] = "detector"
        out.append(f)
    return out


def analyze(rec: Reconstruction, params: dict | None = None) -> dict:
    p = {**analysis_params(), **(params or {})}
    t0 = time.time()
    traj = rec.trajectory()
    if traj is None or len(traj) < 2:
        raise ValueError("analysis needs camera poses (the vehicle path) to define road segments")
    path = resample_path(traj, PATH_STEP)
    segs = make_segments(path, PATH_STEP, float(p["segment_length_m"]))
    xyz = rec.points
    _, station, offset = station_offset(xyz[:, :2].astype(np.float64), path, PATH_STEP)

    findings: list[dict] = []
    low = xyz[:, 2] < 1.0  # surface analysis uses near-ground points only
    for seg in segs:
        m = low & (station >= seg["s0"]) & (station < seg["s1"]) & (np.abs(offset) < 14)
        if m.sum() < 500:
            seg["metrics"] = {"coverage": 0.0}
            continue
        surf = SegmentSurface(station[m], offset[m], xyz[m, 2].astype(np.float64), seg["s0"], seg["s1"], p)
        f, met = detect_surface(seg, surf, path, PATH_STEP, p)
        seg["metrics"] = met
        findings.extend(f)

    findings = merge_split(findings)
    ground = _ground_function(xyz)
    objs = detect_objects(xyz, rec.colors, ground, p)
    if rec.labels is not None and rec.label_names:
        dec = decoder_labels(xyz, rec.labels, rec.label_names)
        objs.extend(merge_detector(dec, findings))
    # attach objects to the nearest segment
    if objs:
        oxy = np.array([[o["x"], o["y"]] for o in objs])
        _, ost, _ = station_offset(oxy, path, PATH_STEP)
        for o, s in zip(objs, ost):
            k = int(np.clip(np.searchsorted([sg["s1"] for sg in segs], s), 0, len(segs) - 1))
            o["segment_id"] = segs[k]["id"]
    findings.extend(objs)
    score_segments(segs, findings)
    return {"segments": segs, "findings": findings, "path": path.tolist(),
            "params": p, "seconds": round(time.time() - t0, 2)}

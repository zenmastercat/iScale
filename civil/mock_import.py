"""Import a recorded camera pothole run (config/mock/sukhumvit-asok/) as a finished survey.

There is no point cloud: the analysis is written directly, in the shape analyze() +
pipeline._finalize_findings/_segments_to_geo produce, so every page treats it like any other survey.
The route is the baked OpenStreetMap centreline (route.json), so the import works offline.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np

from . import store
from .analysis.condition import score_segments
from .analysis.detect import _severity_pothole
from .analysis import PATH_STEP
from .analysis.segments import make_segments, resample_path, station_offset
from .config import analysis_params
from .pipeline import _finalize_findings, _segments_to_geo
from .pointcloud import latlon_to_enu

MOCK_DIR = Path(__file__).resolve().parent.parent / "config" / "mock" / "sukhumvit-asok"
PROJECT_NAME = "Sukhumvit Rd, Asok → Phrom Phong (sample run)"
SURVEY_NAME = "Pothole run (camera)"
ROAD_WIDTH_M = 10.5  # Sukhumvit Rd carriageway, for the condition index's share-of-surface maths


def _load() -> tuple[dict, list[list[float]]]:
    summary = json.loads((MOCK_DIR / "potholes_route_summary.json").read_text())
    route = json.loads((MOCK_DIR / "route.json").read_text())["coords"]  # [[lon, lat], ...]
    return summary, route


def _finding(p: dict, lat0: float, lon0: float) -> dict:
    d = p["dimensions_m"]
    depth = float(d["assumed_depth_m"])
    area = float(p["area_m2"])
    dia = 2 * math.sqrt(area / math.pi)
    x, y = latlon_to_enu(np.array([p["latitude"]]), np.array([p["longitude"]]), lat0, lon0)
    x, y = float(x[0]), float(y[0])
    hw, hl = d["width_m"] / 2, d["length_m"] / 2
    weak = not p["alerted"]
    evidence = (f"pothole about {d['width_m']:.1f} x {d['length_m']:.1f} m ({area:.1f} m2), found by the camera detector "
                f"(confidence {p['max_conf']:.2f}, seen in {p['hits']} frames); depth assumed {depth * 100:.0f} cm, not measured")
    if weak:
        evidence += "; weak track (few detections): an engineer should check it first"
    return {
        "type": "pothole", "severity": _severity_pothole(depth, dia), "source": "detector",
        "x": x, "y": y, "z": 0.0, "bbox": [x - hw, y - hl, 0.0, x + hw, y + hl, depth],
        "metrics": {"area_m2": round(area, 3), "depth_max_m": depth, "depth_median_m": depth, "depth_assumed": True,
                    "width_m": d["width_m"], "length_m": d["length_m"], "volume_m3": p["est_volume_m3"],
                    "diameter_m": round(dia, 2)},
        "evidence": evidence, "confidence": p["max_conf"], "needs_review": weak, "photo": True,
        "detector": {"track_id": p["id"], "frames": p["frames"], "hits": p["hits"], "max_conf": p["max_conf"],
                     "alerted": p["alerted"], "min_dist_y_m": p["min_dist_y_m"],
                     "est_cost_thb": p["est_cost_thb"], "est_material_kg": p["est_material_kg"],
                     "est_volume_m3": p["est_volume_m3"], "crop": p["image_path"]},
    }


def import_sukhumvit(company_id: str | None) -> dict:
    summary, route = _load()
    pots = summary["potholes"]
    lat0, lon0 = pots[0]["latitude"], pots[0]["longitude"]
    proj = store.create_project(PROJECT_NAME, lat0, lon0, company_id)
    pid = proj["id"]
    sv = store.create_survey(pid, SURVEY_NAME, "mock_camera", {})
    sid = sv["id"]

    lons = np.array([c[0] for c in route])
    lats = np.array([c[1] for c in route])
    x, y = latlon_to_enu(lats, lons, lat0, lon0)
    p = analysis_params()
    path = resample_path(np.stack([x, y], 1), PATH_STEP)
    segs = make_segments(path, PATH_STEP, float(p["segment_length_m"]))
    for s in segs:
        s["metrics"] = {"road_left_m": ROAD_WIDTH_M / 2, "road_right_m": ROAD_WIDTH_M / 2, "road_width_m": ROAD_WIDTH_M,
                        "coverage": 1.0, "surface_std_mm": None}

    findings = [_finding(q, lat0, lon0) for q in pots]
    _, station, _ = station_offset(np.array([[f["x"], f["y"]] for f in findings]), path, PATH_STEP)
    ends = [s["s1"] for s in segs]
    for f, st in zip(findings, station):
        f["segment_id"] = segs[int(np.clip(np.searchsorted(ends, st), 0, len(segs) - 1))]["id"]
    _finalize_findings(findings, lat0, lon0, "F" + sid[:3].upper() + "-")
    score_segments(segs, findings)
    _segments_to_geo(segs, lat0, lon0)

    photos = store.survey_dir(pid, sid) / "work" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    for f, q in zip(findings, pots):
        shutil.copyfile(MOCK_DIR / q["image_path"], photos / f"{f['id']}.jpg")

    an = {"segments": segs, "findings": findings, "path": path.tolist(), "params": p, "seconds": 0.0, "survey_id": sid}
    store.save_analysis(pid, sid, an)
    stats = {"points": 0, "findings": len(findings), "segments": len(segs),
             "length_m": round(sum(s["length_m"] for s in segs), 1), "analysis_s": 0.0}
    store.update_survey(pid, sid, status="done", stage="", stats=stats,
                        notes=["Imported from a recorded camera run; pothole depth is assumed (5 cm), not measured."])
    with store.lock(pid):
        proj = store.get_project(pid)
        proj["baseline"] = sid
        store.save_project(proj)
    return proj


def photo_path(pid: str, sid: str, fid: str) -> Path | None:
    """The detector crop for an imported finding, or None."""
    import re

    if not re.fullmatch(r"F[0-9A-Z]{3}-\d{4}", fid):
        return None
    f = store.survey_dir(pid, sid) / "work" / "photos" / f"{fid}.jpg"
    return f if f.is_file() else None


def photo_card(pid: str, sid: str, f: dict) -> dict | None:
    """Job-card photo for a finding that has a detector crop (same shape as jobcard.best_frame)."""
    if not f.get("photo") or photo_path(pid, sid, f["id"]) is None:
        return None
    d = f.get("detector") or {}
    note = f"Detector crop, frames {d.get('frames', '?')}, confidence {float(f.get('confidence') or d.get('max_conf') or 0):.2f}"
    return {"url": f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/photo", "note": note, "boxes": []}

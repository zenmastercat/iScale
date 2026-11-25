"""Import a recorded camera pothole run (config/mock/sukhumvit-asok/) as a finished survey.

There is no point cloud: the analysis is written directly, in the shape analyze() +
pipeline._finalize_findings/_segments_to_geo produce, so every page treats it like any other survey.
The route is the baked OpenStreetMap centreline (route.json), so the import works offline.

Positions: the file's latitude/longitude is the phone's GPS fix when the detector saw the pothole, and phone GPS
drifts tens of metres between Sukhumvit's tall buildings. Each pothole is placed on the road instead: the phone fix
is projected onto the centreline, moved forward by the detector's distance ahead of the camera (min_dist_y_m) and
sideways by its lateral offset (avg_lat_x_m, + = right of travel), kept within the carriageway. The raw fix is kept
in detector.phone_lat/phone_lon.
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


def _load() -> tuple[dict, list[list[float]]]:
    summary = json.loads((MOCK_DIR / "potholes_route_summary.json").read_text())
    route = json.loads((MOCK_DIR / "route.json").read_text())["coords"]  # [[lon, lat], ...]
    return summary, route


MAX_LATERAL_M = 3.0  # half a carriageway: a pothole never lands off the road


def on_road(p: dict, path: np.ndarray, lat0: float, lon0: float) -> tuple[float, float]:
    """Where the pothole is on the road (ENU m): phone fix snapped to the route, + distance ahead, + lateral offset."""
    px, py = latlon_to_enu(np.array([p["latitude"]]), np.array([p["longitude"]]), lat0, lon0)
    _, station, _ = station_offset(np.array([[float(px[0]), float(py[0])]]), path, PATH_STEP)
    total = (len(path) - 1) * PATH_STEP
    st = float(np.clip(station[0] + float(p.get("min_dist_y_m") or 0.0), 0.0, total))
    i = min(int(st // PATH_STEP), len(path) - 2)
    t = (st - i * PATH_STEP) / PATH_STEP
    base = path[i] * (1 - t) + path[i + 1] * t
    fwd = path[i + 1] - path[i]
    fwd = fwd / (np.linalg.norm(fwd) + 1e-12)
    right = np.array([fwd[1], -fwd[0]])
    lat = float(np.clip(float(p.get("avg_lat_x_m") or 0.0), -MAX_LATERAL_M, MAX_LATERAL_M))
    x, y = base + right * lat
    return float(x), float(y)


def _finding(p: dict, lat0: float, lon0: float, path: np.ndarray) -> dict:
    d = p["dimensions_m"]
    depth = float(d["assumed_depth_m"])
    area = float(p["area_m2"])
    dia = 2 * math.sqrt(area / math.pi)
    x, y = on_road(p, path, lat0, lon0)
    hw, hl = d["width_m"] / 2, d["length_m"] / 2
    weak = not p["alerted"]
    evidence = (f"pothole about {d['width_m']:.1f} x {d['length_m']:.1f} m ({area:.1f} m2), found by the camera detector "
                f"(confidence {p['max_conf']:.2f}, seen in {p['hits']} frames); depth assumed {depth * 100:.0f} cm, not measured; "
                f"placed on the road from the phone's GPS and the detector's distance ahead ({p['min_dist_y_m']:.1f} m)")
    if weak:
        evidence += "; weak track (few detections): an engineer should check it first"
    return {
        "type": "pothole", "severity": _severity_pothole(depth, dia), "source": "detector",
        "x": x, "y": y, "z": 0.0, "bbox": [x - hw, y - hl, 0.0, x + hw, y + hl, depth],
        "metrics": {"area_m2": round(area, 3), "depth_max_m": depth, "depth_median_m": depth, "depth_assumed": True,
                    "width_m": d["width_m"], "length_m": d["length_m"], "volume_m3": p["est_volume_m3"],
                    # "Across" on the cards is the detector box width (the equivalent-circle diameter is not what a rectangle looks like)
                    "diameter_m": d["width_m"], "equivalent_diameter_m": round(dia, 2)},
        "evidence": evidence, "confidence": p["max_conf"], "needs_review": weak, "photo": True,
        "detector": {"track_id": p["id"], "frames": p["frames"], "hits": p["hits"], "max_conf": p["max_conf"],
                     "alerted": p["alerted"], "min_dist_y_m": p["min_dist_y_m"],
                     "avg_lat_x_m": p["avg_lat_x_m"], "phone_lat": p["latitude"], "phone_lon": p["longitude"],
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
        # a camera run has no 3D surface: width, coverage and roughness are unknown, not zero (the pages show "–")
        s["metrics"] = {"road_left_m": None, "road_right_m": None, "road_width_m": None, "coverage": None, "surface_std_mm": None}

    findings = [_finding(q, lat0, lon0, path) for q in pots]
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
        # the detector's own view: the same crop with its box and "#id conf y" label drawn on (AI evidence)
        det = MOCK_DIR / "detections" / Path(q["image_path"]).name
        if det.is_file():
            shutil.copyfile(det, photos / f"{f['id']}_detection.jpg")
            f["detection_photo"] = True

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


def photo_path(pid: str, sid: str, fid: str, detection: bool = False) -> Path | None:
    """The clean crop (or, with detection=True, the detector's annotated view) for an imported finding, or None."""
    import re

    if not re.fullmatch(r"F[0-9A-Z]{3}-\d{4}", fid):
        return None
    f = store.survey_dir(pid, sid) / "work" / "photos" / (f"{fid}_detection.jpg" if detection else f"{fid}.jpg")
    return f if f.is_file() else None


def photo_card(pid: str, sid: str, f: dict) -> dict | None:
    """Job-card photo for a finding that has a detector crop (same shape as jobcard.best_frame)."""
    if not f.get("photo") or photo_path(pid, sid, f["id"]) is None:
        return None
    d = f.get("detector") or {}
    note = f"Detector crop, frames {d.get('frames', '?')}, confidence {float(f.get('confidence') or d.get('max_conf') or 0):.2f}"
    return {"url": f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/photo", "note": note, "boxes": []}

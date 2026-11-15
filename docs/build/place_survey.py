"""Put a finished clip survey on a real street, without re-running the detector or LingBot-Map.

A YouTube clip has no GPS, so a clip is first placed at the project origin heading north. This
turns the finished survey (3D points, camera path, findings) rigidly about its start (0, 0) to
the street's heading and recomputes latitude and longitude from the given start point.
Measurements are unchanged. Which stretch was filmed and the direction are assumptions that
the caller states in `label`.

Usage: uv run python docs/build/place_survey.py <project_id> <survey_id> <start_lat> <start_lon> <heading_deg> "<label>"
(The Rangoon Road placement, replace_field_test.py, is the same operation with fixed values.)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from civil import store  # noqa: E402
from civil.pointcloud import Reconstruction  # noqa: E402
from civil.pipeline import _finalize_findings, _segments_to_geo  # noqa: E402


def _rot_xy(xy, a: float):
    c, s = math.cos(a), math.sin(a)
    xy = np.asarray(xy, float)
    return np.stack([c * xy[..., 0] - s * xy[..., 1], s * xy[..., 0] + c * xy[..., 1]], -1)


def place(pid: str, sid: str, lat: float, lon: float, hd: float, label: str) -> dict:
    sv = store.get_survey(pid, sid)
    params = dict(sv.get("params") or {})
    old = float(params.get("placed_heading_deg", params.get("heading_deg", 0.0)))
    a = math.radians(old - hd)  # compass heading is clockwise, ENU angles counter-clockwise
    d = store.survey_dir(pid, sid)

    rec = Reconstruction.load(store.recon_path(pid, sid))
    r = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    rec.points = (rec.points @ r.T).astype(rec.points.dtype)
    if rec.poses is not None:
        t = np.eye(4)
        t[:3, :3] = r
        rec.poses = t @ rec.poses
    rec.save(store.recon_path(pid, sid))

    an = json.loads((d / "analysis.json").read_text())
    for f in an["findings"]:
        f["x"], f["y"] = map(float, _rot_xy([f["x"], f["y"]], a))
        if f.get("bbox"):
            b = f["bbox"]
            cs = _rot_xy([[b[0], b[1]], [b[3], b[1]], [b[0], b[4]], [b[3], b[4]]], a)
            f["bbox"] = [float(cs[:, 0].min()), float(cs[:, 1].min()), b[2], float(cs[:, 0].max()), float(cs[:, 1].max()), b[5]]
    if an.get("path"):
        pth = np.asarray(an["path"], float)
        pth[:, :2] = _rot_xy(pth[:, :2], a)
        an["path"] = pth.tolist()
    for sg in an["segments"]:
        sg["line"] = _rot_xy(sg["line"], a).tolist()
    _finalize_findings(an["findings"], lat, lon, "F" + sid[:3].upper() + "-")
    _segments_to_geo(an["segments"], lat, lon)
    store.save_analysis(pid, sid, an)

    params.update({"placed_heading_deg": hd, "placed_start": [lat, lon]})
    notes = [n for n in (sv.get("notes") or []) if not n.startswith(("placed by heading", "street from", "placed on"))]
    notes.append(f"placed on {label}, heading {hd:.0f} deg; stretch and direction assumed (no GPS)")
    store.update_survey(pid, sid, params=params, notes=notes)
    return {"survey": sid, "turned_deg": round(math.degrees(a), 1), "notes": notes[-1],
            "potholes": sum(f["type"] == "pothole" for f in an["findings"])}


if __name__ == "__main__":
    pid_, sid_, la, lo, h, lbl = sys.argv[1:7]
    print(json.dumps(place(pid_, sid_, float(la), float(lo), float(h), lbl)))

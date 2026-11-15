"""Put the Rangoon Road field test on the real street, without re-running the detector or LingBot-Map.

The YouTube clip has no GPS, so the first run placed the walk at the default project origin
(Bangkok), heading north. This script moves the project origin onto Rangoon Road, Leonardsville,
Ladysmith (KwaZulu-Natal; OpenStreetMap way 854179657, the only Rangoon Road in the province),
turns the finished survey (3D points, camera path, findings) to follow the street, and
recomputes latitude and longitude. Measurements are unchanged. The street is from OpenStreetMap; WHICH stretch of it was filmed, and the
walking direction, are assumptions.

Usage: uv run python docs/build/replace_field_test.py <project_id> <clip_survey_id>
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

# Straight middle stretch of Rangoon Road (two OSM nodes of way 854179657).
A = (-28.5642267, 29.7896272)
B = (-28.5624799, 29.7866687)
START = (-28.5636825, 29.7886938)  # OSM node on that stretch; assumed start of the walk


def heading(a, b) -> float:
    north = (b[0] - a[0]) * 111_320.0
    east = (b[1] - a[1]) * 111_320.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.degrees(math.atan2(east, north)) % 360


def _rot_xy(xy, a: float):
    c, s = math.cos(a), math.sin(a)
    xy = np.asarray(xy, float)
    return np.stack([c * xy[..., 0] - s * xy[..., 1], s * xy[..., 0] + c * xy[..., 1]], -1)


def main(pid: str, sid: str) -> None:
    """Turn the finished survey rigidly about the walk start (0, 0), so every measurement stays
    exactly as analysed (the analysis grid follows the world axes, and re-analysing at another
    angle changes pothole sizes by up to about a third), then recompute latitude and longitude."""
    hd = round(heading(A, B), 1)
    sv = store.get_survey(pid, sid)
    params = dict(sv.get("params") or {})
    old = float(params.get("placed_heading_deg", params.get("heading_deg", 0.0)))
    a = math.radians(old - hd)  # compass heading is clockwise, ENU angles counter-clockwise
    d = store.survey_dir(pid, sid)

    rec = Reconstruction.load(store.recon_path(pid, sid))
    r = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    rec.points = (rec.points @ r.T).astype(rec.points.dtype)
    if rec.poses is not None:
        T = np.eye(4); T[:3, :3] = r
        rec.poses = T @ rec.poses
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
    _finalize_findings(an["findings"], START[0], START[1], "F" + sid[:3].upper() + "-")
    _segments_to_geo(an["segments"], START[0], START[1])
    store.save_analysis(pid, sid, an)

    with store.lock(pid):
        proj = store.get_project(pid)
        proj["origin_lat"], proj["origin_lon"] = START
        proj["placement"] = {"street": "Rangoon Road, Leonardsville, Ladysmith, KwaZulu-Natal (OSM way 854179657)",
                             "heading_deg": hd, "assumed": "stretch and walking direction (no GPS in the clip)"}
        store.save_project(proj)
    params["placed_heading_deg"] = hd
    notes = [n for n in (sv.get("notes") or []) if not n.startswith(("placed by heading", "street from"))]
    notes += [f"placed on Rangoon Road, Ladysmith (OpenStreetMap), heading {hd:.0f} deg; stretch and direction assumed (no GPS)"]
    store.update_survey(pid, sid, params=params, notes=notes)
    print(json.dumps({"heading_deg": hd, "turned_deg": round(math.degrees(a), 1), "notes": notes,
                      "pothole_lat_lon": [[round(f["lat"], 6), round(f["lon"], 6)] for f in an["findings"] if f["type"] == "pothole"]}))


if __name__ == "__main__":
    main(*sys.argv[1:3])

"""Before/after verification: did the repair actually happen?

Both surveys are in the same project frame (GPS-georeferenced), so a finding's
location can be looked up in the after-survey directly.  For each defect we check:
  1. coverage   the after survey has points at the defect location
  2. re-detect  the after analysis has a defect of the same family within 1 m
  3. surface    mean height inside the old outline vs. a ring around it
"""

from __future__ import annotations

import time

import numpy as np

from .pointcloud import Reconstruction

FAMILY = {"pothole": "depression", "depression": "depression", "manhole_sunken": "depression",
          "heave": "heave", "surface_roughness": "roughness", "sidewalk_trip_hazard": "trip"}


def _surface_delta(rec: Reconstruction, f: dict) -> tuple[int, float | None]:
    b = f["bbox"]
    cx, cy = f["x"], f["y"]
    rx = max(0.15, (b[3] - b[0]) / 2)
    ry = max(0.15, (b[4] - b[1]) / 2)
    p = rec.points
    near = (np.abs(p[:, 0] - cx) < rx + 1.0) & (np.abs(p[:, 1] - cy) < ry + 1.0) & (p[:, 2] < f["z"] + 0.5)
    q = p[near]
    if len(q) == 0:
        return 0, None
    inside = (np.abs(q[:, 0] - cx) < rx) & (np.abs(q[:, 1] - cy) < ry)
    ring = ~((np.abs(q[:, 0] - cx) < rx + 0.3) & (np.abs(q[:, 1] - cy) < ry + 0.3))
    if inside.sum() < 5 or ring.sum() < 5:
        return int(inside.sum()), None
    return int(inside.sum()), float(np.median(q[inside, 2]) - np.median(q[ring, 2]))


def verify(before_findings: list[dict], after_findings: list[dict], after_rec: Reconstruction,
           only_ids: list[str] | None = None) -> dict:
    results = []
    after_def = [a for a in after_findings if a["type"] in FAMILY]
    for f in before_findings:
        if f["type"] not in FAMILY:
            continue
        if only_ids and f["id"] not in only_ids:
            continue
        n_in, delta = _surface_delta(after_rec, f)
        fam = FAMILY[f["type"]]
        match = None
        for a in after_def:
            if FAMILY[a["type"]] == fam and np.hypot(a["x"] - f["x"], a["y"] - f["y"]) < 1.0:
                match = a
                break
        if n_in < 5:
            status, why = "not_covered", "the after survey has no points at this location"
        elif match is not None:
            status = "not_fixed"
            why = f"still detected in the after survey ({match['id']}: {match['evidence']})"
        else:
            status = "verified"
            why = "not detected in the after survey"
            if delta is not None:
                why += f"; surface now {delta * 100:+.1f} cm relative to its surroundings"
        results.append({"finding_id": f["id"], "type": f["type"], "severity": f.get("severity"),
                        "status": status, "evidence": why, "after_match": match["id"] if match else None,
                        "surface_delta_m": None if delta is None else round(delta, 3),
                        "before_metrics": f.get("metrics", {}), "after_metrics": match.get("metrics") if match else None,
                        "lat": f.get("lat"), "lon": f.get("lon"), "x": f["x"], "y": f["y"]})
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("verified", "not_fixed", "not_covered")}
    return {"created": time.time(), "results": results, "counts": counts}

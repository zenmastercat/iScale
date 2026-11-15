"""Segment condition index (0-100), PCI-like.

This is a simplified deduct-value model, NOT a certified ASTM D6433 PCI:
each defect contributes a deduct that grows with severity and with the share of
the segment's surface it affects; deducts are combined with diminishing weight
(largest first) and subtracted from 100.  Tune the tables to your agency's data.
"""

from __future__ import annotations

import math

BASE_DEDUCT = {"low": 4.0, "medium": 10.0, "high": 20.0}
TYPE_FACTOR = {
    "pothole": 1.0, "depression": 0.7, "heave": 0.7, "surface_roughness": 0.9, "manhole_sunken": 0.4,
    "rutting": 0.9, "alligator_cracking": 1.0, "longitudinal_crack": 0.5, "transverse_crack": 0.5,
    "block_cracking": 0.6, "edge_cracking": 0.4, "patch_failure": 0.7, "raveling": 0.6, "bleeding": 0.3,
    "shoving": 0.7, "joint_spall": 0.5, "faulting": 0.6, "utility_cut": 0.4, "ponding": 0.4,
}
BANDS = [(85, "good", "#3fb37f"), (70, "satisfactory", "#9fc84a"), (55, "fair", "#e8c547"),
         (40, "poor", "#ef8f36"), (25, "very poor", "#e0503a"), (0, "failed", "#8c1d2c")]


def band(index: float) -> tuple[str, str]:
    for lo, name, color in BANDS:
        if index >= lo:
            return name, color
    return BANDS[-1][1], BANDS[-1][2]


def score_segments(segs: list[dict], findings: list[dict]) -> None:
    by_seg: dict[str, list[dict]] = {}
    for f in findings:
        if f.get("status") in ("fixed", "verified", "dismissed"):
            continue
        by_seg.setdefault(f.get("segment_id", ""), []).append(f)
    for seg in segs:
        met = seg.setdefault("metrics", {})
        width = met.get("road_width_m") or 7.0
        road_area = max(1.0, seg["length_m"] * width)
        deducts = []
        for f in by_seg.get(seg["id"], []):
            if f["type"] not in TYPE_FACTOR or not f.get("severity"):
                continue
            area = float(f.get("metrics", {}).get("area_m2", 0.25))
            density_pct = 100.0 * area / road_area
            d = BASE_DEDUCT[f["severity"]] * TYPE_FACTOR[f["type"]] * (1 + math.log10(1 + density_pct))
            deducts.append(d)
        deducts.sort(reverse=True)
        total = sum(d * (0.7 ** i) for i, d in enumerate(deducts))
        idx = max(0.0, 100.0 - total)
        if met.get("coverage", 1.0) == 0.0:
            seg["condition"] = None
            seg["rating"], seg["color"] = "no data", "#6b7280"
        else:
            seg["condition"] = round(idx, 1)
            seg["rating"], seg["color"] = band(idx)
        seg["defect_count"] = len(deducts)
        seg["area_m2"] = round(road_area, 1)

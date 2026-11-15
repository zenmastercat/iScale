"""Map of the Thai field test (EP160 section on Route 348, Non Din Daeng), on OpenStreetMap tiles.

Usage: uv run python docs/build/thai_map.py <project_id> <clip_survey_id> [<clip_survey_id> ...]
Writes docs/build/fig/f17_thai_map.png and fig/thai_map.json. Tiles are cached in fig/.tiles
(fetched once, per the OpenStreetMap tile usage policy). Map data © OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from field_map import ACTION, INK, INK2, OUT, SEV, UA, basemap, m_per_px, scalebar  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PT = (14.2716744, 102.7155621)  # OSM node 2127590173, "PT" fuel station


def main(pid: str, sids: list[str]) -> None:
    base = ROOT / "data" / "projects" / pid
    pots, paths = [], []
    for sid in sids:
        an = json.loads((base / "surveys" / sid / "analysis.json").read_text())
        pots += [f for f in an["findings"] if f["type"] == "pothole"]
        for sg in an["segments"]:
            paths.append(np.array(sg["coords"]))  # [lon, lat]
    lat0 = float(np.mean([f["lat"] for f in pots]))
    lon0 = float(np.mean([f["lon"] for f in pots]))
    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as client:
        ov, ov_px = basemap(lat0, lon0, 15, 700, 700, client)
        dz, DW = 18, 420
        dt, dt_px = basemap(lat0, lon0, dz, DW, DW, client)
    mpp = m_per_px(lat0, dz)

    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 6.1))
    a.imshow(ov)
    cx, cy = ov_px(lat0, lon0)
    side = DW * mpp / m_per_px(lat0, 15)
    a.add_patch(Rectangle((cx - side / 2, cy - side / 2), side, side, fill=False, ec=ACTION, lw=1.6))
    a.annotate("surveyed stretch\n(right)", (cx + side / 2, cy - side / 2), (cx + 90, cy - 170), fontsize=9, color=ACTION,
               arrowprops=dict(arrowstyle="-", color=ACTION, lw=1), bbox=dict(fc="white", ec="none", alpha=0.85))
    scalebar(a, 30, 670, 500, m_per_px(lat0, 15), "500 m")
    a.set_title("Route 348 (Thana Withi Road), Non Din Daeng, Buriram", fontsize=10)
    a.axis("off")

    b.imshow(dt, interpolation="bicubic")
    for i, pth in enumerate(paths):
        line = np.array([dt_px(la, lo) for lo, la in pth])
        b.plot(line[:, 0], line[:, 1], color=ACTION, lw=2, ls="--", label="camera path" if i == 0 else None)
    first = np.array([dt_px(la, lo) for lo, la in paths[0]])
    tip = first[min(len(first) - 1, 30)]
    b.add_patch(FancyArrowPatch(tuple(first[0]), tuple(tip), arrowstyle="-|>", mutation_scale=18, color=ACTION, lw=2, zorder=5))
    for f in pots:
        x, y = dt_px(f["lat"], f["lon"])
        r = max(4.0, (f["metrics"].get("diameter_m") or 0.6) / 2 / mpp)  # at least 4 px so small finds show
        b.add_patch(Circle((x, y), r, fc=SEV.get(f["severity"], INK), ec="white", lw=0.8, alpha=0.6, zorder=4))
    px_, py_ = dt_px(*PT)
    b.plot(px_, py_, marker="P", ms=11, mfc="#0b7a3b", mec="white", zorder=6)
    b.annotate("PT station (OSM): anchor,\nseen at 5:30 in the video", (px_, py_), (px_ - 250, py_ - 70), fontsize=8, color=INK,
               arrowprops=dict(arrowstyle="-", color=INK2, lw=0.7), bbox=dict(fc="white", ec="none", alpha=0.85))
    handles = [plt.Line2D([], [], marker="o", ls="", ms=9, mfc=SEV[k], mec="white", alpha=0.7, label=f"pothole, {k}")
               for k in ("high", "medium", "low") if any(f["severity"] == k for f in pots)]
    handles += [plt.Line2D([], [], color=ACTION, ls="--", lw=2, label="camera path (direction: arrow)"),
                plt.Line2D([], [], marker="P", ls="", ms=9, mfc="#0b7a3b", mec="white", label="anchor")]
    b.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, 0.93), fontsize=8, framealpha=0.92)
    scalebar(b, 14, 16, 50, mpp, "50 m")
    b.set_title(f"{len(pots)} potholes (circles at measured size, at least 4 px)", fontsize=10)
    b.axis("off")
    b.text(DW - 2, DW - 2, "Map data © OpenStreetMap contributors", ha="right", va="bottom", fontsize=7, color=INK2,
           bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))
    fig.savefig(OUT / "f17_thai_map.png")
    plt.close(fig)
    out = {"centre": [round(lat0, 6), round(lon0, 6)], "potholes": len(pots),
           "rows": [{"id": f["id"], "severity": f["severity"], "source": f["source"], "lat": round(f["lat"], 6), "lon": round(f["lon"], 6),
                     "diameter_m": f["metrics"].get("diameter_m"), "depth_max_m": f["metrics"].get("depth_max_m"),
                     "depth_unreliable": bool(f["metrics"].get("depth_unreliable"))} for f in pots]}
    (OUT / "thai_map.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("centre", "potholes")}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

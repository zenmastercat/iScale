"""Map of where the field test found potholes (docx figure 13), on OpenStreetMap tiles.

Usage: uv run python docs/build/field_map.py <project_id> <clip_survey_id>
Writes docs/build/fig/f13_field_map.png. Tiles are cached in docs/build/fig/.tiles (a few dozen,
fetched once, per the OpenStreetMap tile usage policy). Map data © OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("fig")
CACHE = OUT / ".tiles"
CACHE.mkdir(parents=True, exist_ok=True)
INK, INK2, ACTION = "#1d2622", "#5e6a64", "#1e4f8f"
SEV = {"high": "#b42318", "medium": "#d9730d", "low": "#c9a100"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 200, "savefig.bbox": "tight"})
UA = {"User-Agent": "civil-scan-docs/0.1 (figure build; tiles cached)"}


def px(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Web Mercator global pixel coordinates at zoom z (256 px tiles)."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile(z: int, x: int, y: int, client: httpx.Client) -> Image.Image:
    f = CACHE / f"{z}_{x}_{y}.png"
    if not f.is_file():
        r = client.get(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        r.raise_for_status()
        f.write_bytes(r.content)
    return Image.open(io.BytesIO(f.read_bytes())).convert("RGB")


def basemap(lat: float, lon: float, z: int, w: int, h: int, client: httpx.Client):
    """Image of w x h px centred on (lat, lon) and a function lat/lon -> image px."""
    cx, cy = px(lat, lon, z)
    x0, y0 = cx - w / 2, cy - h / 2
    img = Image.new("RGB", (w, h))
    for tx in range(int(x0 // 256), int((x0 + w) // 256) + 1):
        for ty in range(int(y0 // 256), int((y0 + h) // 256) + 1):
            img.paste(tile(z, tx, ty, client), (int(tx * 256 - x0), int(ty * 256 - y0)))
    return np.asarray(img), (lambda la, lo: (px(la, lo, z)[0] - x0, px(la, lo, z)[1] - y0))


def m_per_px(lat: float, z: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** z


def scalebar(ax, x, y, metres, mpp, label, h=None):
    L = metres / mpp
    h = h or max(1.0, L / 12)
    ax.add_patch(Rectangle((x, y - h / 2), L, h, color=INK, zorder=5))
    ax.text(x + L / 2, y - h * 1.4, label, ha="center", va="bottom", fontsize=8, color=INK, zorder=5,
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))


def main(pid: str, sid: str) -> None:
    base = ROOT / "data" / "projects" / pid
    proj = json.loads((base / "project.json").read_text())
    an = json.loads((base / "surveys" / sid / "analysis.json").read_text())
    finds = an["findings"]
    pots = [f for f in finds if f["type"] == "pothole"]
    seg = an["segments"][0]["coords"]  # [lon, lat]
    lat0 = float(np.mean([f["lat"] for f in pots]))
    lon0 = float(np.mean([f["lon"] for f in pots]))

    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as client:
        ov, ov_px = basemap(lat0, lon0, 16, 760, 760, client)
        dz = 19
        DW = 190  # px at zoom 19, about 50 m across
        dt, dt_px = basemap(lat0, lon0, dz, DW, DW, client)
    mpp = m_per_px(lat0, dz)

    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 5.9))
    # overview -----------------------------------------------------------------
    a.imshow(ov)
    cx, cy = ov_px(lat0, lon0)
    side = DW * m_per_px(lat0, dz) / m_per_px(lat0, 16)
    a.add_patch(Rectangle((cx - side / 2, cy - side / 2), side, side, fill=False, ec=ACTION, lw=1.6))
    a.add_patch(Circle((cx, cy), 26, fill=False, ec=ACTION, lw=2))
    a.annotate("surveyed stretch\n(right)", (cx + 20, cy - 18), (cx + 120, cy - 150), fontsize=9, color=ACTION,
               arrowprops=dict(arrowstyle="-", color=ACTION, lw=1), bbox=dict(fc="white", ec="none", alpha=0.85))
    scalebar(a, 30, 730, 200, m_per_px(lat0, 16), "200 m")
    a.set_title("Rangoon Road, Leonardsville, Ladysmith (KwaZulu-Natal)", fontsize=10)
    a.axis("off")
    # detail -------------------------------------------------------------------
    b.imshow(dt, interpolation="bicubic")
    line = np.array([dt_px(la, lo) for lo, la in seg])
    b.plot(line[:, 0], line[:, 1], color=ACTION, lw=2, ls="--", label="walked path")
    for f in finds:
        x, y = dt_px(f["lat"], f["lon"])
        if f["type"] == "pothole":
            r = max(0.15, f["metrics"].get("diameter_m", 0.3) / 2) / mpp
            b.add_patch(Circle((x, y), r, fc=SEV.get(f["severity"], INK), ec="white", lw=1.2, alpha=0.55, zorder=4))
        else:
            b.plot(x, y, "^" if f["type"] == "heave" else "s", ms=5, mfc="none", mec=INK2, mew=1.2, zorder=3)
    # numbered labels: sorted along the walk, alternating sides, spaced evenly so none overlap
    path_dir = (line[-1] - line[0]) / max(1e-6, np.linalg.norm(line[-1] - line[0]))
    normal = np.array([-path_dir[1], path_dir[0]])
    pos = [(np.dot(np.array(dt_px(f["lat"], f["lon"])) - line[0], path_dir), f) for f in pots]
    pos.sort(key=lambda t: t[0])
    span = np.linalg.norm(line[-1] - line[0])
    for i, (st, f) in enumerate(pos):
        x, y = dt_px(f["lat"], f["lon"])
        k = i // 2
        n_side = (len(pos) + 1) // 2
        along = -0.15 * span + (1.3 * span) * (k + 0.5) / n_side
        side_ = 1 if i % 2 == 0 else -1
        tx, ty = line[0] + path_dir * along + normal * side_ * 34
        b.annotate(str(int(f["id"].split("-")[1])), (x, y), (tx, ty), fontsize=8.5, ha="center", va="center", color=INK, zorder=6,
                   arrowprops=dict(arrowstyle="-", color=INK2, lw=0.7),
                   bbox=dict(boxstyle="circle,pad=0.25", fc="white", ec=SEV.get(f["severity"], INK), lw=1.2))
    handles = [plt.Line2D([], [], marker="o", ls="", ms=9, mfc=SEV[k], mec="white", alpha=0.7, label=f"pothole, {k}")
               for k in ("high", "medium", "low") if any(f["severity"] == k for f in pots)]
    handles += [plt.Line2D([], [], marker="^", ls="", mfc="none", mec=INK2, label="raised area (heave)"),
                plt.Line2D([], [], marker="s", ls="", mfc="none", mec=INK2, label="rough patch"),
                plt.Line2D([], [], color=ACTION, ls="--", lw=2, label="walked path")]
    b.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.92)
    scalebar(b, DW - 10 - 10 / mpp, 14, 10, mpp, "10 m")
    b.set_title("Findings, circles drawn at measured size", fontsize=10)
    b.axis("off")
    b.text(DW - 2, DW - 2, "Map data © OpenStreetMap contributors", ha="right", va="bottom", fontsize=7, color=INK2, bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))
    fig.savefig(OUT / "f13_field_map.png")
    plt.close(fig)
    print(json.dumps({"centre": [round(lat0, 6), round(lon0, 6)], "origin": [proj["origin_lat"], proj["origin_lon"]],
                      "tiles": len(list(CACHE.glob("*.png")))}))


if __name__ == "__main__":
    main(*sys.argv[1:3])

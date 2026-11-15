"""The iScale flow, end to end, on the Route 348 test (f20_iscale_flow.png / .pdf).

Run from the project root, after flow_parts.py:
    uv run --no-project --with matplotlib --with numpy --with pillow python docs/build/iscale_flow.py
Every number on the figure is read from docs/build/fig/flow/facts.json (written by flow_parts.py from
the survey data); the screens are the app's own, with number plates pixelated.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PARTS, SHOT, FIG = HERE / "fig" / "flow", ROOT / "docs" / "screenshots", HERE / "fig"
facts = json.loads((PARTS / "facts.json").read_text())

for f in ("/nix/store/5gbijvvjbp9pvp0dv77g16dn45xyxlrh-noto-fonts-2026.09.01/share/fonts/noto/NotoSansThai.ttf",):
    if Path(f).exists():
        fm.fontManager.addfont(f)
plt.rcParams.update({"font.family": ["DejaVu Sans", "Noto Sans Thai"], "font.size": 11})

INK, INK2 = "#1d2622", "#5e6a64"
YEL, YEL_F = "#f2cf3d", "#f7de6e"
BLU, BLU_F = "#2050d8", "#a9cbf5"
GRN, GRN_F = "#6cc04a", "#9bd36f"
GREY = "#b9bdbb"
HIGH, MED = "#b42318", "#d9730d"

W, H = 24.0, 10.0
fig = plt.figure(figsize=(W, H))
T = fig.transFigure


def box(x, y, w, h, color, lw=3.0, ls=(0, (5, 3)), r=0.012, fill="none"):
    fig.add_artist(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", transform=T,
                                  ec=color, fc=fill, lw=lw, ls=ls, mutation_aspect=W / H))


def pill(cx, cy, text, fc, w=None, h=0.042, fs=12, color=INK, weight="normal"):
    w = w or (0.0062 * len(text) + 0.03)
    fig.add_artist(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.015", transform=T,
                                  ec="none", fc=fc, mutation_aspect=W / H))
    fig.text(cx, cy, text, ha="center", va="center", fontsize=fs, color=color, weight=weight)


def img(path, x, y, w, h=None, title=None, fs=9.5, border=False):
    im = Image.open(path).convert("RGB")
    if h is None:
        h = w * im.height / im.width * W / H
    ax = fig.add_axes([x, y, w, h])
    ax.imshow(im, interpolation="lanczos")
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(border)
        s.set_color(GREY)
    if title:
        ax.set_title(title, fontsize=fs, color=INK2, pad=3)
    return h


def arrow(pts, color=INK, lw=2.4, ls="-", head=True):
    """A polyline arrow through figure-fraction points; only the last segment has a head."""
    for i in range(len(pts) - 1):
        last = i == len(pts) - 2
        fig.add_artist(FancyArrowPatch(pts[i], pts[i + 1], transform=T, arrowstyle="-|>" if (last and head) else "-",
                                       mutation_scale=18, color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0))


# ------------------------------------------------------------------ inputs (left)
fig.text(0.013, 0.735, "Drive video", ha="left", fontsize=12, color=INK, weight="bold")
hv = img(PARTS / "d1_frame.png", 0.013, 0.505, 0.15)
# GPS phone
px, py, pw, ph = 0.03, 0.12, 0.115, 0.27
fig.add_artist(FancyBboxPatch((px, py), pw, ph, boxstyle="round,pad=0,rounding_size=0.02", transform=T, fc="#2b2f2e", ec="none", mutation_aspect=W / H))
mx, my, mw, mh = px + 0.012, py + 0.025, pw - 0.024, ph - 0.07
fig.add_artist(Rectangle((mx, my), mw, mh, transform=T, fc="#e9e4dc", ec="none"))
for (a, b, c, d, col) in [(0.05, 0.05, 0.35, 0.3, "#c9c0b6"), (0.55, 0.1, 0.4, 0.25, "#a7d18b"), (0.1, 0.55, 0.3, 0.35, "#c9c0b6"),
                          (0.55, 0.5, 0.4, 0.4, "#c9c0b6"), (0.0, 0.42, 1.0, 0.06, "#ffffff"), (0.45, 0.0, 0.06, 1.0, "#ffffff")]:
    fig.add_artist(Rectangle((mx + a * mw, my + b * mh), c * mw, d * mh, transform=T, fc=col, ec="none"))
arrow([(mx + 0.2 * mw, my + 0.1 * mh), (mx + 0.48 * mw, my + 0.45 * mh), (mx + 0.75 * mw, my + 0.78 * mh)], color=HIGH, lw=2.2, head=False)
fig.add_artist(Ellipse((mx + 0.75 * mw, my + 0.83 * mh), 0.012, 0.012 * W / H, transform=T, fc=HIGH, ec="white", lw=1.5))
fig.text(px + 0.016, py + ph - 0.028, "GPS track", fontsize=10.5, color="white", weight="bold")
fig.text(0.088, 0.085, "Opt-in, with Record a drive (section 9.5).\nThis test video has no GPS: scale from\ncamera height 1.1 m, placed by a landmark.",
         ha="center", va="top", fontsize=9, color=INK2, linespacing=1.35)
arrow([(0.135, 0.505 + hv), (0.135, 0.80), (0.183, 0.80)])                       # video -> detection
arrow([(0.145, 0.25), (0.183, 0.25)], ls=(0, (4, 3)), lw=2.0)                      # GPS -> LingBot (scale/position)
fig.text(0.164, 0.262, "scale &\nposition", ha="center", va="bottom", fontsize=8.5, color=INK2)

# ------------------------------------------------------------------ A: detection (pre-inference)
ax0, aw = 0.185, 0.375
box(ax0, 0.56, aw, 0.41, YEL)
fig.text(ax0 + 0.012, 0.935, "Detection (pre-inference)", fontsize=15, color=INK)
box(ax0 + 0.012, 0.645, aw - 0.024, 0.25, GREY, lw=2.2, ls=(0, (6, 4)))
pill(ax0 + aw / 2, 0.895, "pothole detector", YEL_F)
iw = 0.105
img(PARTS / "d1_frame.png", ax0 + 0.022, 0.70, iw, title="1. Frames, 3 per second")
img(PARTS / "d2_boxes.png", ax0 + 0.022 + iw + 0.012, 0.70, iw, title=f"2. Boxes (Roboflow, conf ≥ {facts['detector']['confidence']})")
img(PARTS / "d3_timeline.png", ax0 + 0.022 + 2 * (iw + 0.012) + 0.004, 0.665, iw - 0.006,
    title=f"3. {facts['detections']} hits → {facts['events']} events → {len(facts['windows'])} clips")
fig.text(ax0 + aw / 2, 0.598, "* Find pothole moments, cut clips of ≤ 40 s around them *", ha="center", fontsize=12.5, color=INK)

# ------------------------------------------------------------------ B: feature engineering (LingBot-Map)
box(ax0, 0.03, aw, 0.5, YEL)
fig.text(ax0 + 0.012, 0.495, "Feature Engineering (LingBot-Map 3D)", fontsize=15, color=INK)
box(ax0 + 0.012, 0.215, aw - 0.024, 0.245, GREY, lw=2.2, ls=(0, (6, 4)))
pill(ax0 + aw / 2, 0.46, "3D reconstruction", YEL_F)
arrow([(ax0 + aw / 2, 0.56), (ax0 + aw / 2, 0.485)])
fig.text(ax0 + aw / 2 + 0.008, 0.545, "clips + the detector's boxes on every frame", ha="left", va="center", fontsize=10, color="#c0187f", style="italic")
cols = [("l1_frames.png", "Frames + boxes"), ("l5_detector.png", "Box pixels → 3D points"),
        ("l3_height.png", "Height above road"), ("l4_regions.png", "Dip + detector = pothole")]
xs = [ax0 + 0.03, ax0 + 0.115, ax0 + 0.19, ax0 + 0.275]
for (f, t), x in zip(cols, xs):
    im = Image.open(PARTS / f)
    hh = 0.165
    ww = hh * im.width / im.height * H / W
    img(PARTS / f, x, 0.24, ww, hh, title=t)
pill(ax0 + aw / 2, 0.185, "feature vector", YEL_F)
arrow([(ax0 + aw / 2, 0.215), (ax0 + aw / 2, 0.207)])
box(ax0 + 0.035, 0.105, aw - 0.07, 0.055, GREY, lw=2.2, ls=(0, (6, 4)))
fig.text(ax0 + aw / 2, 0.132, "* Area · Depth · Volume · Diameter · Circularity → Severity *", ha="center", va="center", fontsize=12.5, color=INK)
pill(ax0 + aw / 2, 0.06, "Output (analysis.json)", YEL_F)
arrow([(ax0 + aw / 2, 0.105), (ax0 + aw / 2, 0.082)])
# a measured example under the panels
p3 = next(p for p in facts["potholes"] if p["n"] == 3)
fig.text(ax0 + 0.025, 0.233, f"magenta: {facts['detector_points_clip']:,} 3D points from boxes on {facts['box_frames']} frames",
         ha="left", va="top", fontsize=8.5, color="#c0187f")
fig.text(ax0 + aw - 0.02, 0.233, f"pothole 3: {p3['area_m2']} m², {p3['depth_m'] * 100:.1f} cm deep, {p3['volume_m3'] * 1000:.1f} L, {p3['severity']}",
         ha="right", va="top", fontsize=8.5, color=INK2)

# ------------------------------------------------------------------ C: rules & Civil Helper
cx0, cw = 0.578, 0.41
box(cx0, 0.50, cw, 0.47, BLU)
fig.text(cx0 + 0.012, 0.935, "Rules & Civil Helper (LLM + RAG)", fontsize=15, color=INK)
pill(cx0 + 0.062, 0.86, "Findings (json)", BLU_F, w=0.1)
pill(cx0 + 0.062, 0.80, "Shared pins", BLU_F, w=0.1)
fig.text(cx0 + 0.165, 0.83, "⚙", ha="center", va="center", fontsize=46, color=INK)
fig.text(cx0 + 0.165, 0.775, "fixed rules\n(config files)", ha="center", va="top", fontsize=9.5, color=INK2)
arrow([(cx0 + 0.112, 0.86), (cx0 + 0.135, 0.86), (cx0 + 0.135, 0.835), (cx0 + 0.145, 0.835)], head=False)
arrow([(cx0 + 0.112, 0.80), (cx0 + 0.135, 0.80), (cx0 + 0.135, 0.83), (cx0 + 0.145, 0.83)])
box(cx0 + 0.215, 0.555, 0.185, 0.365, GREY, lw=2.2, ls=(0, (6, 4)))
outs = [("Risk", "fix-first: severity × safety × traffic"), ("Location", "map pin, address (OpenStreetMap)"),
        ("Cost & Material", "DOH method, TPSO / store prices"), ("Time & Traffic", "work window by road type, Google traffic")]
for i, (t, sub) in enumerate(outs):
    y = 0.875 - i * 0.083
    pill(cx0 + 0.3075, y, t, GRN_F, w=0.15, h=0.04, fs=12)
    fig.text(cx0 + 0.3075, y - 0.031, sub, ha="center", va="center", fontsize=8.3, color=INK2)
arrow([(cx0 + 0.188, 0.83), (cx0 + 0.213, 0.83)])
# Civil Helper (LLM + RAG): answers questions beside the rules
fig.text(cx0 + 0.062, 0.705, "Civil Helper", ha="center", fontsize=12, color=INK, weight="bold")
fig.add_artist(FancyBboxPatch((cx0 + 0.03, 0.6), 0.064, 0.085, boxstyle="round,pad=0,rounding_size=0.012", transform=T,
                              fc="white", ec=INK, lw=2.2, mutation_aspect=W / H))
fig.text(cx0 + 0.062, 0.6425, "LLM", ha="center", va="center", fontsize=14, color=INK, weight="bold")
fig.text(cx0 + 0.062, 0.588, "local, Ollama\n(tested: Qwen 3.5 9B)", ha="center", va="top", fontsize=8.3, color=INK2)
dbx, dby = cx0 + 0.165, 0.615
for k, col in enumerate(["#2f6fe0", "#4f8cf0", "#79aaf6"]):
    fig.add_artist(Rectangle((dbx - 0.022, dby + k * 0.022), 0.044, 0.022, transform=T, fc=col, ec="none"))
    fig.add_artist(Ellipse((dbx, dby + (k + 1) * 0.022), 0.044, 0.012 * W / H * 0.9, transform=T, fc=col, ec="white", lw=1))
fig.add_artist(Ellipse((dbx, dby), 0.044, 0.012 * W / H * 0.9, transform=T, fc="#2f6fe0", ec="none"))
fig.text(dbx, 0.588, "company manuals\n(retrieved, cited)", ha="center", va="top", fontsize=8.3, color=INK2)
arrow([(cx0 + 0.143, 0.645), (cx0 + 0.096, 0.645)])
fig.text(cx0 + 0.119, 0.66, "RAG", ha="center", fontsize=8.5, color=INK2)
fig.text(cx0 + 0.062, 0.535, "answers engineers' questions, with sources", ha="left", fontsize=9, color=INK2, style="italic")

# analysis.json -> C (along the bottom and up, as in the example)
arrow([(ax0 + aw / 2, 0.038), (ax0 + aw / 2, 0.018), (0.569, 0.018), (0.569, 0.83), (cx0 + 0.012, 0.83)])
arrow([(cx0 + cw / 2 + 0.1, 0.50), (cx0 + cw / 2 + 0.1, 0.468)])                   # C -> output

# ------------------------------------------------------------------ D: output
box(cx0, 0.03, cw, 0.425, GRN)
fig.text(cx0 + 0.012, 0.415, "Output", fontsize=15, color=INK)
m = Image.open(SHOT / "map-route348.png").convert("RGB")
mw_, mh_ = m.size
m.crop((int(mw_ * 0.105), int(mh_ * 0.045), mw_, mh_)).save(PARTS / "o_map.png")
img(PARTS / "o_map.png", cx0 + 0.012, 0.07, 0.185, title="Map: condition and findings (Route 348, clip 1)", border=True)
for i, (f, t) in enumerate([("jobcard-route348-location.png", "Job card: location"), ("jobcard-route348-cost.png", "Cost & material"),
                            ("check3d-phone.png", "3D check: verify")]):
    im = Image.open(SHOT / f)
    hh = 0.31
    ww = hh * im.width / im.height * H / W
    img(SHOT / f, cx0 + 0.21 + i * (ww + 0.008), 0.06, ww, hh, title=t, border=True)

fig.text(0.013, 0.012, "Footage: \"EP160 ถนนพังเร็วจัง\", ถนนไทยแลนด์ (YouTube, CC BY), Route 348, Non Din Daeng, Buriram. Number plates pixelated.",
         fontsize=8.5, color=INK2)

for ext in ("png", "pdf"):
    fig.savefig(FIG / f"f20_iscale_flow.{ext}", dpi=200, facecolor="white")
print(FIG / "f20_iscale_flow.png")

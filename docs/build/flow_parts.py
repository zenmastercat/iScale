"""Panels for the iScale flow figure (f20_iscale_flow.png), all from the Route 348 test run.

Run from the project root:  .venv/bin/python docs/build/flow_parts.py
Writes docs/build/fig/flow/*.png. Inputs: the pothole-video survey of project 88d34769ee
("Thai road test, Non Din Daeng, Buriram", YouTube EP160 5:20-6:10, CC BY) and its first LingBot-Map clip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civil.analysis.raster import windowed_residual  # noqa: E402

PROJ = ROOT / "data" / "projects" / "88d34769ee" / "surveys"
VSID, CSID = "f04547f20d", "2c77cfa42f"     # video job, its clip 1 (0:00-0:40)
OUT = Path(__file__).with_name("fig") / "flow"
OUT.mkdir(parents=True, exist_ok=True)
INK, INK2, HIGH, MED, LOW, BLUE = "#1d2622", "#5e6a64", "#b42318", "#d9730d", "#c9a100", "#1e4f8f"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "savefig.dpi": 220,
                     "savefig.bbox": "tight", "savefig.pad_inches": 0.02})

vj = json.loads((PROJ / VSID / "video.json").read_text())
video = str(next((PROJ / VSID / "input").glob("*.mp4")))
det = vj["detections"]


def pixelate(rgb: np.ndarray, x0: int, y0: int, x1: int, y1: int, block: int = 10) -> None:
    roi = rgb[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // block), max(1, (y1 - y0) // block)), interpolation=cv2.INTER_AREA)
    rgb[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)


def plate_boxes(rgb: np.ndarray) -> list:
    """Bright, low-saturation, plate-shaped blobs in the lower part of a frame (Thai plates are white).
    A helper for the small clip frames; every result is still checked by eye in the rendered figure."""
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 2] > 170) & (hsv[..., 1] < 70)).astype(np.uint8)
    m[: int(h * 0.45)] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if 1.4 < bw / max(bh, 1) < 3.6 and 0.0002 * w * h < bw * bh < 0.02 * w * h and area > 0.5 * bw * bh:
            mx, my = max(2, bw // 4), max(2, bh // 3)
            out.append((max(0, x - mx), max(0, y - my), min(w, x + bw + mx), min(h, y + bh + my)))
    return out


def save_img(rgb: np.ndarray, name: str, w: int = 640) -> None:
    h = int(rgb.shape[0] * w / rgb.shape[1])
    cv2.imwrite(str(OUT / name), cv2.cvtColor(cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR))


# ---- detection: one frame, raw and with the detector's boxes ----------------------------------------------
by_frame: dict[int, list] = {}
for d in det:
    by_frame.setdefault(d["frame"], []).append(d)
frame = max((f for f, ds in by_frame.items() if 30 <= ds[0]["t"] <= 37), key=lambda f: (len(by_frame[f]), -abs(by_frame[f][0]["t"] - 33)))
cap = cv2.VideoCapture(video)
cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
ok, bgr = cap.read()
assert ok
rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
# the car ahead shows its number plate: pixelate it (PDPA treats registration numbers as identifying data).
# Region found by eye in this frame (1920 x 1080); checked again in the rendered panel.
PLATES = {825: [(585, 696, 750, 792)]}
plate_tpl = rgb[706:779, 600:731].copy() if frame in PLATES else None   # the plate itself, to find it in clip frames
for x0, y0, x1, y1 in PLATES.get(frame, []):
    roi = rgb[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 18), max(1, (y1 - y0) // 18)), interpolation=cv2.INTER_AREA)
    rgb[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
assert frame in PLATES, f"new frame {frame}: check it for number plates and add them to PLATES"
save_img(rgb, "d1_frame.png")
boxed = rgb.copy()
for d in by_frame[frame]:
    x0, y0, x1, y1 = map(int, d["box"])
    cv2.rectangle(boxed, (x0, y0), (x1, y1), (230, 40, 40), 6)
    cv2.putText(boxed, f"{d['conf']:.2f}", (x0 + 6, max(40, y0 - 12)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (230, 40, 40), 4)
save_img(boxed, "d2_boxes.png")
frame_t = by_frame[frame][0]["t"]

# ---- detection: hits over time -> events -> clips --------------------------------------------------------------
fig, ax = plt.subplots(figsize=(3.4, 2.0))
dur = vj["info"]["duration"] if isinstance(vj.get("info"), dict) and vj["info"].get("duration") else max(d["t"] for d in det) + 1
for i, w in enumerate(vj["windows"]):
    ax.axvspan(w["start"], w["end"], color=["#e8eef6", "#d6e1f0"][i % 2], zorder=0)
    ax.text((w["start"] + w["end"]) / 2, 0.98, f"clip {i + 1}", ha="center", va="top", color=BLUE, fontsize=9, fontweight="bold")
ax.scatter([d["t"] for d in det], [d["conf"] for d in det], s=9, color=HIGH, zorder=3)
for e in vj["events"]:
    ax.plot([e["t0"], max(e["t1"], e["t0"] + 0.5)], [0.36, 0.36], color=BLUE, lw=4, solid_capstyle="butt")
ax.axvline(frame_t, color=INK, lw=0.8, ls=":")
ax.set_ylim(0.33, 1.0), ax.set_xlim(0, dur)
ax.set_xlabel("time in the video (s)", fontsize=8), ax.set_ylabel("confidence", fontsize=8)
ax.tick_params(labelsize=7)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.savefig(OUT / "d3_timeline.png")
plt.close(fig)

# ---- LingBot-Map: clip frames (filmstrip) ----------------------------------------------------------------------
cs = json.loads((PROJ / CSID / "survey.json").read_text())
an = json.loads((PROJ / CSID / "analysis.json").read_text())
z = np.load(PROJ / CSID / "recon.npz")
pts, cols, poses = z["points"], z["colors"], z["poses"]
path = poses[:, :3, 3]
dv = path[-1, :2] - path[0, :2]
a = np.pi / 2 - np.arctan2(dv[1], dv[0])          # rotate so the drive runs up the page
R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
o = path[0, :2]
P = pts.copy()
P[:, :2] = (pts[:, :2] - o) @ R.T
pth = path.copy()
pth[:, :2] = (path[:, :2] - o) @ R.T
pots = [f for f in an["findings"] if f["type"] == "pothole" and f["metrics"].get("area_m2")]
for f in pots:
    f["_xy"] = (np.array([f["x"], f["y"]]) - o) @ R.T
yc = float(np.mean([f["_xy"][1] for f in pots]))
# second pass: align with the local driving direction around the potholes, centred on the camera path
loc = (pth[:, 1] > yc - 14) & (pth[:, 1] < yc + 8)
dl = path[loc][-1, :2] - path[loc][0, :2]
a = np.pi / 2 - np.arctan2(dl[1], dl[0])
R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
o = path[loc][0, :2]
P[:, :2] = (pts[:, :2] - o) @ R.T
pth[:, :2] = (path[:, :2] - o) @ R.T
for f in pots:
    f["_xy"] = (np.array([f["x"], f["y"]]) - o) @ R.T
yc = float(np.mean([f["_xy"][1] for f in pots]))
xc = float(np.median(pth[(pth[:, 1] > yc - 10) & (pth[:, 1] < yc + 6), 0]))
Y0, Y1, X0, X1 = yc - 9, yc + 5, xc - 3.6, xc + 3.6

frames = sorted((PROJ / CSID / "input" / "frames").glob("*.jpg"))
k_near = int(np.argmin(np.abs(pth[:, 1] - (yc - 6))))   # the camera ~6 m before the potholes
bj = json.loads((PROJ / CSID / "input" / "boxes.json").read_text())
geo = bj["geometry"]
with_boxes = sorted(int(k) for k in bj["boxes"])
# three clip frames that carry detector boxes, the last one nearest the camera position above
pick = sorted(with_boxes, key=lambda k: abs(k - k_near))[:3]
pick = sorted(pick)
strip = [cv2.cvtColor(cv2.imread(str(frames[k])), cv2.COLOR_BGR2RGB) for k in pick]
found = []
for im in strip:
    # the same car is ahead in every clip frame: find its plate by multi-scale template matching
    g = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
    best = (0.0, None)
    for sc in np.linspace(0.4, 1.6, 25):
        t = cv2.cvtColor(cv2.resize(plate_tpl, None, fx=sc, fy=sc), cv2.COLOR_RGB2GRAY)
        if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1]:
            continue
        r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        _, v, _, loc = cv2.minMaxLoc(r)
        if v > best[0]:
            best = (v, (loc[0], loc[1], loc[0] + t.shape[1], loc[1] + t.shape[0]))
    found.append((round(best[0], 2), best[1]))
    if best[1] and best[0] > 0.45:
        x0, y0, x1, y1 = best[1]
        mx, my = (x1 - x0) // 6, (y1 - y0) // 4
        pixelate(im, max(0, x0 - mx), max(0, y0 - my), x1 + mx, y1 + my, block=max(4, (x1 - x0) // 8))
print("plates blurred in clip frames (score, box):", found)
# the detector's boxes as LingBot-Map receives them (model pixels -> frame pixels)
for im, k in zip(strip, pick):
    for b in bj["boxes"][str(k)]:
        x0 = int(b[0] / geo["sx"]); x1 = int(b[2] / geo["sx"])
        y0 = int((b[1] + geo["crop_top"]) / geo["sy"] + geo["y0"]); y1 = int((b[3] + geo["crop_top"]) / geo["sy"] + geo["y0"])
        cv2.rectangle(im, (x0, y0), (x1, y1), (255, 46, 179), 8)
h = min(im.shape[0] for im in strip)
strip = [cv2.resize(im, (int(im.shape[1] * h / im.shape[0]), h)) for im in strip]
pad = np.full((h // 14, strip[0].shape[1], 3), 255, np.uint8)
film = np.vstack([strip[0], pad, strip[1], pad, strip[2]])
save_img(film, "l1_frames.png", w=360)

# ---- LingBot-Map: top views of the stretch with the potholes ---------------------------------------------------
keep = (P[:, 1] > Y0) & (P[:, 1] < Y1) & (P[:, 0] > X0) & (P[:, 0] < X1)
p, c = P[keep], cols[keep].astype(float)
c = c / 255.0 if c.max() > 1.5 else c
rng = np.random.default_rng(0)
if len(p) > 350_000:
    idx = rng.choice(len(p), 350_000, replace=False)
    p, c = p[idx], c[idx]
cell = 0.08
gx = np.floor((p[:, 0] - X0) / cell).astype(int)
gy = np.floor((p[:, 1] - Y0) / cell).astype(int)
grid = np.full((gy.max() + 1, gx.max() + 1), np.nan)
order = np.lexsort((gx, gy))
keys = gy[order] * (gx.max() + 1) + gx[order]
uniq, first = np.unique(keys, return_index=True)
for k, a0, a1 in zip(uniq, first, list(first[1:]) + [len(keys)]):
    grid[k // (gx.max() + 1), k % (gx.max() + 1)] = np.median(p[order[a0:a1], 2])
uu, vv = np.meshgrid(np.arange(grid.shape[0]) * cell, np.arange(grid.shape[1]) * cell, indexing="ij")
win = float((cs.get("params") or {}).get("analysis", {}).get("surface_window_m") or 8)
resid = np.asarray(windowed_residual(uu, vv, grid, np.isfinite(grid), win))
rel = resid[gy, gx]
ok = np.isfinite(rel)


def topview(name: str, colour, cmap=None, vmin=None, vmax=None, outlines=False, cbar=False, overlay=None):
    fig, ax = plt.subplots(figsize=(1.9, 3.1))
    sc = ax.scatter(p[ok, 0], p[ok, 1], s=0.35, c=colour, cmap=cmap, vmin=vmin, vmax=vmax, rasterized=True, linewidths=0)
    if overlay is not None and overlay.any():
        ax.scatter(p[ok & overlay, 0], p[ok & overlay, 1], s=0.35, c="#ff2eb3", alpha=0.35, rasterized=True, linewidths=0)
    seg = (pth[:, 1] > Y0) & (pth[:, 1] < Y1)
    ax.plot(pth[seg, 0], pth[seg, 1], color=INK, lw=1, ls="--")
    if outlines:
        for i, f in enumerate(sorted(pots, key=lambda f: f["_xy"][1])):
            col = {"high": HIGH, "medium": MED, "low": LOW}.get(f["severity"], INK)
            r = f["metrics"]["diameter_m"] / 2          # the measured diameter, drawn to scale
            ax.add_patch(plt.Circle(f["_xy"], r, fill=False, ec=col, lw=1.8))
            ax.text(f["_xy"][0] + r + 0.25, f["_xy"][1], str(i + 1), color=col, fontsize=8, fontweight="bold", va="center")
    ax.set_xlim(X0, X1), ax.set_ylim(Y0, Y1), ax.set_aspect("equal")
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if cbar:
        cb = fig.colorbar(sc, ax=ax, fraction=0.06, pad=0.02, ticks=[vmin, 0, vmax])
        cb.ax.tick_params(labelsize=6)
        cb.set_label("m", fontsize=7)
    fig.savefig(OUT / name)
    plt.close(fig)


topview("l2_colour.png", np.clip(c[ok], 0, 1))
# the points LingBot-Map labelled from the detector's boxes, over a grey photo
labels = z["labels"] if "labels" in z.files else None
lab_keep = (labels[keep] == 1) if labels is not None else np.zeros(int(keep.sum()), bool)
if len(lab_keep) != len(p):  # p was subsampled above: subsample the labels the same way
    lab_keep = lab_keep[idx] if len(lab_keep) > len(p) else lab_keep
grey = np.repeat((0.3 * c[:, :1] + 0.59 * c[:, 1:2] + 0.11 * c[:, 2:3]) * 0.55 + 0.35, 3, 1)
mag = np.where(lab_keep[:, None], np.array([[1.0, 0.18, 0.7]]), grey)
topview("l5_detector.png", np.clip(mag[ok], 0, 1))
topview("l3_height.png", rel[ok], cmap="RdYlBu", vmin=-0.12, vmax=0.12, cbar=True)
topview("l4_regions.png", rel[ok], cmap="RdYlBu", vmin=-0.12, vmax=0.12, outlines=True, overlay=lab_keep)

# ---- numbers used in the figure's labels ------------------------------------------------------------------------
rows = []
for i, f in enumerate(sorted(pots, key=lambda f: f["_xy"][1])):
    m = f["metrics"]
    rows.append({"n": i + 1, "id": f["id"], "severity": f["severity"], "area_m2": m.get("area_m2"),
                 "depth_m": m.get("depth_max_m"), "volume_m3": m.get("volume_m3"), "diameter_m": m.get("diameter_m"),
                 "circularity": m.get("circularity")})
facts = {"frame_t": frame_t, "boxes_in_frame": len(by_frame[frame]), "detections": len(det), "events": len(vj["events"]),
         "windows": [[w["start"], w["end"]] for w in vj["windows"]], "clip_frames": len(frames), "points": int(len(pts)),
         "stretch_m": [round(Y0, 1), round(Y1, 1)], "potholes": rows, "notes": cs.get("notes"), "detector_points_clip": int((z["labels"] == 1).sum()) if "labels" in z.files else 0, "box_frames": len(with_boxes),
         "sample_every_s": vj.get("detector", {}).get("every_s") if isinstance(vj.get("detector"), dict) else None,
         "detector": vj.get("detector")}
(OUT / "facts.json").write_text(json.dumps(facts, indent=1, default=str))
print(json.dumps(facts, indent=1, default=str)[:1800])

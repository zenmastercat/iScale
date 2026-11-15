"""Figures for the field test on a real road video (Rangoon Road clip, see the docx section 13).

Usage: uv run python docs/build/field_test.py <project_id> <video_survey_id> <clip_survey_id> <video.mp4>
Writes docs/build/fig/f10_*.png ... f12_*.png and docs/build/fig/field_test.json (numbers used in the docx).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("fig")
OUT.mkdir(exist_ok=True)
INK, INK2, RULE, ACTION, TINT = "#1d2622", "#5e6a64", "#d9dfdb", "#1e4f8f", "#e8eef6"
HIGH, MED, LOW = "#b42318", "#d9730d", "#c9a100"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "savefig.dpi": 200, "savefig.bbox": "tight"})

pid, vsid, csid, video = sys.argv[1:5]
base = ROOT / "data" / "projects" / pid / "surveys"
vj = json.loads((base / vsid / "video.json").read_text())
an = json.loads((base / csid / "analysis.json").read_text())
sv = json.loads((base / csid / "survey.json").read_text())
log = (base / csid / "work" / "decoder.log").read_text(errors="ignore")

# ---- 1. detection timeline ---------------------------------------------------------------
det = vj["detections"]
dur = vj["info"]["duration"]
fig, ax = plt.subplots(figsize=(10, 2.8))
ax.scatter([d["t"] for d in det], [d["conf"] for d in det], s=14, color=HIGH, alpha=0.7, label="pothole box (Roboflow)")
for w in vj["windows"]:
    ax.axvspan(w["start"], w["end"], color=TINT, zorder=0, label="clip sent to LingBot-Map")
for e in vj["windows"][0]["events"]:
    ax.hlines(0.42, e["t0"], e["t1"], color=ACTION, lw=4)
ax.text(0.2, 0.395, "confirmed events", fontsize=8, color=ACTION, va="top")
ax.axhline(0.45, color=INK2, ls="--", lw=0.8)
ax.text(dur, 0.455, "threshold 0.45", fontsize=8, color=INK2, ha="right")
ax.set_xlim(0, dur), ax.set_ylim(0.36, 0.92)
ax.set_xlabel("time in the video (s)"), ax.set_ylabel("confidence")
ax.legend(frameon=False, loc="lower right", fontsize=8)
fig.savefig(OUT / "f10_field_timeline.png")
plt.close(fig)

# ---- 2. sample detections ----------------------------------------------------------------
cap = cv2.VideoCapture(video)
picks = []
for t in (3.0, 12.0, 20.0, 36.0):
    near = min(det, key=lambda d: abs(d["t"] - t))
    same = [d for d in det if d["frame"] == near["frame"]]
    cap.set(cv2.CAP_PROP_POS_FRAMES, near["frame"])
    ok, img = cap.read()
    for d in same:
        x0, y0, x1, y1 = map(int, d["box"])
        cv2.rectangle(img, (x0, y0), (x1, y1), (24, 35, 180), 3)
        cv2.putText(img, f"{d['conf']:.2f}", (x0 + 4, max(18, y0 + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (24, 35, 180), 2)
    picks.append((near["t"], cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
fig, axs = plt.subplots(1, 4, figsize=(12, 2.2))
for a, (t, im) in zip(axs, picks):
    a.imshow(im), a.axis("off"), a.set_title(f"t = {t:.1f} s", fontsize=9, color=INK2)
fig.savefig(OUT / "f11_field_detections.png")
plt.close(fig)

# ---- 3. top-down 3D with findings ----------------------------------------------------------
z = np.load(base / csid / "recon.npz", allow_pickle=False)
pts, cols = z["points"], z["colors"]
rng = np.random.default_rng(0)
idx = rng.choice(len(pts), size=min(400_000, len(pts)), replace=False)
p, c = pts[idx], cols[idx].astype(float)
c = c / 255.0 if c.max() > 1.5 else c
path = np.array(an["path"])
# The survey may have been turned onto a street afterwards (replace_field_test.py); draw it in the walk frame.
_hd = np.radians(float((sv.get("params") or {}).get("placed_heading_deg", 0.0)))
_r = np.array([[np.cos(_hd), -np.sin(_hd)], [np.sin(_hd), np.cos(_hd)]])
p = p.copy(); p[:, :2] = p[:, :2] @ _r.T
path = path.copy(); path[:, :2] = path[:, :2] @ _r.T
walk_xy = {f["id"]: tuple(_r @ np.array([f["x"], f["y"]])) for f in an["findings"]}
keep = (np.abs(p[:, 0] - np.median(path[:, 0])) < 6) & (p[:, 1] > path[:, 1].min() - 2) & (p[:, 1] < path[:, 1].max() + 4)
p, c = p[keep], c[keep]
ground = np.percentile(p[:, 2], 50)
# height above the local road surface: median grid along the walk, 8 m windowed robust fit (as the analysis does)
from civil.analysis.raster import windowed_residual  # noqa: E402

cell = 0.1
gx = np.floor((p[:, 0] - p[:, 0].min()) / cell).astype(int)
gy = np.floor((p[:, 1] - p[:, 1].min()) / cell).astype(int)
grid = np.full((gy.max() + 1, gx.max() + 1), np.nan)
order = np.lexsort((gx, gy))
keys = gy[order] * (gx.max() + 1) + gx[order]
uniq, first = np.unique(keys, return_index=True)
for k, a0, a1 in zip(uniq, first, list(first[1:]) + [len(keys)]):
    grid[k // (gx.max() + 1), k % (gx.max() + 1)] = np.median(p[order[a0:a1], 2])
uu, vv = np.meshgrid(np.arange(grid.shape[0]) * cell, np.arange(grid.shape[1]) * cell, indexing="ij")
win = float((sv.get("params") or {}).get("analysis", {}).get("surface_window_m") or 8)
resid = np.asarray(windowed_residual(uu, vv, grid, np.isfinite(grid), win))
rel = resid[gy, gx]
fig, (a, b, cax) = plt.subplots(1, 3, figsize=(12, 7.4), sharey=True)
a.scatter(p[:, 0], p[:, 1], s=0.15, c=np.clip(c, 0, 1), rasterized=True)
a.set_title("Colour (top view)", fontsize=10)
h1 = b.scatter(p[:, 0], p[:, 1], s=0.15, c=p[:, 2] - ground, cmap="RdYlBu", vmin=-0.25, vmax=0.25, rasterized=True)
b.set_title("Raw height: the reconstruction bends", fontsize=10)
fig.colorbar(h1, ax=b, fraction=0.05, pad=0.02, label="m")
h2 = cax.scatter(p[:, 0], p[:, 1], s=0.15, c=rel, cmap="RdYlBu", vmin=-0.15, vmax=0.15, rasterized=True)
cax.set_title(f"Height above the local road ({win:.0f} m windows)", fontsize=10)
fig.colorbar(h2, ax=cax, fraction=0.05, pad=0.02, label="m")
mark = {"pothole": ("o", HIGH), "heave": ("^", MED), "surface_roughness": ("s", LOW), "fire_hydrant": ("x", INK)}
for ax_ in (a, b, cax):
    ax_.plot(path[:, 0], path[:, 1], color=INK, lw=1, ls="--")
    ax_.set_aspect("equal"), ax_.set_xlabel("across (m)")
for f in an["findings"]:
    m, col = mark.get(f["type"], ("o", INK))
    cax.plot(*walk_xy[f["id"]], m, ms=9, mfc="none", mec=col, mew=2)
a.set_ylabel("along the walk (m)")
present = {f["type"] for f in an["findings"]}
handles = [plt.Line2D([], [], marker=m, ls="", mfc="none", mec=col, mew=2, label=k.replace("_", " ")) for k, (m, col) in mark.items() if k in present]
handles.append(plt.Line2D([], [], color=INK, ls="--", label="camera path"))
cax.legend(handles=handles, frameon=True, fontsize=8, loc="upper left")
fig.savefig(OUT / "f12_field_topdown.png")
plt.close(fig)

# ---- numbers for the document -------------------------------------------------------------
infer = next((ln for ln in log.splitlines() if "Inference done" in ln), "")
seg = an["segments"][0]
num = {
    "duration_s": dur, "fps": vj["info"]["fps"], "size": f"{vj['info']['width']}x{vj['info']['height']}",
    "samples": len({d["frame"] for d in det}) and vj.get("samples_count", None),
    "detections": len(det), "frames_with_box": len({d["frame"] for d in det}),
    "conf_min": min(d["conf"] for d in det), "conf_median": float(np.median([d["conf"] for d in det])), "conf_max": max(d["conf"] for d in det),
    "events": [[e["t0"], e["t1"], e["hits"]] for w in vj["windows"] for e in w["events"]],
    "windows": [[w["start"], w["end"]] for w in vj["windows"]],
    "lingbot_frames": len(z["times"]), "lingbot": infer.strip(), "points": int(len(pts)),
    "align_notes": sv.get("notes"), "analysis_s": an.get("seconds"),
    "path_m": float(np.sum(np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1))),
    "segment": {"id": seg["id"], "length_m": seg["length_m"], "condition": seg.get("condition"), "rating": seg.get("rating")},
    "findings": [{"id": f["id"], "type": f["type"], "severity": f.get("severity"), "evidence": f.get("evidence"), "lat": f.get("lat"), "lon": f.get("lon"),
                  "metrics": f.get("metrics")} for f in an["findings"]],
    "counts": Counter(f["type"] for f in an["findings"]),
}
(OUT / "field_test.json").write_text(json.dumps(num, indent=1, default=str))
print(json.dumps({k: num[k] for k in ("detections", "frames_with_box", "events", "windows", "lingbot", "points", "path_m", "segment", "counts")}, default=str))

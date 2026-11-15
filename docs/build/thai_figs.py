"""Figures and numbers for the Thai field test (docx section 12.6).

Usage: uv run python docs/build/thai_figs.py <isan_project> <isan_video_survey> <isan_video.mp4> <ep160_project> <ep160_video_survey>
Writes fig/f18_thai_isan.png (detections and the four 3D clips, with sample frames) and
fig/thai_test.json (per-clip results used in the docx).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("fig")
INK, INK2, ACTION, TINT = "#1d2622", "#5e6a64", "#1e4f8f", "#e8eef6"
HIGH = "#b42318"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "savefig.dpi": 200, "savefig.bbox": "tight"})


def summary(pid: str, vsid: str) -> dict:
    base = ROOT / "data" / "projects" / pid / "surveys"
    v = json.loads((base / vsid / "video.json").read_text())
    clips = []
    for c in v["children"]:
        d = base / c["survey_id"]
        s = json.loads((d / "survey.json").read_text())
        a = json.loads((d / "analysis.json").read_text())
        pots = [f for f in a["findings"] if f["type"] == "pothole"]
        meas = [f for f in pots if f["metrics"].get("depth_max_m") is not None]
        dm = [f["metrics"]["depth_max_m"] for f in meas]
        dia = [f["metrics"]["diameter_m"] for f in meas]
        scale = next((n for n in s.get("notes", []) if n.startswith("scale")), "")
        widths = [sg["metrics"].get("road_width_m") for sg in a["segments"]]
        cond = [sg.get("condition") for sg in a["segments"]]
        clips.append({
            "id": c["survey_id"], "start": s["params"]["clip_start"], "frames": c["frames"],
            "end": next(w["end"] for w in v["windows"] if w["index"] == s["params"]["window"]),
            "scale": float(scale.split("factor ")[1].rstrip(")")) if "factor" in scale else None,
            "length_m": s["stats"].get("length_m"), "potholes": len(pots), "measured": len(meas),
            "detector_only": sum(f["source"] == "detector" for f in pots),
            "unmeasurable_depth": sum(bool(f["metrics"].get("depth_unreliable")) for f in pots),
            "severity": {k: sum(f["severity"] == k for f in pots) for k in ("high", "medium", "low")},
            "depth_p50_cm": round(float(np.median(dm)) * 100, 1) if dm else None,
            "depth_p90_cm": round(float(np.percentile(dm, 90)) * 100, 1) if dm else None,
            "depth_max_cm": round(float(max(dm)) * 100, 1) if dm else None,
            "across_p50_m": round(float(np.median(dia)), 2) if dia else None,
            "road_width_m": widths, "condition": cond,
            "scored_segments": sum(x is not None for x in cond), "segments": len(cond),
        })
    return {"duration_s": round(v["info"]["duration"], 1), "samples": v["samples"], "detections": len(v["detections"]),
            "events": len(v["events"]), "windows": [[w["start"], w["end"]] for w in v["windows"]], "clips": clips,
            "_v": v}


def isan_figure(s: dict, video: str) -> None:
    v = s["_v"]
    det = v["detections"]
    fig = plt.figure(figsize=(11, 4.6))
    ax = fig.add_axes([0.06, 0.58, 0.9, 0.36])
    ax.scatter([d["t"] for d in det], [d["conf"] for d in det], s=12, color=HIGH, alpha=0.7, label="pothole box (Roboflow)")
    for i, (a, b) in enumerate(s["windows"]):
        ax.axvspan(a, b, color=TINT if i % 2 == 0 else "#d6e2f2", zorder=0)
        c = s["clips"][i]
        ax.text((a + b) / 2, 0.93, f"clip {i + 1}: {c['measured']}/{c['potholes']} measured\nscale x{c['scale']:.1f}",
                ha="center", va="top", fontsize=8, color=ACTION)
    for e in v["events"]:
        ax.hlines(0.42, e["t0"], e["t1"], color=ACTION, lw=4)
    ax.axhline(0.45, color=INK2, ls="--", lw=0.8)
    ax.set_xlim(0, s["duration_s"]), ax.set_ylim(0.36, 0.97)
    ax.set_xlabel("time in the video (s)"), ax.set_ylabel("confidence")
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=8, ncol=2)
    ax.text(0.5, 0.39, "blue bars: confirmed events (2+ hits within 1 s)", fontsize=8, color=ACTION, va="top")
    cap = cv2.VideoCapture(video)
    for k, t in enumerate((12.0, 36.0, 58.0, 110.0)):
        near = min(det, key=lambda d: abs(d["t"] - t))
        same = [d for d in det if d["frame"] == near["frame"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, near["frame"])
        ok, img = cap.read()
        if not ok:
            continue
        for d in same:
            x0, y0, x1, y1 = map(int, d["box"])
            cv2.rectangle(img, (x0, y0), (x1, y1), (24, 35, 180), 4)
        a2 = fig.add_axes([0.06 + k * 0.228, 0.0, 0.215, 0.44])
        a2.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)), a2.axis("off")
        a2.set_title(f"t = {near['t']:.0f} s" + (" (water in holes)" if 50 < t < 70 else ""), fontsize=9, color=INK2)
    fig.savefig(OUT / "f18_thai_isan.png")
    plt.close(fig)


if __name__ == "__main__":
    ip, iv, video, ep, ev = sys.argv[1:6]
    isan, ep160 = summary(ip, iv), summary(ep, ev)
    isan_figure(isan, video)
    out = {"isan": {k: v for k, v in isan.items() if k != "_v"}, "ep160": {k: v for k, v in ep160.items() if k != "_v"}}
    (OUT / "thai_test.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: {kk: vv for kk, vv in d.items() if kk != "clips"} for k, d in out.items()}))

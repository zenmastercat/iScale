"""Video job: detect potholes in a drive video, then reconstruct only the windows around them.

    video ──sample──▶ detector ──hits──▶ events ──±10 s──▶ windows ──▶ one clip survey each
                                                                       (frames → LingBot → 3D → analysis)

Each detection also gets a bird's-eye (perspective-transform) footprint estimate and
evidence images, so it is useful on its own before 3D exists.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np

from .. import store
from ..config import CONFIG_DIR
from .detector import make_detector
from .frames import band, box_to_model, extract_clip, model_geometry, sample, video_info
from .perspective import RoadPlane
from .windows import events, windows

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def video_config() -> dict:
    return json.loads((CONFIG_DIR / "video.json").read_text())


def _find_inputs(input_dir: Path) -> tuple[Path, Path | None]:
    vids = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in VIDEO_EXT)
    if not vids:
        raise ValueError("upload a drive video (.mp4, .mov, ...)")
    gps = sorted(p for p in input_dir.iterdir() if p.suffix.lower() == ".csv")
    return vids[0], (gps[0] if gps else None)


def _draw(img: np.ndarray, boxes: list) -> np.ndarray:
    import cv2

    out = img.copy()
    for b in boxes:
        p0, p1 = (int(b.x0), int(b.y0)), (int(b.x1), int(b.y1))
        cv2.rectangle(out, p0, p1, (32, 176, 255), 2)
        cv2.putText(out, f"{b.conf:.2f}", (p0[0], max(14, p0[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (32, 176, 255), 2)
    return out


def run_video_job(pid: str, sid: str, progress) -> dict:
    """Runs inside the survey worker. Returns stats; writes video.json in the survey folder."""
    import cv2

    cfg = video_config()
    sv = store.get_survey(pid, sid)
    over = sv.get("params", {}).get("video") or {}
    for k in ("detector", "window", "frames", "lingbot", "scale"):
        if isinstance(over.get(k), dict):
            cfg[k] = {**cfg[k], **over[k]}
    d = store.survey_dir(pid, sid)
    video, gps = _find_inputs(d / "input")
    info = video_info(video)
    ev_dir = d / "work" / "detections"
    ev_dir.mkdir(parents=True, exist_ok=True)
    plane = RoadPlane(cfg["perspective"], info["width"], info["height"])

    # 1. detect ------------------------------------------------------------------
    det_cfg = cfg["detector"]
    detector = make_detector(det_cfg)
    step = 1.0 / float(det_cfg.get("sample_fps", 3))
    boxes = []
    batch: list = []
    n_samples = 0
    for item in sample(video, step):
        batch.append(item)
        n_samples += 1
        if len(batch) >= 24:
            boxes += detector.detect(batch)
            progress(f"detecting {item[1]:.0f}/{info['duration']:.0f} s")
            batch = []
    if batch:
        boxes += detector.detect(batch)
    hits = sorted({b.t for b in boxes})
    evts = events(hits, int(det_cfg.get("min_hits", 2)), float(det_cfg.get("hit_gap_s", 1.0)))
    wins = windows(evts, info["duration"], **{k: float(cfg["window"][k]) for k in ("before_s", "after_s", "merge_gap_s")})

    # evidence: one annotated frame + bird's-eye view per detected sample time
    by_t: dict[float, list] = {}
    for b in boxes:
        by_t.setdefault(b.t, []).append(b)
    dets = []
    if by_t:
        frames_needed = {round(t, 3) for t in by_t}
        for idx, t, img in sample(video, step):
            if round(t, 3) not in frames_needed:
                continue
            bs = by_t[t]
            name = f"t{t:08.2f}".replace(".", "_")
            cv2.imwrite(str(ev_dir / f"{name}.jpg"), _draw(img, bs), [cv2.IMWRITE_JPEG_QUALITY, 85])
            cv2.imwrite(str(ev_dir / f"{name}_bev.jpg"), plane.bev(_draw(img, bs)), [cv2.IMWRITE_JPEG_QUALITY, 85])
            for b in bs:
                dets.append({**b.to_dict(), **plane.measure_box((b.x0, b.y0, b.x1, b.y1)), "image": f"{name}.jpg",
                             "bev_image": f"{name}_bev.jpg",
                             "window": next((w["index"] for w in wins if w["start"] <= t <= w["end"]), None)})
    rec = {"video": video.name, "info": info, "detector": {k: v for k, v in det_cfg.items() if k != "api_key_env"},
           "samples": n_samples, "detections": dets, "events": evts, "windows": wins, "children": [],
           "perspective_calibrated": plane.calibrated, "created": time.time()}
    (d / "video.json").write_text(json.dumps(rec, indent=1))

    # 2. one clip survey per window -----------------------------------------------
    from ..pipeline import run_survey

    fr = cfg["frames"]
    rows = band(fr, info["width"], info["height"])
    geo = model_geometry(info["width"], rows)
    lb_fps = float(fr.get("fps", 10))
    for w in wins:
        progress(f"window {w['index'] + 1}/{len(wins)}: extracting frames")
        name = f"{sv['name']}, clip {w['index'] + 1} ({_mmss(w['start'])} to {_mmss(w['end'])})"
        child = store.create_survey(pid, name, "lingbot_clip", {
            "parent": sid, "window": w["index"],
            "camera_height_m": float(sv.get("params", {}).get("camera_height_m") or cfg["scale"].get("camera_height_m", 1.4)),
            "clip_start": w["start"], "clip_fps": lb_fps,
            "analysis": {k: v for k, v in (cfg.get("analysis") or {}).items() if not k.startswith("_")}})
        cdir = store.survey_dir(pid, child["id"]) / "input"
        times = extract_clip(video, w["start"], w["end"], lb_fps, rows, cdir / "frames")
        # detector boxes -> clip frame index, in LingBot model-image pixels
        tarr = np.array(times)
        mboxes: dict[int, list] = {}
        for b in boxes:
            if not (w["start"] <= b.t <= w["end"]) or not len(tarr):
                continue
            k = int(np.argmin(np.abs(tarr - b.t)))
            if abs(tarr[k] - b.t) <= 0.6 / lb_fps:
                mboxes.setdefault(k, []).append(box_to_model([b.x0, b.y0, b.x1, b.y1], geo))
        (cdir / "boxes.json").write_text(json.dumps({"boxes": {str(k): v for k, v in mboxes.items()},
                                                     "times": times, "geometry": geo}))
        if gps is not None:
            shutil.copy2(gps, cdir / "gps.csv")
        rec["children"].append({"survey_id": child["id"], "window": w["index"], "frames": len(times),
                                "detection_frames": len(mboxes)})
        (d / "video.json").write_text(json.dumps(rec, indent=1))
        progress(f"window {w['index'] + 1}/{len(wins)}: LingBot 3D")
        run_survey(pid, child["id"])
    return {"video_s": round(info["duration"], 1), "samples": n_samples, "detections": len(dets),
            "events": len(evts), "windows": len(wins), "clips": [c["survey_id"] for c in rec["children"]]}


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"

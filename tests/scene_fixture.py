"""A synthetic LingBot clip: a straight road seen by a dash camera, for scene-scale tests and the UI check.

Everything LingBot-Map would leave behind is made here, so the real code path runs from there on:
input/frames/*.jpg (960 x 540 frame files), input/boxes.json (frame -> model geometry and detector
boxes), work/lingbot_raw/frame_*.npz (extrinsic, intrinsic, depth, depth_conf, images in model units
= metres / MODEL_UNIT), then LingbotClipDecoder.convert -> pipeline.finish (align with a wrong camera
height guess, analyse).

The scene's sizes are this fixture's own, not standard sizes: two solid edge lines EDGE_GAP_M apart
(centre to centre), a dashed centre line, and one pothole POTHOLE = (x, y, radius, depth) in metres.

    python tests/scene_fixture.py <project id>      # add a video job + clip to a project in $CIVIL_DATA_DIR
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODEL_UNIT = 2.4          # metres per LingBot model unit (unknown to the app)
CAM_H = 1.9               # true camera height, metres (the app guesses 1.4 m)
GUESS_H = 1.4
PITCH = math.radians(10)
N_FRAMES, STEP_M, FPS = 30, 0.55, 10.0
FW, FH = 960, 540                                   # stored frame files
MW, MH, F_MODEL = 518, 280, 400.0                   # LingBot model image
GEO = {"sx": MW / FW, "sy": MH / FH, "y0": 0, "crop_top": 0, "model_w": MW, "model_h": MH}
EDGE_GAP_M = 7.0          # centre-to-centre distance of the two edge lines (this fixture's road)
LINE_W = 0.15
POTHOLE = (1.6, 10.5, 0.45, 0.08)
MAX_DEPTH_M = 40.0
K_MODEL = np.array([[F_MODEL, 0, MW / 2], [0, F_MODEL, MH / 2], [0, 0, 1.0]])


def c2w(i: int) -> np.ndarray:
    z = np.array([0.0, math.cos(PITCH), -math.sin(PITCH)])
    x = np.array([1.0, 0.0, 0.0])
    m = np.eye(4)
    m[:3, :3] = np.stack([x, np.cross(z, x), z], 1)
    m[:3, 3] = [-1.75, STEP_M * i, CAM_H]           # driving in the right-hand lane
    return m


def surface_z(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    px, py, r, d = POTHOLE
    rr = ((x - px) ** 2 + (y - py) ** 2) / r**2
    return np.where(rr < 1, -d * (1 - rr), 0.0)


def colour(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Asphalt with a little texture, white lines, a darker pothole, grass beyond the road."""
    h = np.sin(x * 37.1 + y * 11.7) * np.cos(x * 5.3 - y * 23.9) + 0.5 * np.sin(x * 91.0 + y * 67.0)
    base = 78 + 10 * h
    rgb = np.stack([base, base, base + 4], -1)
    half = EDGE_GAP_M / 2
    edge = (np.abs(np.abs(x) - half) < LINE_W / 2)
    dash = (np.abs(x) < LINE_W / 2) & ((y % 9.0) < 3.0)
    white = edge | dash
    rgb[white] = [228, 228, 222]
    grass = np.abs(x) > half + 0.6
    rgb[grass] = np.stack([60 + 8 * h, 105 + 10 * h, 50 + 6 * h], -1)[grass]
    hole = z < -0.003
    rgb[hole] = np.stack([52 + 6 * h, 48 + 6 * h, 44 + 6 * h], -1)[hole]
    return np.clip(rgb, 0, 255)


def ray_ground(cam: np.ndarray, d_cam: np.ndarray):
    """z-depth (metres) where camera rays d_cam (z = 1) meet the road surface; nan above the horizon."""
    dw = d_cam @ cam[:3, :3].T
    o = cam[:3, 3]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dw[..., 2] < -1e-6, -o[2] / dw[..., 2], np.nan)
        for _ in range(4):  # step onto the pothole's bowl
            x, y = o[0] + t * dw[..., 0], o[1] + t * dw[..., 1]
            t = np.where(np.isfinite(t), (surface_z(x, y) - o[2]) / dw[..., 2], np.nan)
    t = np.where((t > 0) & (t * np.linalg.norm(dw, axis=-1) < MAX_DEPTH_M * 1.5), t, np.nan)
    p = o + t[..., None] * dw
    return t, p


def render(cam: np.ndarray, w: int, h: int, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vv, uu = np.mgrid[0:h, 0:w]
    d = np.stack([(uu + 0.5 - k[0, 2]) / k[0, 0], (vv + 0.5 - k[1, 2]) / k[1, 1], np.ones((h, w))], -1)
    t, p = ray_ground(cam, d)
    ok = np.isfinite(t)
    img = np.zeros((h, w, 3))
    sky = np.clip(np.stack([200 - 0.1 * vv, 220 - 0.08 * vv, 245 + 0 * vv], -1), 0, 255)
    img[~ok] = sky[~ok]
    img[ok] = colour(p[ok][:, 0], p[ok][:, 1], p[ok][:, 2])
    return img.astype(np.uint8), np.where(ok, t, 0.0)


def frame_k() -> np.ndarray:
    """Intrinsics of the stored 960 x 540 frame (the model's, undone through GEO)."""
    k = K_MODEL.copy()
    k[0, 0] /= GEO["sx"]
    k[0, 2] /= GEO["sx"]
    k[1, 1] /= GEO["sy"]
    k[1, 2] = (k[1, 2] + GEO["crop_top"]) / GEO["sy"]
    return k


def project(cam: np.ndarray, k: np.ndarray, p: np.ndarray) -> np.ndarray:
    w2c = np.linalg.inv(cam)
    pc = (np.atleast_2d(p) @ w2c[:3, :3].T) + w2c[:3, 3]
    return np.c_[k[0, 0] * pc[:, 0] / pc[:, 2] + k[0, 2], k[1, 1] * pc[:, 1] / pc[:, 2] + k[1, 2]]


def edge_taps(frame: int, y_m: float) -> list[list[float]]:
    """Frame pixels of the two edge lines' centres at distance y_m along the road (metres)."""
    half = EDGE_GAP_M / 2
    return project(c2w(frame), frame_k(), np.array([[-half, y_m, 0.0], [half, y_m, 0.0]])).round(2).tolist()


def write_clip(sdir: Path, noise: float = 0.004, seed: int = 0) -> None:
    import cv2

    rng = np.random.default_rng(seed)
    frames = sdir / "input" / "frames"
    raw = sdir / "work" / "lingbot_raw"
    frames.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    kf = frame_k()
    px, py, r, _ = POTHOLE
    boxes = {}
    for i in range(N_FRAMES):
        cam = c2w(i)
        img, _ = render(cam, FW, FH, kf)
        cv2.imwrite(str(frames / f"{i:06d}.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
        mimg, depth = render(cam, MW, MH, K_MODEL)
        depth = np.where(depth * 1.0 < MAX_DEPTH_M, depth, 0.0)
        depth = np.where(depth > 0, depth * (1 + rng.normal(0, noise, depth.shape)), 0.0) / MODEL_UNIT
        cm = cam.copy()
        cm[:3, 3] /= MODEL_UNIT
        w2c = np.linalg.inv(cm)[:3, :4]
        np.savez(raw / f"frame_{i:06d}.npz", extrinsic=w2c[None], intrinsic=K_MODEL[None], depth=depth[None, ..., None],
                 depth_conf=np.full((1, MH, MW), 2.0, np.float32), images=(mimg.transpose(2, 0, 1)[None] / 255.0).astype(np.float32))
        # the detector's box around the pothole, in model pixels, while it is 3-12 m ahead
        ahead = py - cam[1, 3]
        if 3 < ahead < 12:
            ring = np.array([[px + r * math.cos(a), py + r * math.sin(a), 0.0] for a in np.linspace(0, 2 * math.pi, 16)])
            uv = project(cam, K_MODEL, ring)
            boxes[str(i)] = [[float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max())]]
    times = [i / FPS for i in range(N_FRAMES)]
    (sdir / "input" / "boxes.json").write_text(json.dumps({"boxes": boxes, "times": times, "geometry": GEO}))


def make_clip(pid: str, name: str = "Synthetic clip", parent: str | None = None, noise: float = 0.004) -> str:
    """A done lingbot_clip survey built from the synthetic predictions. Returns its id."""
    from civil import pipeline, store
    from civil.decoders.lingbot_clip import LingbotClipDecoder

    params = {"camera_height_m": GUESS_H, "clip_start": 0.0, "clip_fps": FPS, "window": 0,
              **({"parent": parent} if parent else {})}
    sv = store.create_survey(pid, name, "lingbot_clip", params)
    sid = sv["id"]
    store.update_survey(pid, sid, status="running", stage="synthetic clip")
    sdir = store.survey_dir(pid, sid)
    write_clip(sdir, noise=noise)
    rec = LingbotClipDecoder().convert(sdir / "work" / "lingbot_raw", sdir / "input", sdir / "work", params)
    pipeline.finish(pid, sid, rec, params, store.get_project(pid))
    return sid


def add_video_job(pid: str) -> tuple[str, str]:
    """A finished video job whose one clip is the synthetic clip (so the Video view lists it)."""
    from civil import store

    job = store.create_survey(pid, "Synthetic drive", "pothole_video", {})
    jid = job["id"]
    cid = make_clip(pid, "Synthetic drive, clip 1 (0:00 to 0:03)", parent=jid)
    dur = N_FRAMES / FPS
    rec = {"video": "synthetic.mp4", "info": {"fps": 30.0, "frames": int(dur * 30), "width": FW, "height": FH, "duration": dur},
           "detector": {"kind": "synthetic"}, "samples": int(dur * 3), "detections": [], "events": [],
           "windows": [{"index": 0, "start": 0.0, "end": dur}],
           "children": [{"survey_id": cid, "window": 0, "frames": N_FRAMES, "detection_frames": 0}],
           "perspective_calibrated": False, "created": time.time()}
    (store.survey_dir(pid, jid) / "video.json").write_text(json.dumps(rec, indent=1))
    store.update_survey(pid, jid, status="done", stage="", kind="video",
                        stats={"video_s": dur, "samples": 0, "detections": 0, "events": 0, "windows": 1, "clips": [cid]})
    return jid, cid


if __name__ == "__main__":
    j, c = add_video_job(sys.argv[1])
    print(json.dumps({"job": j, "clip": c}))

"""Video reading, sampling and the frame band given to LingBot."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def video_info(path: Path) -> dict:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {path.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": float(fps), "frames": n, "width": w, "height": h, "duration": n / fps if fps else 0.0}


def sample(path: Path, every_s: float, start: float = 0.0, end: float | None = None):
    """Yield (frame_index, t, BGR image) every `every_s` seconds between start and end."""
    import cv2

    info = video_info(path)
    fps = info["fps"]
    end = info["duration"] if end is None else min(end, info["duration"])
    cap = cv2.VideoCapture(str(path))
    try:
        targets = np.arange(start, end, every_s)
        want = sorted({int(round(t * fps)) for t in targets})
        if not want:
            return
        cap.set(cv2.CAP_PROP_POS_FRAMES, want[0])
        i = want[0]
        wi = 0
        while wi < len(want):
            ok, img = cap.read()
            if not ok:
                break
            if i == want[wi]:
                yield i, i / fps, img
                wi += 1
            i += 1
    finally:
        cap.release()


def band(cfg: dict, w: int, h: int) -> tuple[int, int]:
    """Rows [y0, y1) of the frame given to LingBot.

    LingBot's 'crop' preprocessing resizes to 518 px wide and centre-crops anything
    taller than square. For portrait video that would keep the middle of the frame
    and drop the road at the bottom, so for portrait video we choose a square band
    ourselves, centred low in the frame (auto_portrait_center).
    """
    b = cfg.get("band", "auto")
    if isinstance(b, (list, tuple)) and len(b) == 2:
        y0, y1 = int(b[0] * h), int(b[1] * h)
    elif h > w:
        c = float(cfg.get("auto_portrait_center", 0.62)) * h
        y0 = int(np.clip(c - w / 2, 0, h - w))
        y1 = y0 + w
    else:
        y0, y1 = 0, h
    return max(0, y0), min(h, y1)


def model_geometry(w: int, band_rows: tuple[int, int], image_size: int = 518, patch: int = 14) -> dict:
    """How a band-cropped frame maps onto LingBot's model image ('crop' mode).

    new_w = 518; new_h = round(bh * 518 / w / 14) * 14; if new_h > 518 the centre
    518 rows are kept.  Returns scale and offsets so x_model = x * sx,
    y_model = (y - y0) * sy - crop_top.
    """
    y0, y1 = band_rows
    bh = y1 - y0
    new_w = image_size
    new_h = int(round(bh * (new_w / w) / patch) * patch)
    crop_top = (new_h - image_size) // 2 if new_h > image_size else 0
    return {"sx": new_w / w, "sy": new_h / bh, "y0": y0, "crop_top": crop_top,
            "model_w": new_w, "model_h": min(new_h, image_size)}


def box_to_model(box: list[float], geo: dict) -> list[float]:
    x0, y0, x1, y1 = box
    return [x0 * geo["sx"], (y0 - geo["y0"]) * geo["sy"] - geo["crop_top"],
            x1 * geo["sx"], (y1 - geo["y0"]) * geo["sy"] - geo["crop_top"]]


def extract_clip(path: Path, start: float, end: float, fps: float, rows: tuple[int, int], out_dir: Path) -> list[float]:
    """Write band-cropped JPEG frames for [start, end) at `fps`; returns their times."""
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    times = []
    for k, (_, t, img) in enumerate(sample(path, 1.0 / fps, start, end)):
        cv2.imwrite(str(out_dir / f"{k:06d}.jpg"), img[rows[0]:rows[1]], [cv2.IMWRITE_JPEG_QUALITY, 92])
        times.append(t)
    return times

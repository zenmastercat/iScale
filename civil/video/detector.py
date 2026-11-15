"""Pothole detectors that scan a video.

RoboflowDetector calls the hosted Roboflow model with the user's snippet:

    InferenceHTTPClient(api_url=..., api_key=...).configure(
        InferenceConfiguration(api_key_transport="header"))
    client.infer(image, model_id="pothole-all-conditions-n6tqz/1")

Sampled frames are sent to Roboflow's servers (serverless inference, uses account
credits). The API key is read from an environment variable, never from a file in the
project.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np


@dataclass
class Box:
    t: float  # seconds from video start
    frame: int  # index in the source video
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float
    label: str

    def to_dict(self) -> dict:
        return {"t": round(self.t, 3), "frame": self.frame, "box": [round(v, 1) for v in (self.x0, self.y0, self.x1, self.y1)],
                "conf": round(self.conf, 3), "label": self.label}


class Detector:
    name = "base"

    def detect(self, frames: list[tuple[int, float, np.ndarray]]) -> list[Box]:
        raise NotImplementedError


class RoboflowDetector(Detector):
    name = "roboflow"

    def __init__(self, cfg: dict):
        from inference_sdk import InferenceConfiguration, InferenceHTTPClient

        key = os.environ.get(cfg.get("api_key_env", "ROBOFLOW_API_KEY"), "")
        if not key:
            raise RuntimeError(f"{cfg.get('api_key_env', 'ROBOFLOW_API_KEY')} is not set")
        self.model_id = cfg["model_id"]
        self.conf = float(cfg.get("confidence", 0.45))
        self.workers = max(1, int(cfg.get("workers", 4)))
        self.client = InferenceHTTPClient(api_url=cfg.get("api_url", "https://serverless.roboflow.com"), api_key=key).configure(
            InferenceConfiguration(api_key_transport="header", confidence_threshold=self.conf))

    def _one(self, item: tuple[int, float, np.ndarray]) -> list[Box]:
        idx, t, img = item
        res = self.client.infer(img, model_id=self.model_id)
        out = []
        for p in res.get("predictions", []):
            c = float(p.get("confidence", 0))
            if c < self.conf:
                continue
            x, y, w, h = (float(p[k]) for k in ("x", "y", "width", "height"))
            out.append(Box(t, idx, x - w / 2, y - h / 2, x + w / 2, y + h / 2, c, str(p.get("class", "pothole"))))
        return out

    def detect(self, frames):
        with ThreadPoolExecutor(self.workers) as ex:
            return [b for boxes in ex.map(self._one, frames) for b in boxes]


class FixedDetector(Detector):
    """Returns preset detections (for tests and for re-running with known times)."""

    name = "fixed"

    def __init__(self, boxes: list[dict]):
        self.boxes = boxes

    def detect(self, frames):
        out = []
        for idx, t, img in frames:
            for b in self.boxes:
                if abs(b["t"] - t) < 1e-6 or (b.get("t0", 1e9) <= t <= b.get("t1", -1e9)):
                    x0, y0, x1, y1 = b["box"]
                    out.append(Box(t, idx, x0, y0, x1, y1, b.get("conf", 0.9), "pothole"))
        return out


def make_detector(cfg: dict) -> Detector:
    kind = cfg.get("kind", "roboflow")
    if kind == "roboflow":
        return RoboflowDetector(cfg)
    if kind == "fixed":
        return FixedDetector(cfg.get("boxes", []))
    raise ValueError(f"unknown detector kind {kind}")

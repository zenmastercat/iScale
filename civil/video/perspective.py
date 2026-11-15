"""Road-plane perspective transform (bird's-eye view) with OpenCV.

Follows the 4-point method: cv2.getPerspectiveTransform(source, target) builds the
3x3 matrix from four corresponding points (same order on both sides: top-left,
bottom-left, bottom-right, top-right) and cv2.warpPerspective(image, M, size) warps
the pixels.  The four source points are the corners of a known rectangle on the road
(e.g. a lane 3.5 m wide); the target is that rectangle in metres, so the warped image
is a top-down view with a fixed scale and any point on the road can be measured.

Use: a size, area and distance estimate for each detection straight from the 2D
frame, plus a top-down evidence image. The 3D reconstruction is the main measurement;
this is the quick cross-check and works even before LingBot has run.
"""

from __future__ import annotations

import numpy as np


class RoadPlane:
    def __init__(self, cfg: dict, frame_w: int, frame_h: int):
        import cv2

        self.cfg = cfg
        self.w_m = float(cfg["width_m"])
        self.l_m = float(cfg["length_m"])
        self.near_m = float(cfg.get("near_m", 0.0))
        self.ppm = float(cfg.get("px_per_m", 40))
        src = np.array([[x * frame_w, y * frame_h] for x, y in cfg["src"]], dtype=np.float32)
        # target rectangle in BEV pixels: x across (0..w), y along (0 = far edge, bottom = near edge)
        bw, bh = self.w_m * self.ppm, self.l_m * self.ppm
        self.margin = 1.0 * self.ppm  # show 1 m either side of the rectangle
        m = self.margin
        dst = np.array([[m, 0], [m, bh], [m + bw, bh], [m + bw, 0]], dtype=np.float32)
        self.size = (int(bw + 2 * m), int(bh))
        self.M = cv2.getPerspectiveTransform(src, dst)
        # the matrix is defined up to scale and may come out with a negative sign; points on the
        # road share the sign of w with the calibration points, points beyond the horizon flip it
        self.wsign = float(np.sign((self.M @ np.r_[src[1], 1.0])[2]))
        self.calibrated = bool(cfg.get("calibrated", False))

    def bev(self, frame: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.warpPerspective(frame, self.M, self.size, flags=cv2.INTER_LINEAR)

    def to_metres(self, pts_px: np.ndarray) -> np.ndarray:
        """Image pixels (N,2) on the road plane -> (N,2) metres: x lateral (0 = rectangle centre), y ahead of camera.
        Points at or above the horizon have no position on the road and come back as NaN."""
        p = np.c_[pts_px, np.ones(len(pts_px))] @ self.M.T
        w = p[:, 2:3] * self.wsign
        p = np.where(w > 1e-9, p[:, :2] * self.wsign / np.where(w > 1e-9, w, 1.0), np.nan)
        x = (p[:, 0] - self.margin) / self.ppm - self.w_m / 2
        y = self.near_m + (self.l_m - p[:, 1] / self.ppm)
        return np.c_[x, y]

    def measure_box(self, box: tuple[float, float, float, float]) -> dict:
        """Footprint of a detection box assumed flat on the road."""
        x0, y0, x1, y1 = box
        corners = self.to_metres(np.array([[x0, y0], [x0, y1], [x1, y1], [x1, y0]], dtype=np.float64))
        xs, ys = corners[:, 0], corners[:, 1]
        far = self.near_m + 3 * self.l_m
        if not np.isfinite(corners).all() or ys.min() < 0 or ys.max() > far or np.ptp(xs) > 3 * self.w_m:
            return {"bev_valid": False, "calibrated": self.calibrated}
        area = 0.5 * abs(np.dot(xs, np.roll(ys, 1)) - np.dot(ys, np.roll(xs, 1)))
        width = float(np.linalg.norm(corners[2] - corners[1]))
        length = float(np.linalg.norm(corners[1] - corners[0]))
        return {"bev_valid": True, "bev_width_m": round(width, 2), "bev_length_m": round(length, 2), "bev_area_m2": round(float(area), 2),
                "distance_ahead_m": round(float(min(ys)), 1), "lateral_m": round(float(np.mean(xs)), 2),
                "calibrated": self.calibrated}

    def overlay(self, frame: np.ndarray) -> np.ndarray:
        """Frame with the calibration trapezoid drawn on it (for checking/adjusting src)."""
        import cv2

        h, w = frame.shape[:2]
        pts = np.array([[x * w, y * h] for x, y in self.cfg["src"]], dtype=np.int32)
        out = frame.copy()
        cv2.polylines(out, [pts], True, (32, 176, 255), 2)
        for i, (x, y) in enumerate(pts):
            cv2.circle(out, (int(x), int(y)), 6, (32, 176, 255), -1)
            cv2.putText(out, ["TL", "BL", "BR", "TR"][i], (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return out

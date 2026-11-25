"""Road segments along the survey trajectory, and station/offset of each point."""

from __future__ import annotations

import numpy as np


def resample_path(traj: np.ndarray, step: float = 0.5) -> np.ndarray:
    """Evenly spaced (K,2) samples along the horizontal trajectory, dropping stops/back-ups."""
    xy = traj[:, :2].astype(np.float64)
    keep = [0]
    for i in range(1, len(xy)):
        if np.linalg.norm(xy[i] - xy[keep[-1]]) > 0.05:
            keep.append(i)
    xy = xy[keep]
    if len(xy) < 2:
        raise ValueError("trajectory too short")
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    s = np.arange(0, d[-1], step)
    if len(s) < 2:
        s = np.array([0.0, d[-1]])
    return np.stack([np.interp(s, d, xy[:, 0]), np.interp(s, d, xy[:, 1])], 1)


def station_offset(xy: np.ndarray, path: np.ndarray, step: float, chunk: int = 8_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For points (N,2): nearest path index, station (m along path), signed offset (m, + = left)."""
    fwd = np.gradient(path, axis=0)
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-12
    left = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    n = len(xy)
    idx = np.empty(n, np.int64)
    # coarse grid of path samples to keep the distance matrix small
    for a in range(0, n, chunk):
        p = xy[a:a + chunk]
        d2 = ((p[:, None, :] - path[None, :, :]) ** 2).sum(-1)
        idx[a:a + chunk] = d2.argmin(1)
    rel = xy - path[idx]
    along = (rel * fwd[idx]).sum(1)
    off = (rel * left[idx]).sum(1)
    station = idx * step + along
    return idx, station, off


def make_segments(path: np.ndarray, step: float, seg_len: float) -> list[dict]:
    total = (len(path) - 1) * step
    n = max(1, int(round(total / seg_len)))
    edges = np.linspace(0, total, n + 1)
    segs = []
    for k in range(n):
        a, b = edges[k], edges[k + 1]
        ia, ib = int(a / step), min(len(path) - 1, int(np.ceil(b / step)))
        segs.append({"id": f"S{k + 1:03d}", "index": k, "s0": float(a), "s1": float(b),
                     "length_m": float(b - a), "line": path[ia:ib + 1].tolist()})
    return segs

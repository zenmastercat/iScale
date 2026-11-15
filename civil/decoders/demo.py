"""Synthetic street scan, so the whole pipeline can be tried without a real decoder.

The scene is two streets in an L (140 m east, then 100 m north) with curbs,
sidewalks, buildings, trees, streetlights, utility poles, a hydrant, four kinds of
signs, and planted defects: potholes, a sunken manhole, a heave, a rough patch and a
sidewalk trip hazard.  With params {"repaired": true} it renders the same street
after a repair crew has fixed some of them, for before/after verification.

Like many real decoders it outputs y-up axes and camera-convention poses; the
GPS track is in WGS84.  civil.align brings it back to ENU.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..pointcloud import Reconstruction, enu_to_latlon
from .base import Decoder

ROAD_HALF = 4.0
CURB_H = 0.15
WALK_OUT = 6.5
VERGE_OUT = 8.0
FACADE_L = 11.0

ASPHALT = np.array([72, 72, 76])
CONCRETE = np.array([168, 166, 160])
GRASS = np.array([78, 118, 58])


@dataclass
class Street:
    name: str
    start: tuple[float, float]
    heading: float  # radians, ENU angle of the driving direction
    length: float

    def to_enu(self, s: np.ndarray, l: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        c, si = math.cos(self.heading), math.sin(self.heading)
        # l is positive to the LEFT of the driving direction
        x = self.start[0] + s * c - l * si
        y = self.start[1] + s * si + l * c
        return x, y


STREETS = [
    Street("Pracharat Rd", (0.0, 0.0), 0.0, 140.0),
    Street("Wongsawang Rd", (140.0, 0.0), math.pi / 2, 100.0),
]

# Planted features: (street index, s, l, ...).  "fix" = repaired in the after survey.
POTHOLES = [  # street, s, l, radius, depth, fix
    (0, 22.0, -1.6, 0.45, 0.08, True),
    (0, 57.5, 1.2, 0.30, 0.045, True),
    (0, 96.0, -2.4, 0.60, 0.11, False),
    (1, 31.0, 1.8, 0.35, 0.06, True),
    (1, 74.0, -1.1, 0.25, 0.035, False),
]
MANHOLES = [  # street, s, l, sink(m), fix
    (0, 70.0, 0.4, 0.035, True),
    (1, 50.0, -0.5, 0.0, False),  # flush cover: asset only
]
HEAVES = [(1, 12.0, -2.0, 0.6, 0.045)]  # street, s, l, radius, height
ROUGH = [(0, 112.0, -2.5, 3.0, 1.6)]  # street, s0, l0, length, width
TRIP = [(0, 41.0, 5.3, 1.4, 1.2, 0.035, True)]  # street, s, l, len, width, step, fix
STREETLIGHTS = [(0, s, 5.1) for s in (15, 50, 85, 120)] + [(1, s, 5.1) for s in (20, 55, 90)]
UTILITY = [(0, s, -5.3) for s in (30, 75, 120)] + [(1, s, -5.3) for s in (40, 85)]
TREES = [(0, s, -7.2) for s in (12, 45, 66, 101, 132)] + [(1, s, 7.2) for s in (8, 38, 66)]
HYDRANTS = [(0, 82.0, -4.6)]
SIGNS = [  # street, s, l, kind
    (0, 136.0, 4.7, "stop"),
    (0, 8.0, -4.7, "regulatory"),
    (1, 60.0, 4.7, "warning"),
    (1, 4.0, -4.7, "guide"),
    (1, 96.0, 4.7, "stop"),
]
SIGN_COLORS = {"stop": (200, 28, 36), "warning": (236, 196, 24), "regulatory": (238, 238, 238), "guide": (18, 120, 60)}


def _uniform(rng, n, s_range, l_range):
    s = rng.uniform(*s_range, n)
    l = rng.uniform(*l_range, n)
    return s, l


class _Builder:
    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.xyz: list[np.ndarray] = []
        self.rgb: list[np.ndarray] = []

    def add(self, x, y, z, color, jitter=6):
        n = len(x)
        c = np.clip(np.asarray(color, float)[None, :] + self.rng.normal(0, jitter, (n, 3)), 0, 255)
        self.xyz.append(np.stack([x, y, z], 1).astype(np.float32))
        self.rgb.append(c.astype(np.uint8))

    def cylinder(self, cx, cy, z0, z1, r, color, density=900):
        area = 2 * math.pi * r * (z1 - z0)
        n = max(20, int(area * density))
        a = self.rng.uniform(0, 2 * math.pi, n)
        z = self.rng.uniform(z0, z1, n)
        self.add(cx + r * np.cos(a), cy + r * np.sin(a), z, color)

    def blob(self, cx, cy, cz, r, color, n):
        v = self.rng.normal(0, 1, (n, 3))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        rad = r * self.rng.uniform(0.75, 1.0, n) ** 0.5
        self.add(cx + v[:, 0] * rad, cy + v[:, 1] * rad, cz + v[:, 2] * rad * 0.8, color, jitter=18)


def build_scene(repaired: bool = False, seed: int = 7, density: float = 1.0) -> tuple[np.ndarray, np.ndarray, list]:
    rng = np.random.default_rng(seed + (101 if repaired else 0))
    b = _Builder(rng)
    road_d, walk_d = 260 * density, 140 * density

    for si, st in enumerate(STREETS):
        L = st.length
        # --- road surface with planted defects ------------------------------
        n = int(L * 2 * ROAD_HALF * road_d)
        s, l = _uniform(rng, n, (0, L), (-ROAD_HALF, ROAD_HALF))
        z = rng.normal(0, 0.003, n)
        col = np.repeat(ASPHALT[None], n, 0).astype(float)
        # centre dashes
        dash = (np.abs(l) < 0.08) & ((s % 6.0) < 3.0)
        col[dash] = (225, 222, 205)
        for (ps, p_s, p_l, R, depth, fix) in POTHOLES:
            if ps != si:
                continue
            r = np.hypot(s - p_s, l - p_l)
            inside = r < R
            if repaired and fix:
                col[inside] = (38, 38, 40)  # fresh patch, flush
                z[inside] += rng.normal(0, 0.002, inside.sum())
            else:
                z[inside] -= depth * np.sqrt(1 - (r[inside] / R) ** 2) * 0.9 + depth * 0.1
                col[inside] = (52, 48, 44)
        for (ms, m_s, m_l, sink, fix) in MANHOLES:
            if ms != si:
                continue
            inside = np.hypot(s - m_s, l - m_l) < 0.32
            z[inside] = rng.normal(0, 0.0015, inside.sum()) - (0 if (repaired and fix) else sink)
            col[inside] = (60, 62, 66)
        for (hs, h_s, h_l, R, h) in HEAVES:
            if hs != si:
                continue
            r2 = (s - h_s) ** 2 + (l - h_l) ** 2
            z += h * np.exp(-r2 / (2 * (R / 2) ** 2))
        for (rs, s0, l0, ln, w) in ROUGH:
            if rs != si:
                continue
            m = (s > s0) & (s < s0 + ln) & (l > l0 - w / 2) & (l < l0 + w / 2)
            z[m] += rng.normal(0, 0.012, m.sum())
            col[m] *= 0.85
        x, y = st.to_enu(s, l)
        b.add(x, y, z, (0, 0, 0), jitter=0)
        b.rgb[-1] = np.clip(col + rng.normal(0, 7, col.shape), 0, 255).astype(np.uint8)

        # --- curbs, sidewalks, verges, facades (both sides) ------------------
        for side in (-1, 1):
            n = int(L * CURB_H * 400 * density)
            s = rng.uniform(0, L, n)
            x, y = st.to_enu(s, np.full(n, side * ROAD_HALF))
            b.add(x, y, rng.uniform(0, CURB_H, n), CONCRETE * 0.9)
            n = int(L * (WALK_OUT - ROAD_HALF) * walk_d)
            s, l = _uniform(rng, n, (0, L), (ROAD_HALF, WALK_OUT))
            z = CURB_H + rng.normal(0, 0.003, n)
            for (ts, t_s, t_l, tl, tw, step, fix) in TRIP:
                if ts == si and side == 1 and not (repaired and fix):
                    m = (np.abs(s - t_s) < tl / 2) & (np.abs(l - t_l) < tw / 2)
                    z[m] += step
            b.add(*st.to_enu(s, side * l), z, CONCRETE)
            n = int(L * (VERGE_OUT - WALK_OUT) * 60 * density)
            s, l = _uniform(rng, n, (0, L), (WALK_OUT, VERGE_OUT))
            b.add(*st.to_enu(s, side * l), 0.12 + rng.normal(0, 0.02, n), GRASS, jitter=14)
            # facades: blocks of buildings with gaps
            s0 = rng.uniform(0, 4)
            while s0 < L - 6:
                w = rng.uniform(10, 22)
                h = rng.uniform(5, 11)
                n = int(w * h * 25 * density)
                s = rng.uniform(s0, min(s0 + w, L), n)
                zf = rng.uniform(CURB_H, h, n)
                tone = rng.uniform(140, 210)
                b.add(*st.to_enu(s, np.full(n, side * FACADE_L)), zf, (tone, tone * 0.95, tone * 0.88), jitter=10)
                s0 += w + rng.uniform(2, 6)

    def at(si, s, l):
        x, y = STREETS[si].to_enu(np.array([s]), np.array([l]))
        return float(x[0]), float(y[0])

    truth = []
    # --- streetlights: pole + arm over the road + lamp head ------------------
    for si, s, l in STREETLIGHTS:
        cx, cy = at(si, s, l)
        b.cylinder(cx, cy, CURB_H, 8.0, 0.11, (120, 124, 128))
        hx, hy = at(si, s, l - 1.6)
        t = rng.uniform(0, 1, 300)
        b.add(cx + (hx - cx) * t, cy + (hy - cy) * t, 7.9 + rng.normal(0, 0.03, 300), (120, 124, 128))
        b.blob(hx, hy, 7.8, 0.25, (230, 226, 200), 250)
        truth.append(("streetlight", cx, cy))
    for si, s, l in UTILITY:
        cx, cy = at(si, s, l)
        b.cylinder(cx, cy, CURB_H, 10.0, 0.15, (110, 84, 60))
        truth.append(("utility_pole", cx, cy))
    for si, s, l in TREES:
        cx, cy = at(si, s, l)
        b.cylinder(cx, cy, 0.12, 3.0, 0.16, (92, 70, 52), density=700)
        b.blob(cx, cy, 4.8, 2.3, GRASS * 0.8, 5000)
        truth.append(("tree", cx, cy))
    for si, s, l in HYDRANTS:
        cx, cy = at(si, s, l)
        b.cylinder(cx, cy, CURB_H, 0.85, 0.12, (210, 40, 30), density=2500)
        truth.append(("fire_hydrant", cx, cy))
    for si, s, l, kind in SIGNS:
        cx, cy = at(si, s, l)
        b.cylinder(cx, cy, CURB_H, 2.3, 0.035, (150, 150, 150), density=3000)
        # plate faces along the street (normal = driving direction)
        st = STREETS[si]
        tx, ty = -math.sin(st.heading), math.cos(st.heading)  # plate's horizontal axis (lateral)
        n = 2600
        u = rng.uniform(-0.38, 0.38, n)
        v = rng.uniform(-0.38, 0.38, n)
        if kind == "stop":  # octagon
            keep = (np.abs(u) + np.abs(v)) < 0.38 * 1.55
        elif kind == "warning":  # diamond
            keep = (np.abs(u) + np.abs(v)) < 0.40
        elif kind == "guide":  # wide, short blade
            u = rng.uniform(-0.6, 0.6, n)
            v = rng.uniform(-0.12, 0.12, n)
            keep = np.ones(n, bool)
        else:  # regulatory rectangle (portrait)
            u = rng.uniform(-0.3, 0.3, n)
            keep = np.ones(n, bool)
        u, v = u[keep], v[keep]
        b.add(cx + 0.06 * math.cos(st.heading) + u * tx, cy + 0.06 * math.sin(st.heading) + u * ty,
              2.65 + v, SIGN_COLORS[kind], jitter=8)
        truth.append(("sign_" + kind, cx, cy))
    for (si, p_s, p_l, R, depth, fix) in POTHOLES:
        if not (repaired and fix):
            truth.append(("pothole", *at(si, p_s, p_l)))
    for (si, h_s, h_l, R, hh) in HEAVES:
        truth.append(("heave", *at(si, h_s, h_l)))
    for (si, s0, l0, ln, w) in ROUGH:
        truth.append(("surface_roughness", *at(si, s0 + ln / 2, l0)))
    for (si, t_s, t_l, tl, tw, stp, fix) in TRIP:
        if not (repaired and fix):
            truth.append(("sidewalk_trip_hazard", *at(si, t_s, t_l)))
    for (si, m_s, m_l, sink, fix) in MANHOLES:
        truth.append(("manhole_sunken" if sink and not (repaired and fix) else "manhole", *at(si, m_s, m_l)))

    xyz = np.concatenate(b.xyz)
    rgb = np.concatenate(b.rgb)
    return xyz, rgb, truth


def demo_trajectory(step: float = 0.5, cam_h: float = 2.1, lane: float = -1.8):
    """Camera centres (K,3), headings (K,) and times (K,) along both streets."""
    pts, heads = [], []
    for st in STREETS:
        s = np.arange(0, st.length, step)
        x, y = st.to_enu(s, np.full(len(s), lane))
        pts.append(np.stack([x, y, np.full(len(s), cam_h)], 1))
        heads.append(np.full(len(s), st.heading))
    c = np.concatenate(pts)
    h = np.concatenate(heads)
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c[:, :2], axis=0), axis=1))]
    return c, h, d / 8.0  # 8 m/s


# ENU (x east, y north, z up)  ->  decoder frame (x, y up, z = -north)
_TO_DECODER = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)


class DemoDecoder(Decoder):
    name = "demo"
    label = "Demo street (synthetic)"
    description = "Generates a synthetic street scan with planted defects and assets. Set repaired=true for the after-repair survey."
    accepts = ()

    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        repaired = bool(params.get("repaired", False))
        density = float(params.get("density", 1.0))
        xyz, rgb, truth = build_scene(repaired=repaired, seed=int(params.get("seed", 7)), density=density)
        cams, heads, times = demo_trajectory()
        poses = np.repeat(np.eye(4)[None], len(cams), 0)
        for i, (c, h) in enumerate(zip(cams, heads)):
            fwd = np.array([math.cos(h), math.sin(h), 0.0])
            right = np.array([math.sin(h), -math.cos(h), 0.0])
            down = np.array([0.0, 0.0, -1.0])
            poses[i, :3, :3] = np.stack([right, down, fwd], 1)  # OpenCV camera axes in ENU
            poses[i, :3, 3] = c
        # express everything in the decoder's own frame
        r = _TO_DECODER
        xyz_d = xyz.astype(np.float64) @ r.T
        poses_d = poses.copy()
        poses_d[:, :3, :3] = r @ poses[:, :3, :3]
        poses_d[:, :3, 3] = poses[:, :3, 3] @ r.T
        lat0 = float(params.get("origin_lat", 13.8196))
        lon0 = float(params.get("origin_lon", 100.5137))
        rng = np.random.default_rng(3)
        glat, glon = enu_to_latlon(cams[::4, 0] + rng.normal(0, 0.4, len(cams[::4])),
                                   cams[::4, 1] + rng.normal(0, 0.4, len(cams[::4])), lat0, lon0)
        gps = np.stack([times[::4], glat, glon], 1)
        return Reconstruction(points=xyz_d, colors=rgb, poses=poses_d, times=times, gps=gps,
                              meta={"metric": True, "up_axis": "y", "decoder": self.name,
                                    "repaired": repaired, "truth": [list(t) for t in truth]})

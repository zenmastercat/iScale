"""Honest pothole measurement accuracy benchmark for both 3D paths in iScale.

Paths evaluated:
  1. Phone video -> LingBot-Map -> Reconstruction -> Pothole analysis
  2. FORGE SLAM (LiDAR + IMU) -> Reconstruction -> Pothole analysis
  (+ shared 3D alignment & surface analysis on real metric 3D road scans)

Strict rules:
  - Real-GT datasets and synthetic datasets are ALWAYS reported separately.
  - Dev splits and held-out Test splits are ALWAYS separated; never tune on Test.
  - Ground-truth depth, area and volume come from independent geometry/annotations
    and are never modified to match predictions.
"""

from __future__ import annotations

import json
import math
import resource
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np
import scipy.io
from scipy.spatial.transform import Rotation

from .align import align, ransac_plane
from .analysis import analyze
from .config import DEFAULT_ORIGIN, ROOT
from .decoders.lingbot_clip import LingbotClipDecoder, free_gpu_gb
from .forge.pipeline import ForgeSlam
from .forge.types import ForgeConfig, ImuSample, LidarScan, SensorCalibration
from .pointcloud import Reconstruction, read_ply


def default_pothole_datasets_dir() -> Path:
    return ROOT.parent / "iScale-datasets" / "potholes"


# ---------------------------------------------------------------------------
# Ground-truth schema & exact 1-to-1 matching / scoring
# ---------------------------------------------------------------------------
@dataclass
class PotholeGT:
    id: str
    x: float
    y: float
    depth_m: float
    area_m2: float
    volume_m3: float
    diameter_m: float
    shape: str = "bowl"


def match_and_score(
    gt: list[PotholeGT],
    findings: list[dict],
    match_radius_m: float | None = None,
) -> dict:
    """Match predicted pothole findings 1-to-1 against ground-truth potholes and score errors."""
    pothole_preds = [f for f in findings if f.get("type") == "pothole"]
    other_deps = [f for f in findings if f.get("type") in ("depression", "manhole_sunken")]

    # Build candidate (dist, gi, pi) pairs within radius
    pairs: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gt):
        rad = match_radius_m if match_radius_m is not None else max(0.50, 0.75 * g.diameter_m)
        for pi, f in enumerate(pothole_preds):
            d = math.hypot(float(f["x"]) - g.x, float(f["y"]) - g.y)
            if d <= rad:
                pairs.append((d, gi, pi))
    pairs.sort(key=lambda t: t[0])

    used_g: set[int] = set()
    used_p: set[int] = set()
    matches: list[dict] = []
    for dist, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        g = gt[gi]
        f = pothole_preds[pi]
        m = f.get("metrics") or {}
        d_pred = m.get("depth_max_m")
        a_pred = float(m.get("area_m2") or 0.0)
        v_pred = float(m.get("volume_m3") or 0.0)
        unreliable = bool(m.get("depth_unreliable")) or d_pred is None
        rec = {
            "gt_id": g.id,
            "shape": g.shape,
            "dist_m": round(dist, 3),
            "gt_depth_cm": round(g.depth_m * 100.0, 2),
            "pred_depth_cm": None if unreliable else round(float(d_pred) * 100.0, 2),
            "depth_err_cm": None if unreliable else round((float(d_pred) - g.depth_m) * 100.0, 2),
            "depth_abs_err_cm": None if unreliable else round(abs(float(d_pred) - g.depth_m) * 100.0, 2),
            "depth_unreliable": unreliable,
            "gt_area_m2": round(g.area_m2, 4),
            "pred_area_m2": round(a_pred, 4),
            "area_err_pct": round(abs(a_pred - g.area_m2) / max(g.area_m2, 1e-9) * 100.0, 2),
            "area_signed_pct": round((a_pred - g.area_m2) / max(g.area_m2, 1e-9) * 100.0, 2),
            "gt_vol_l": round(g.volume_m3 * 1000.0, 3),
            "pred_vol_l": round(v_pred * 1000.0, 3),
            "vol_err_pct": round(abs(v_pred - g.volume_m3) / max(g.volume_m3, 1e-9) * 100.0, 2),
            "vol_signed_pct": round((v_pred - g.volume_m3) / max(g.volume_m3, 1e-9) * 100.0, 2),
        }
        matches.append(rec)

    # Check if any missed GT was emitted as depression or manhole_sunken
    misclassified: list[dict] = []
    missed: list[str] = []
    for gi, g in enumerate(gt):
        if gi in used_g:
            continue
        rad = match_radius_m if match_radius_m is not None else max(0.50, 0.75 * g.diameter_m)
        hit = None
        for f in other_deps:
            d = math.hypot(float(f["x"]) - g.x, float(f["y"]) - g.y)
            if d <= rad:
                hit = (d, f)
                break
        if hit is not None:
            misclassified.append({"gt_id": g.id, "pred_type": hit[1]["type"], "dist_m": round(hit[0], 3)})
        else:
            missed.append(g.id)

    return {
        "n_gt": len(gt),
        "n_pred": len(pothole_preds),
        "n_matched": len(matches),
        "false_positives": len(pothole_preds) - len(matches),
        "misclassified": misclassified,
        "missed": missed,
        "matches": matches,
    }


def aggregate_scores(scene_scores: list[dict], runtime_s: float = 0.0, vram_peak_mb: float | None = None) -> dict:
    """Aggregate per-scene match results into dataset-level accuracy metrics."""
    n_gt = sum(s["n_gt"] for s in scene_scores)
    n_pred = sum(s["n_pred"] for s in scene_scores)
    n_matched = sum(s["n_matched"] for s in scene_scores)
    n_fp = sum(s["false_positives"] for s in scene_scores)
    n_mis = sum(len(s["misclassified"]) for s in scene_scores)
    all_m = [m for s in scene_scores for m in s["matches"]]

    d_abs = [m["depth_abs_err_cm"] for m in all_m if m["depth_abs_err_cm"] is not None]
    d_sgn = [m["depth_err_cm"] for m in all_m if m["depth_err_cm"] is not None]
    a_abs = [m["area_err_pct"] for m in all_m]
    a_sgn = [m["area_signed_pct"] for m in all_m]
    v_abs = [m["vol_err_pct"] for m in all_m]
    v_sgn = [m["vol_signed_pct"] for m in all_m]

    out = {
        "n_gt": n_gt,
        "n_pred": n_pred,
        "n_matched": n_matched,
        "n_depth_valid": len(d_abs),
        "n_depth_unreliable": sum(1 for m in all_m if m["depth_unreliable"]),
        "n_misclassified": n_mis,
        "false_positives": n_fp,
        "recall": round(n_matched / n_gt, 3) if n_gt else None,
        "precision": round(n_matched / n_pred, 3) if n_pred else None,
        "depth_mae_cm": round(float(np.mean(d_abs)), 3) if d_abs else None,
        "depth_max_cm": round(float(np.max(d_abs)), 3) if d_abs else None,
        "depth_bias_cm": round(float(np.mean(d_sgn)), 3) if d_sgn else None,
        "area_mae_pct": round(float(np.mean(a_abs)), 2) if a_abs else None,
        "area_bias_pct": round(float(np.mean(a_sgn)), 2) if a_sgn else None,
        "vol_mae_pct": round(float(np.mean(v_abs)), 2) if v_abs else None,
        "vol_bias_pct": round(float(np.mean(v_sgn)), 2) if v_sgn else None,
        "runtime_s": round(runtime_s, 2),
        "vram_peak_mb": round(vram_peak_mb, 1) if vram_peak_mb is not None else None,
        "rss_peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    return out


# ---------------------------------------------------------------------------
# GPU VRAM monitor (read-only nvidia-smi polling during LingBot runs)
# ---------------------------------------------------------------------------
class _VramMonitor:
    def __init__(self, interval_s: float = 0.25) -> None:
        self.interval_s = interval_s
        self.peak_mb: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _query_mb(self) -> float | None:
        smi = shutil.which("nvidia-smi")
        if not smi:
            return None
        try:
            r = subprocess.run(
                [smi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            return max(float(x) for x in r.stdout.split())
        except Exception:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            v = self._query_mb()
            if v is not None:
                self.peak_mb = v if self.peak_mb is None else max(self.peak_mb, v)
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "_VramMonitor":
        v = self._query_mb()
        if v is not None:
            self.peak_mb = v
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Analytical synthetic road + pothole surface (exact continuous GT)
# ---------------------------------------------------------------------------
@dataclass
class AnalyticalPotholeSpec:
    id: str
    cx: float
    cy: float
    rx: float
    ry: float
    depth_m: float
    angle_rad: float = 0.0
    profile: str = "parabolic"  # "parabolic", "steep", "asymmetric", "flat_bowl"


@dataclass
class SyntheticRoadScene:
    name: str
    split: str  # "dev" or "test"
    length_m: float
    half_width_m: float
    crown_slope: float  # e.g. 0.02 = 2% cross-slope downward from centerline
    grade_slope: float  # longitudinal slope dz/dx
    noise_sigma_m: float
    potholes: list[AnalyticalPotholeSpec]
    with_traffic: bool = False
    seed: int = 0

    def road_z(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Continuous undisturbed road elevation (grade + quadratic crown)."""
        # Smooth crown: 0 at y=0, -crown_slope * y^2 / half_width_m at edges
        return self.grade_slope * x - self.crown_slope * (y * y) / max(self.half_width_m, 1.0)

    def pothole_depression(self, spec: AnalyticalPotholeSpec, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Non-negative depression depth d(x, y) >= 0 for a single analytical pothole."""
        dx = x - spec.cx
        dy = y - spec.cy
        ca, sa = math.cos(spec.angle_rad), math.sin(spec.angle_rad)
        u = (ca * dx + sa * dy) / spec.rx
        v = (-sa * dx + ca * dy) / spec.ry
        r2 = u * u + v * v
        if spec.profile == "asymmetric":
            # Irregular multi-lobe shape: modulate effective radius by angle
            ang = np.arctan2(v, u)
            scale = 1.0 + 0.18 * np.cos(2.0 * ang + 0.4) + 0.10 * np.sin(3.0 * ang)
            r2 = r2 / (scale * scale)
            d = np.where(r2 < 1.0, spec.depth_m * np.maximum(0.0, 1.0 - r2) ** 1.35, 0.0)
        elif spec.profile == "steep":
            # Steep broken asphalt wall with slightly rounded floor
            d = np.where(r2 < 1.0, spec.depth_m * np.sqrt(np.maximum(0.0, 1.0 - r2 * r2)), 0.0)
        elif spec.profile == "flat_bowl":
            # Flat-ish center with sloped walls (truncated cone / weathered pothole)
            r = np.sqrt(r2)
            d = np.where(r < 1.0, spec.depth_m * np.clip((1.0 - r) / 0.45, 0.0, 1.0), 0.0)
        else:  # parabolic bowl
            d = np.where(r2 < 1.0, spec.depth_m * (1.0 - r2), 0.0)
        return d

    def surface_z(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        z = self.road_z(x, y)
        for sp in self.potholes:
            z = z - self.pothole_depression(sp, x, y)
        return z

    def ground_truth(self, step_m: float = 0.005) -> list[PotholeGT]:
        """Exact numerical integration of each pothole on a 5 mm grid."""
        out: list[PotholeGT] = []
        cell_a = step_m * step_m
        for sp in self.potholes:
            pad = max(sp.rx, sp.ry) * 1.45 + 0.05
            xs = np.arange(sp.cx - pad, sp.cx + pad + step_m, step_m)
            ys = np.arange(sp.cy - pad, sp.cy + pad + step_m, step_m)
            xx, yy = np.meshgrid(xs, ys, indexing="ij")
            d = self.pothole_depression(sp, xx, yy)
            inside = d > 1e-6
            area = float(inside.sum()) * cell_a
            vol = float(d[inside].sum()) * cell_a
            depth = float(d.max())
            out.append(PotholeGT(
                id=f"{self.name}:{sp.id}",
                x=sp.cx,
                y=sp.cy,
                depth_m=depth,
                area_m2=area,
                volume_m3=vol,
                diameter_m=2.0 * math.sqrt(area / math.pi),
                shape=sp.profile,
            ))
        return out


# Deterministic synthetic FORGE scenes (STRICTLY separated Dev vs Held-Out Test)
SYNTH_FORGE_DEV_SCENES: list[SyntheticRoadScene] = [
    SyntheticRoadScene(
        name="forge_dev_clean",
        split="dev",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.02,
        grade_slope=0.015,
        noise_sigma_m=0.010,
        seed=101,
        potholes=[
            AnalyticalPotholeSpec("p1", 6.0, -0.8, 0.22, 0.18, 0.048, 0.2, "parabolic"),
            AnalyticalPotholeSpec("p2", 12.0, 0.6, 0.30, 0.26, 0.068, -0.3, "parabolic"),
            AnalyticalPotholeSpec("p3", 18.5, -0.4, 0.40, 0.34, 0.088, 0.5, "steep"),
            AnalyticalPotholeSpec("p4", 25.0, 0.9, 0.48, 0.42, 0.112, -0.2, "asymmetric"),
        ],
    ),
    SyntheticRoadScene(
        name="forge_dev_traffic",
        split="dev",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.02,
        grade_slope=0.0,
        noise_sigma_m=0.012,
        with_traffic=True,
        seed=102,
        potholes=[
            AnalyticalPotholeSpec("p1", 7.0, 0.5, 0.19, 0.16, 0.075, 0.1, "steep"),
            AnalyticalPotholeSpec("p2", 13.5, -0.7, 0.42, 0.36, 0.042, 0.7, "parabolic"),
            AnalyticalPotholeSpec("p3", 20.0, 0.2, 0.34, 0.28, 0.095, -0.4, "asymmetric"),
            AnalyticalPotholeSpec("p4", 26.0, -0.9, 0.28, 0.24, 0.062, 0.3, "flat_bowl"),
        ],
    ),
    SyntheticRoadScene(
        name="forge_dev_slope_edge",
        split="dev",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.025,
        grade_slope=0.025,
        noise_sigma_m=0.012,
        seed=103,
        potholes=[
            AnalyticalPotholeSpec("p1", 6.5, 1.8, 0.25, 0.21, 0.055, 0.0, "parabolic"),
            AnalyticalPotholeSpec("p2", 13.0, -1.9, 0.36, 0.30, 0.082, 0.4, "steep"),
            AnalyticalPotholeSpec("p3", 19.5, 1.4, 0.44, 0.35, 0.104, -0.6, "asymmetric"),
            AnalyticalPotholeSpec("p4", 25.5, -1.2, 0.24, 0.22, 0.050, 0.2, "flat_bowl"),
        ],
    ),
]

SYNTH_FORGE_TEST_SCENES: list[SyntheticRoadScene] = [
    SyntheticRoadScene(
        name="forge_test_varied",
        split="test",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.022,
        grade_slope=-0.018,
        noise_sigma_m=0.012,
        seed=201,
        potholes=[
            AnalyticalPotholeSpec("p1", 5.5, 0.4, 0.20, 0.17, 0.052, -0.2, "parabolic"),
            AnalyticalPotholeSpec("p2", 11.5, -1.1, 0.33, 0.29, 0.078, 0.6, "asymmetric"),
            AnalyticalPotholeSpec("p3", 18.0, 0.8, 0.50, 0.40, 0.118, 0.1, "steep"),
            AnalyticalPotholeSpec("p4", 24.5, -0.3, 0.27, 0.22, 0.044, -0.5, "flat_bowl"),
        ],
    ),
    SyntheticRoadScene(
        name="forge_test_traffic",
        split="test",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.028,
        grade_slope=0.020,
        noise_sigma_m=0.014,
        with_traffic=True,
        seed=202,
        potholes=[
            AnalyticalPotholeSpec("p1", 7.5, -0.6, 0.23, 0.19, 0.086, 0.4, "steep"),
            AnalyticalPotholeSpec("p2", 14.0, 1.2, 0.38, 0.33, 0.064, -0.3, "parabolic"),
            AnalyticalPotholeSpec("p3", 20.5, -1.5, 0.46, 0.38, 0.092, 0.8, "asymmetric"),
            AnalyticalPotholeSpec("p4", 26.5, 0.5, 0.31, 0.26, 0.058, -0.1, "flat_bowl"),
        ],
    ),
    SyntheticRoadScene(
        name="forge_test_hard",
        split="test",
        length_m=32.0,
        half_width_m=3.6,
        crown_slope=0.018,
        grade_slope=-0.025,
        noise_sigma_m=0.010,
        seed=203,
        potholes=[
            AnalyticalPotholeSpec("p1", 6.0, -1.7, 0.18, 0.17, 0.060, 0.0, "steep"),
            AnalyticalPotholeSpec("p2", 12.5, 1.6, 0.45, 0.39, 0.045, 0.3, "parabolic"),
            AnalyticalPotholeSpec("p3", 19.0, -0.2, 0.35, 0.24, 0.108, -0.7, "asymmetric"),
            AnalyticalPotholeSpec("p4", 25.0, 0.9, 0.29, 0.27, 0.072, 0.5, "flat_bowl"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Path B: Physically simulated FORGE SLAM road drive
# ---------------------------------------------------------------------------
def _simulate_lidar_world(scene: SyntheticRoadScene, rng: np.random.Generator) -> np.ndarray:
    """Dense static corridor: road (4 cm grid), curbs, sidewalks, and textured facades for LIO."""
    hw = scene.half_width_m
    rx, ry = np.meshgrid(np.arange(-3.0, scene.length_m + 4.0, 0.04), np.arange(-hw, hw + 0.001, 0.04))
    rx, ry = rx.ravel(), ry.ravel()
    rz = scene.surface_z(rx, ry)
    road = np.column_stack([rx, ry, rz])

    # Curbs + sidewalks
    sx, sy_s = np.meshgrid(np.arange(-3.0, scene.length_m + 4.0, 0.12), np.arange(hw + 0.12, hw + 2.2, 0.12))
    sx, sy_s = sx.ravel(), sy_s.ravel()
    sw_l = np.column_stack([sx, sy_s, scene.road_z(sx, sy_s) + 0.15])
    sw_r = np.column_stack([sx, -sy_s, scene.road_z(sx, -sy_s) + 0.15])

    # Side walls + periodic pillars (strong longitudinal LIO constraints so scan-to-map is non-degenerate)
    wx, wz = np.meshgrid(np.arange(-3.0, scene.length_m + 4.0, 0.25), np.arange(0.15, 3.2, 0.25))
    wx, wz = wx.ravel(), wz.ravel()
    lat_mod = 0.35 * np.sin(0.6 * wx)
    w_l = np.column_stack([wx, hw + 2.4 + lat_mod, scene.road_z(wx, np.full_like(wx, hw)) + wz])
    w_r = np.column_stack([wx, -(hw + 2.4 - lat_mod), scene.road_z(wx, np.full_like(wx, -hw)) + wz])

    # End wall ahead so scans see longitudinal planes
    ey, ez = np.meshgrid(np.arange(-(hw + 2.4), hw + 2.5, 0.25), np.arange(0.0, 3.2, 0.25))
    ey, ez = ey.ravel(), ez.ravel()
    w_end = np.column_stack([
        np.full_like(ey, scene.length_m + 4.0),
        ey,
        scene.road_z(np.full_like(ey, scene.length_m + 4.0), ey) + ez,
    ])
    return np.vstack([road, sw_l, sw_r, w_l, w_r, w_end]).astype(np.float64)


def run_synth_forge_scene(
    scene: SyntheticRoadScene,
    work_dir: Path,
    forge_cfg: ForgeConfig | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    """Run full ForgeSlam (ESKF LIO + dynamic filter + tile memory + pose graph) + align + analyze."""
    rng = np.random.default_rng(scene.seed)
    world = _simulate_lidar_world(scene, rng)
    cfg = forge_cfg or ForgeConfig(
        keyframe_dist_m=1.0,
        enable_loop_closure=False,
        enable_thermal=False,
        enable_gsplat=False,
    )
    calib = SensorCalibration(gyr_noise=2.0e-3, acc_noise=2.0e-2, gyr_bias_walk=1e-5, acc_bias_walk=5e-4)
    slam = ForgeSlam(calib, work_dir / scene.name, cfg)

    # 0.5 s stationary IMU init, then smooth 3.0 m/s drive along the road
    t_start = 0.0
    dt_imu = 0.01  # 100 Hz IMU
    sensor_h = 1.5
    speed = 3.0
    t_drive = (scene.length_m - 2.0) / speed
    pitch = -math.atan(scene.grade_slope)  # body X aligned with road slope
    R_wb = np.array([
        [math.cos(pitch), 0.0, math.sin(pitch)],
        [0.0, 1.0, 0.0],
        [-math.sin(pitch), 0.0, math.cos(pitch)],
    ], dtype=np.float64)
    g_w = np.array([0.0, 0.0, -9.80665])
    f_body_true = R_wb.T @ (-g_w)  # specific force at constant velocity

    # Static init samples before first scan
    for k in range(30):
        t = k * dt_imu
        slam.add_imu(ImuSample(
            t=t,
            gyro=rng.normal(0.0, 0.001, 3),
            accel=f_body_true + rng.normal(0.0, 0.01, 3),
        ))

    n_scans = int(t_drive / 0.25) + 1  # 4 Hz scans, 0.75 m spacing along 30 m road
    t0_wall = time.perf_counter()
    prev_t = 0.30
    for si in range(n_scans):
        t_scan = 0.30 + si * 0.25
        # IMU samples between prev_t and t_scan
        t_cur = prev_t + dt_imu
        while t_cur <= t_scan + 1e-9:
            slam.add_imu(ImuSample(
                t=t_cur,
                gyro=rng.normal(0.0, 0.0015, 3),
                accel=f_body_true + rng.normal(0.0, 0.015, 3),
            ))
            t_cur += dt_imu
        prev_t = t_scan

        x_pos = 1.0 + si * 0.25 * speed
        z_pos = float(scene.road_z(np.array([x_pos]), np.array([0.0]))[0]) + sensor_h
        T_wb = np.eye(4, dtype=np.float64)
        T_wb[:3, :3] = R_wb
        T_wb[:3, 3] = [x_pos, 0.0, z_pos]
        T_bw = np.linalg.inv(T_wb)

        # Crop realistic LiDAR FOV (within 16 m horizontally, range > 1.2 m)
        dxy = np.hypot(world[:, 0] - x_pos, world[:, 1])
        sel = (dxy >= 1.2) & (dxy <= 16.0)
        pts_w = world[sel]
        # Subsample distant road points slightly to mimic LiDAR beam divergence; keep dense near vehicle
        pts_b = (pts_w @ T_bw[:3, :3].T) + T_bw[:3, 3]
        # Add realistic radial range noise along ray direction
        r_len = np.linalg.norm(pts_b, axis=1, keepdims=True)
        unit = pts_b / np.maximum(r_len, 1e-6)
        pts_b = pts_b + unit * rng.normal(0.0, scene.noise_sigma_m, size=(len(pts_b), 1))

        if scene.with_traffic:
            # Passing sedan driving in opposite direction across the lane
            car_x = scene.length_m - 2.0 - si * 0.95
            if 0.0 <= car_x <= scene.length_m:
                cx, cy, cz = np.meshgrid(
                    np.linspace(car_x - 1.8, car_x + 1.8, 12),
                    np.linspace(-1.2, 0.6, 8),
                    np.linspace(0.25, 1.45, 7),
                )
                z_base = float(scene.road_z(np.array([car_x]), np.array([-0.3]))[0])
                car_w = np.column_stack([cx.ravel(), cy.ravel(), cz.ravel() + z_base])
                car_b = (car_w @ T_bw[:3, :3].T) + T_bw[:3, 3]
                pts_b = np.vstack([pts_b, car_b])

        slam.add_scan(LidarScan(t=t_scan, points=pts_b.astype(np.float32)))

    res = slam.finish()
    rec = res.reconstruction
    # Align + analyze (note: FORGE outputs metric z-up; align levels & shifts ground to z=0)
    align(rec, *DEFAULT_ORIGIN, {"metric": True, "up_axis": "z"})
    an = analyze(rec, analysis_overrides)
    runtime_s = time.perf_counter() - t0_wall

    # Transform GT positions into aligned frame using the exact shift align() applied to trajectory
    # Trajectory started at world (1.0, 0.0) heading +X (heading=0 maps trajectory start->(0,0) heading North +Y!)
    # Let's map world XY -> aligned XY via Umeyama on keyframe poses so matching is exact!
    gt_raw = scene.ground_truth()
    kf_t = np.array([kf.t for kf in res.keyframes])
    gt_kf_xy = np.column_stack([1.0 + (kf_t - 0.30) * speed, np.zeros_like(kf_t)])
    est_kf_xy = rec.trajectory()[:, :2]
    # Note: align() rotates heading=0 to +Y (north) and shifts traj[0] to (0,0)
    from .align import umeyama
    _, R2, t2 = umeyama(gt_kf_xy, est_kf_xy, with_scale=False)
    gt_aligned = []
    for g in gt_raw:
        p2 = np.array([g.x, g.y]) @ R2.T + t2
        gt_aligned.append(PotholeGT(
            id=g.id, x=float(p2[0]), y=float(p2[1]),
            depth_m=g.depth_m, area_m2=g.area_m2, volume_m3=g.volume_m3,
            diameter_m=g.diameter_m, shape=g.shape,
        ))
    score = match_and_score(gt_aligned, an["findings"])
    score["scene"] = scene.name
    score["runtime_s"] = round(runtime_s, 2)
    score["points"] = rec.n
    return score


def run_synth_forge_suite(split: str = "dev", analysis_overrides: dict | None = None) -> dict:
    scenes = SYNTH_FORGE_DEV_SCENES if split == "dev" else SYNTH_FORGE_TEST_SCENES
    t0 = time.perf_counter()
    scores = []
    with tempfile.TemporaryDirectory(prefix=f"iscale_bench_forge_{split}_") as td:
        for sc in scenes:
            scores.append(run_synth_forge_scene(sc, Path(td), analysis_overrides=analysis_overrides))
    agg = aggregate_scores(scores, runtime_s=time.perf_counter() - t0)
    return {"suite": f"synth-forge-{split}", "synthetic": True, "split": split, "summary": agg, "scenes": scores}


# ---------------------------------------------------------------------------
# Path A: Physically rendered synthetic video -> LingBot-Map -> Align -> Analyze
# ---------------------------------------------------------------------------
SYNTH_VIDEO_DEV_SCENES: list[SyntheticRoadScene] = [
    SyntheticRoadScene(
        name="video_dev_road1",
        split="dev",
        length_m=18.0,
        half_width_m=3.2,
        crown_slope=0.015,
        grade_slope=0.0,
        noise_sigma_m=0.0,
        seed=301,
        potholes=[
            AnalyticalPotholeSpec("p1", 5.5, -0.5, 0.30, 0.25, 0.065, 0.2, "parabolic"),
            AnalyticalPotholeSpec("p2", 9.5, 0.4, 0.38, 0.32, 0.090, -0.3, "steep"),
            AnalyticalPotholeSpec("p3", 13.5, -0.3, 0.26, 0.22, 0.055, 0.4, "asymmetric"),
        ],
    ),
]

SYNTH_VIDEO_TEST_SCENES: list[SyntheticRoadScene] = [
    SyntheticRoadScene(
        name="video_test_road1",
        split="test",
        length_m=18.0,
        half_width_m=3.2,
        crown_slope=0.020,
        grade_slope=0.015,
        noise_sigma_m=0.0,
        seed=401,
        potholes=[
            AnalyticalPotholeSpec("p1", 5.8, 0.4, 0.28, 0.24, 0.072, -0.2, "steep"),
            AnalyticalPotholeSpec("p2", 10.0, -0.5, 0.42, 0.35, 0.085, 0.5, "parabolic"),
            AnalyticalPotholeSpec("p3", 14.0, 0.3, 0.32, 0.26, 0.050, 0.1, "asymmetric"),
        ],
    ),
]


def _value_noise_2d(x: np.ndarray, y: np.ndarray, cell: float, seed: int) -> np.ndarray:
    """Aperiodic bilinear value noise in [-1, 1] at spatial scale `cell` metres."""
    gx = x / cell
    gy = y / cell
    ix = np.floor(gx).astype(np.int64)
    iy = np.floor(gy).astype(np.int64)
    fx = gx - ix
    fy = gy - iy
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)

    def h(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        n = (a * 374761393 + b * 668265263 + seed * 1442695041) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        return ((n ^ (n >> 16)) & 0xFFFF).astype(np.float64) / 32767.5 - 1.0

    v00 = h(ix, iy)
    v10 = h(ix + 1, iy)
    v01 = h(ix, iy + 1)
    v11 = h(ix + 1, iy + 1)
    return (v00 * (1.0 - fx) + v10 * fx) * (1.0 - fy) + (v01 * (1.0 - fx) + v11 * fx) * fy


def _asphalt_texture(x: np.ndarray, y: np.ndarray, seed: int = 7) -> np.ndarray:
    """Deterministic aperiodic multi-scale world-locked asphalt modulation in [-1, 1]."""
    return (
        0.45 * _value_noise_2d(x, y, 0.80, seed)
        + 0.30 * _value_noise_2d(x, y, 0.22, seed + 13)
        + 0.25 * _value_noise_2d(x, y, 0.06, seed + 29)
    )


def _render_road_frame(
    scene: SyntheticRoadScene,
    cam_pos: np.ndarray,
    R_wc: np.ndarray,
    K: np.ndarray,
    H: int = 384,
    W: int = 512,
) -> np.ndarray:
    """Physically ray-cast an RGB frame of the road + potholes + curbs + aperiodic streetscape."""
    vv, uu = np.meshgrid(np.arange(H, dtype=np.float64), np.arange(W, dtype=np.float64), indexing="ij")
    dirs_c = np.stack([(uu - K[0, 2]) / K[0, 0], (vv - K[1, 2]) / K[1, 1], np.ones_like(uu)], axis=-1)
    dirs_w = dirs_c @ R_wc.T  # (H, W, 3)
    dx, dy, dz = dirs_w[..., 0], dirs_w[..., 1], dirs_w[..., 2]

    # Sky background
    img = np.zeros((H, W, 3), dtype=np.float64)
    sky_t = np.clip((H - vv) / H, 0.0, 1.0)
    img[..., 0] = 175 + 45 * sky_t
    img[..., 1] = 200 + 35 * sky_t
    img[..., 2] = 225 + 20 * sky_t

    # Ray-plane initial guess for road (z ≈ grade*x)
    denom = dz - scene.grade_slope * dx
    hit_g = denom < -1e-4
    t_g = np.where(hit_g, (scene.grade_slope * cam_pos[0] - cam_pos[2]) / np.where(hit_g, denom, -1.0), np.inf)
    t_g = np.where((t_g > 0.2) & (t_g < 45.0), t_g, np.inf)

    # 4 secant/fixed-point iterations to intersect exact pothole + crown surface z(x, y)
    for _ in range(4):
        fin = np.isfinite(t_g)
        if not fin.any():
            break
        px = cam_pos[0] + t_g[fin] * dx[fin]
        py = cam_pos[1] + t_g[fin] * dy[fin]
        pz = cam_pos[2] + t_g[fin] * dz[fin]
        zs = scene.surface_z(px, py)
        t_g[fin] = np.clip(t_g[fin] + (zs - pz) / np.minimum(dz[fin], -0.05), 0.2, 45.0)

    # Side walls at |y| = half_width + 1.5
    wall_y = scene.half_width_m + 1.5
    t_wl = np.where(dy > 1e-4, (wall_y - cam_pos[1]) / np.where(dy > 1e-4, dy, 1.0), np.inf)
    t_wr = np.where(dy < -1e-4, (-wall_y - cam_pos[1]) / np.where(dy < -1e-4, dy, -1.0), np.inf)
    t_wall = np.minimum(np.where(t_wl > 0.2, t_wl, np.inf), np.where(t_wr > 0.2, t_wr, np.inf))
    tw_safe = np.where(np.isfinite(t_wall), t_wall, 0.0)
    z_wall = cam_pos[2] + tw_safe * dz
    x_wall = cam_pos[0] + tw_safe * dx
    wall_ok = np.isfinite(t_wall) & (t_wall < 45.0) & (z_wall >= scene.grade_slope * x_wall) & (z_wall <= scene.grade_slope * x_wall + 4.0)
    t_wall = np.where(wall_ok, t_wall, np.inf)

    is_road = np.isfinite(t_g) & (t_g <= t_wall)
    is_wall = np.isfinite(t_wall) & (t_wall < t_g)

    sun = np.array([0.45, -0.55, 0.70])
    sun /= np.linalg.norm(sun)

    if is_road.any():
        px = cam_pos[0] + t_g[is_road] * dx[is_road]
        py = cam_pos[1] + t_g[is_road] * dy[is_road]
        zs = scene.surface_z(px, py)
        eps = 0.01
        gx = (scene.surface_z(px + eps, py) - scene.surface_z(px - eps, py)) / (2 * eps)
        gy = (scene.surface_z(px, py + eps) - scene.surface_z(px, py - eps)) / (2 * eps)
        nx, ny, nz = -gx, -gy, np.ones_like(gx)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz)
        ndotl = np.clip((nx * sun[0] + ny * sun[1] + nz * sun[2]) / nlen, 0.15, 1.0)
        dep = np.maximum(0.0, scene.road_z(px, py) - zs)
        ao = 1.0 - 0.40 * np.clip(dep / 0.08, 0.0, 1.0)
        tex = _asphalt_texture(px, py, scene.seed)

        # Base asphalt vs sidewalk vs pothole interior vs lane markings
        in_hole = dep > 0.005
        on_walk = np.abs(py) > scene.half_width_m
        r = np.where(on_walk, 158.0, np.where(in_hole, 66.0, 86.0)) + 26.0 * tex
        g = np.where(on_walk, 152.0, np.where(in_hole, 60.0, 86.0)) + 26.0 * tex
        b = np.where(on_walk, 144.0, np.where(in_hole, 54.0, 90.0)) + 24.0 * tex

        # Dashed center line & solid edge lines + aperiodic road cracks/tar patches
        center_dash = (np.abs(py) < 0.07) & ((px % 4.0) < 1.8) & (~in_hole)
        edge_line = (np.abs(np.abs(py) - (scene.half_width_m - 0.25)) < 0.06) & (~in_hole)
        stripe = center_dash | edge_line
        r = np.where(stripe, 225.0, r)
        g = np.where(stripe, 225.0, g)
        b = np.where(stripe, 215.0, b)

        shade = (0.35 + 0.65 * ndotl) * ao
        img[is_road, 0] = np.clip(r * shade, 0, 255)
        img[is_road, 1] = np.clip(g * shade, 0, 255)
        img[is_road, 2] = np.clip(b * shade, 0, 255)

    if is_wall.any():
        wx = cam_pos[0] + t_wall[is_wall] * dx[is_wall]
        wy = cam_pos[1] + t_wall[is_wall] * dy[is_wall]
        wz = cam_pos[2] + t_wall[is_wall] * dz[is_wall]
        # Distinct storefront/building facades every 3.5 m with unique colours & windows (prevents VO aliasing!)
        bldg = np.floor(wx / 3.5).astype(np.int64) + (wy > 0).astype(np.int64) * 37
        h_r = ((bldg * 97 + 41) % 90) + 110.0
        h_g = ((bldg * 53 + 73) % 90) + 105.0
        h_b = ((bldg * 31 + 19) % 90) + 95.0
        wn = _value_noise_2d(wx, wz, 0.35, scene.seed + 99) * 20.0
        local_x = wx - np.floor(wx / 3.5) * 3.5
        is_win = (local_x > 0.7) & (local_x < 2.6) & (wz > 1.2) & (wz < 2.8)
        img[is_wall, 0] = np.clip(np.where(is_win, 55.0, h_r + wn), 0, 255)
        img[is_wall, 1] = np.clip(np.where(is_win, 75.0, h_g + wn), 0, 255)
        img[is_wall, 2] = np.clip(np.where(is_win, 95.0, h_b + wn), 0, 255)

    return img.astype(np.uint8)


def run_lingbot_on_frames(
    frames_dir: Path,
    work_dir: Path,
    camera_height_m: float,
    gt_poses_w: np.ndarray | None = None,
    clip_fps: float = 5.0,
    max_depth: float | None = None,
    analysis_overrides: dict | None = None,
) -> tuple[Reconstruction, dict, float, float | None]:
    """Run LingBot-Map via LingbotClipDecoder on a folder of JPEGs and return (rec, analysis, runtime_s, vram_mb)."""
    free = free_gpu_gb()
    if free is not None and free < 11.5:
        raise RuntimeError(f"GPU has only {free:.1f} GB free; need >= 11.5 GB for LingBot-Map")

    input_dir = work_dir / "input"
    fdir = input_dir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    imgs = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
    for k, p in enumerate(imgs):
        dst = fdir / f"{k:06d}.jpg"
        if p.suffix.lower() == ".jpg":
            shutil.copy2(p, dst)
        else:
            cv2.imwrite(str(dst), cv2.imread(str(p)), [cv2.IMWRITE_JPEG_QUALITY, 95])
    (input_dir / "boxes.json").write_text(json.dumps({"boxes": {}, "times": [k / clip_fps for k in range(len(imgs))]}))

    dec = LingbotClipDecoder()
    params = {"camera_height_m": camera_height_m, "clip_fps": clip_fps, "clip_start": 0.0, "max_depth": max_depth}
    t0 = time.perf_counter()
    with _VramMonitor() as mon:
        rec = dec.decode(input_dir, work_dir / "work", params)
    if gt_poses_w is not None and rec.poses is not None and len(gt_poses_w) == len(rec.poses):
        # Convert GT trajectory to synthetic GPS so align() exercises its exact GPS scaling path
        from .pointcloud import enu_to_latlon
        lat, lon = enu_to_latlon(gt_poses_w[:, 0, 3], gt_poses_w[:, 1, 3], *DEFAULT_ORIGIN)
        times = rec.times if rec.times is not None else np.arange(len(gt_poses_w), dtype=np.float64) / clip_fps
        rec.gps = np.column_stack([times, lat, lon])
    align(rec, *DEFAULT_ORIGIN, {"camera_height_m": camera_height_m})
    an_params = {"surface_window_m": 8.0, **(analysis_overrides or {})}
    an = analyze(rec, an_params)
    return rec, an, time.perf_counter() - t0, mon.peak_mb


def run_synth_video_scene(
    scene: SyntheticRoadScene,
    work_dir: Path,
    use_gps_scale: bool = True,
    max_depth: float | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    """Render synthetic road video frames, run LingBot-Map -> align -> analyze, and score vs analytical GT."""
    H, W = 384, 512
    K = np.array([[420.0, 0.0, W / 2.0], [0.0, 420.0, H / 2.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    cam_h = 1.35
    pitch_deg = 12.0  # realistic dashcam/handheld pitch looking down road ahead
    # OpenCV camera axes: x=right (-Y_w), y=down (-Z_w), z=forward (+X_w), then pitch down
    R_base = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)
    p_rad = math.radians(pitch_deg)
    R_pitch = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(p_rad), -math.sin(p_rad)],
        [0.0, math.sin(p_rad), math.cos(p_rad)],
    ], dtype=np.float64)
    R_wc = R_base @ R_pitch

    frames_dir = work_dir / f"{scene.name}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n_frames = 28
    xs = np.linspace(0.5, scene.length_m - 3.5, n_frames)
    poses_gt = np.repeat(np.eye(4)[None], n_frames, axis=0)
    for i, x_c in enumerate(xs):
        y_c = 0.08 * math.sin(0.35 * i)
        z_c = float(scene.road_z(np.array([x_c]), np.array([y_c]))[0]) + cam_h
        pos = np.array([x_c, y_c, z_c], dtype=np.float64)
        poses_gt[i, :3, :3] = R_wc
        poses_gt[i, :3, 3] = pos
        rgb = _render_road_frame(scene, pos, R_wc, K, H=H, W=W)
        cv2.imwrite(str(frames_dir / f"{i:06d}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])

    rec, an, runtime_s, vram_mb = run_lingbot_on_frames(
        frames_dir, work_dir / f"{scene.name}_lb",
        camera_height_m=cam_h,
        gt_poses_w=poses_gt if use_gps_scale else None,
        clip_fps=5.0,
        max_depth=max_depth,
        analysis_overrides=analysis_overrides,
    )
    # Map GT potholes into aligned coordinates via Umeyama on camera trajectories
    from .align import umeyama
    gt_xy = poses_gt[:, :2, 3]
    est_xy = rec.trajectory()[:, :2]
    _, R2, t2 = umeyama(gt_xy, est_xy, with_scale=False)
    gt_aligned = []
    for g in scene.ground_truth():
        p2 = np.array([g.x, g.y]) @ R2.T + t2
        gt_aligned.append(PotholeGT(
            id=g.id, x=float(p2[0]), y=float(p2[1]),
            depth_m=g.depth_m, area_m2=g.area_m2, volume_m3=g.volume_m3,
            diameter_m=g.diameter_m, shape=g.shape,
        ))
    score = match_and_score(gt_aligned, an["findings"])
    score["scene"] = scene.name
    score["scale_mode"] = "gps" if use_gps_scale else "camera_height"
    score["runtime_s"] = round(runtime_s, 2)
    score["vram_peak_mb"] = vram_mb
    score["points"] = rec.n
    return score


def run_synth_video_suite(
    split: str = "dev",
    use_gps_scale: bool = True,
    max_depth: float | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    scenes = SYNTH_VIDEO_DEV_SCENES if split == "dev" else SYNTH_VIDEO_TEST_SCENES
    t0 = time.perf_counter()
    scores = []
    vram_peaks = []
    with tempfile.TemporaryDirectory(prefix=f"iscale_bench_video_{split}_") as td:
        for sc in scenes:
            s = run_synth_video_scene(
                sc, Path(td), use_gps_scale=use_gps_scale,
                max_depth=max_depth, analysis_overrides=analysis_overrides,
            )
            scores.append(s)
            if s.get("vram_peak_mb") is not None:
                vram_peaks.append(s["vram_peak_mb"])
    agg = aggregate_scores(
        scores,
        runtime_s=time.perf_counter() - t0,
        vram_peak_mb=max(vram_peaks) if vram_peaks else None,
    )
    return {
        "suite": f"synth-video-{split}-{'gps' if use_gps_scale else 'camh'}",
        "synthetic": True,
        "split": split,
        "summary": agg,
        "scenes": scores,
    }


# ---------------------------------------------------------------------------
# Real-GT Benchmarks (MIT):
#   1. stereo_pothole_datasets (Rui Fan et al., IEEE T-IP 2019, MIT)
#   2. rethinking_road_reconstruction_pothole_detection (Rui Fan et al., IEEE T-CYB 2020, MIT)
# ---------------------------------------------------------------------------
CLOSE_RANGE_PARAMS = {"pothole_min_area_m2": 0.002, "pothole_min_depth_m": 0.015}


def _extract_stereo_frame_gt_and_cloud(
    mat_path: Path, label_path: Path, rgb_path: Path
) -> tuple[np.ndarray, np.ndarray, list[PotholeGT], float]:
    """Load one stereo_pothole_datasets frame, level onto its road plane, and compute independent GT.

    Returns (road_aligned_xyz_m, rgb_u8, gt_list, cam_height_m).
    Zero points inside the real stereo patch are modified; coordinates are converted mm -> m
    and rigidly rotated so the intact non-pothole road plane lies at z = 0 (+z up toward camera).
    """
    xyz = scipy.io.loadmat(str(mat_path))["xyzPoints"].astype(np.float64) / 1000.0
    lab = cv2.imread(str(label_path))
    rgb = cv2.cvtColor(cv2.imread(str(rgb_path)), cv2.COLOR_BGR2RGB)
    mask = lab.max(axis=-1) > 20
    fin = np.isfinite(xyz).all(axis=-1)

    # Fit road plane strictly on non-pothole pixels (independent of iScale's analysis)
    non = fin & (~mask)
    pts_non = xyz[non]
    sub = pts_non[:: max(1, len(pts_non) // 15_000)]
    n, d, _ = ransac_plane(sub, thresh=0.008, iters=250, seed=0)
    if d < 0:  # orient +n toward camera origin [0,0,0]
        n, d = -n, -d
    cam_h = float(d)

    # Rigid orthonormal basis: u = along-width, v = along-depth, z = +n (up)
    u_ax = np.cross(n, np.array([0.0, 0.0, 1.0]))
    if np.linalg.norm(u_ax) < 1e-6:
        u_ax = np.cross(n, np.array([1.0, 0.0, 0.0]))
    u_ax /= np.linalg.norm(u_ax)
    v_ax = np.cross(n, u_ax)
    R = np.stack([u_ax, v_ax, n], axis=0)  # maps camera coords -> road-level coords

    valid_pts = xyz[fin]
    valid_rgb = rgb[fin]
    pts_lvl = valid_pts @ R.T
    pts_lvl[:, 2] += d  # road plane at z = 0

    # Center XY at road patch centroid
    cx, cy = float(np.median(pts_lvl[:, 0])), float(np.median(pts_lvl[:, 1]))
    pts_lvl[:, 0] -= cx
    pts_lvl[:, 1] -= cy

    # Independent GT from pixel-level pothole mask components
    gt_list: list[PotholeGT] = []
    n_cc, cc_img = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    step = 0.005  # 5 mm integration grid
    for cid in range(1, n_cc):
        pm = (cc_img == cid) & fin
        if int(pm.sum()) < 50:
            continue
        p_pot = xyz[pm] @ R.T
        p_pot[:, 0] -= cx
        p_pot[:, 1] -= cy
        p_pot[:, 2] += d
        h_pot = -p_pot[:, 2]  # positive depth below road plane
        pu, pv = p_pot[:, 0], p_pot[:, 1]
        iu = np.floor((pu - pu.min()) / step).astype(int)
        iv = np.floor((pv - pv.min()) / step).astype(int)
        nv = int(iv.max()) + 1
        flat = iu * nv + iv
        order = np.lexsort((h_pot, flat))
        f_s, h_s = flat[order], h_pot[order]
        starts = np.r_[0, np.flatnonzero(np.diff(f_s)) + 1]
        ends = np.r_[starts[1:], len(f_s)]
        mids = (starts + ends - 1) // 2
        cell_h = np.maximum(0.0, h_s[mids])
        area = len(starts) * step * step
        vol = float(cell_h.sum()) * step * step
        depth = float(np.percentile(cell_h, 99)) if len(cell_h) >= 20 else float(cell_h.max())
        gt_list.append(PotholeGT(
            id=f"{mat_path.parent.parent.name}:{mat_path.stem}:c{cid}",
            x=float(np.mean(pu)),
            y=float(np.mean(pv)),
            depth_m=depth,
            area_m2=area,
            volume_m3=vol,
            diameter_m=2.0 * math.sqrt(area / math.pi),
            shape="real_stereo",
        ))
    return pts_lvl.astype(np.float32), valid_rgb.astype(np.uint8), gt_list, cam_h


def _wrap_patch_as_corridor(
    pts_lvl: np.ndarray,
    rgb: np.ndarray | None,
    cam_h: float,
    seed: int = 0,
) -> tuple[Reconstruction, np.ndarray]:
    """Place an unmodified metric road patch inside a 6 m x 4 m level collar so SegmentSurface's
    0.3 m curb-border erosion operates on the collar rather than clipping the narrow stereo FOV.
    Returns (Reconstruction with poses along +Y, exact XY shift [dx, dy] applied).
    """
    rng = np.random.default_rng(seed)
    x0, x1 = float(pts_lvl[:, 0].min()), float(pts_lvl[:, 0].max())
    y0, y1 = float(pts_lvl[:, 1].min()), float(pts_lvl[:, 1].max())
    # Shift patch so it sits near (east=0, north=3.0) along a 6 m corridor heading North (+Y)
    shift = np.array([0.0, 3.0], dtype=np.float64)
    p_shift = pts_lvl.copy()
    p_shift[:, 0] += shift[0]
    p_shift[:, 1] += shift[1]

    # Outer collar strictly outside the real patch bounding box
    gx, gy = np.meshgrid(np.arange(-2.5, 2.51, 0.04), np.arange(0.0, 6.01, 0.04))
    gx, gy = gx.ravel(), gy.ravel()
    outside = (gx < x0 + shift[0] - 0.02) | (gx > x1 + shift[0] + 0.02) | (gy < y0 + shift[1] - 0.02) | (gy > y1 + shift[1] + 0.02)
    collar = np.column_stack([gx[outside], gy[outside], rng.normal(0.0, 0.002, int(outside.sum()))]).astype(np.float32)

    all_pts = np.vstack([p_shift, collar])
    if rgb is not None:
        all_rgb = np.vstack([rgb, np.full((len(collar), 3), 120, dtype=np.uint8)])
    else:
        all_rgb = None
    poses = np.repeat(np.eye(4)[None], 13, axis=0)
    poses[:, :3, 3] = np.column_stack([np.zeros(13), np.linspace(0.0, 6.0, 13), np.full(13, max(cam_h, 0.5))])
    rec = Reconstruction(
        points=all_pts, colors=all_rgb, poses=poses,
        meta={"metric": True, "up_axis": "z", "decoder": "real_metric_3d"},
    )
    return rec, shift


def run_real_stereo_suite(
    split: str = "dev",
    datasets_dir: Path | None = None,
    default_params_only: bool = False,
    analysis_overrides: dict | None = None,
) -> dict:
    """Evaluate iScale's 3D alignment + surface analysis on real metric stereo road scans (MIT).

    Dev split: dataset1 (22 frames, ~4.3 cm deep).
    Held-out Test split: dataset3 (5 frames, ~2.45 cm deep).
    """
    base = (datasets_dir or default_pothole_datasets_dir()) / "stereo_pothole_datasets"
    ds_name = "dataset1" if split == "dev" else "dataset3"
    ds_dir = base / ds_name
    if not ds_dir.is_dir():
        raise FileNotFoundError(f"Missing real dataset directory: {ds_dir}")

    mats = sorted((ds_dir / "ptcloud").glob("*.mat"))
    t0 = time.perf_counter()
    scores = []
    params = {} if default_params_only else {**CLOSE_RANGE_PARAMS}
    if analysis_overrides:
        params.update(analysis_overrides)

    for idx, mp in enumerate(mats):
        lp = ds_dir / "label" / f"{mp.stem}.png"
        rp = ds_dir / "rgb" / f"{mp.stem}.png"
        pts_lvl, rgb, gt_raw, cam_h = _extract_stereo_frame_gt_and_cloud(mp, lp, rp)
        rec, shift = _wrap_patch_as_corridor(pts_lvl, rgb, cam_h, seed=idx)
        align(rec, *DEFAULT_ORIGIN, {"metric": True, "up_axis": "z"})
        an = analyze(rec, params)
        # Trajectory went along +Y from (0,0) to (0,6) so heading=0 keeps XY unchanged!
        gt_shifted = [
            PotholeGT(
                id=g.id, x=g.x + float(shift[0]), y=g.y + float(shift[1]),
                depth_m=g.depth_m, area_m2=g.area_m2, volume_m3=g.volume_m3,
                diameter_m=g.diameter_m, shape=g.shape,
            )
            for g in gt_raw
        ]
        s = match_and_score(gt_shifted, an["findings"], match_radius_m=0.25)
        s["scene"] = f"{ds_name}/{mp.stem}"
        s["points"] = rec.n
        scores.append(s)

    mode_tag = "default" if default_params_only else "close"
    agg = aggregate_scores(scores, runtime_s=time.perf_counter() - t0)
    return {
        "suite": f"real-stereo-{split}-{mode_tag}",
        "synthetic": False,
        "split": split,
        "dataset": f"stereo_pothole_datasets/{ds_name} (MIT)",
        "analysis_params_override": params,
        "summary": agg,
        "scenes": scores,
    }


def run_real_laser_suite(
    split: str = "dev",
    datasets_dir: Path | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    """Evaluate iScale's 3D surface analysis on real BQ Ciclop 3D laser-scanned pothole molds (MIT).

    Dev split: model1 (5 scans) + model2 (4 scans) = 9 real laser scans.
    Held-out Test split: model3 (4 scans).
    """
    base = (datasets_dir or default_pothole_datasets_dir()) / "rethinking_pothole" / "dataset"
    models = ("model1", "model2") if split == "dev" else ("model3",)
    t0 = time.perf_counter()
    scores = []
    params = {**CLOSE_RANGE_PARAMS, **(analysis_overrides or {})}

    for mname in models:
        gt_dir = base / mname / "gt"
        if not gt_dir.is_dir():
            raise FileNotFoundError(f"Missing laser GT directory: {gt_dir}")
        for idx, ply_path in enumerate(sorted(gt_dir.glob("*.ply"))):
            xyz_mm, _, _ = read_ply(ply_path)
            xyz_m = xyz_mm.astype(np.float64) / 1000.0
            # Independent GT from upside-down laser-scanned gypsum cast (z >= 0 = depth)
            step = 0.002
            ix = np.floor((xyz_m[:, 0] - xyz_m[:, 0].min()) / step).astype(int)
            iy = np.floor((xyz_m[:, 1] - xyz_m[:, 1].min()) / step).astype(int)
            nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
            flat = ix * ny + iy
            order = np.lexsort((-xyz_m[:, 2], flat))
            uf, first_idx = np.unique(flat[order], return_index=True)
            cell_z = xyz_m[order[first_idx], 2]
            gt_area = float(len(uf)) * step * step
            gt_vol = float(cell_z.sum()) * step * step
            gt_depth = float(np.percentile(cell_z, 99.5))

            # Invert mold into a depression z <= 0 centered at (0, 0)
            cx = float(np.mean(xyz_m[:, 0]))
            cy = float(np.mean(xyz_m[:, 1]))
            pot_pts = np.column_stack([xyz_m[:, 0] - cx, xyz_m[:, 1] - cy, -xyz_m[:, 2]]).astype(np.float32)

            # Place unmodified real laser pothole points into a level road plane outside its exact 2D footprint
            occ = np.zeros((nx, ny), dtype=bool)
            occ[uf // ny, uf % ny] = True
            rng = np.random.default_rng(idx + (10 if mname == "model2" else 20 if mname == "model3" else 0))
            gx, gy = np.meshgrid(np.arange(-2.5, 2.51, 0.02), np.arange(-3.0, 3.01, 0.02))
            gx, gy = gx.ravel(), gy.ravel()
            # Keep collar points strictly outside the mold's 2D footprint
            gix = np.floor((gx + cx - xyz_m[:, 0].min()) / step).astype(int)
            giy = np.floor((gy + cy - xyz_m[:, 1].min()) / step).astype(int)
            in_box = (gix >= 0) & (gix < nx) & (giy >= 0) & (giy < ny)
            in_mold = np.zeros(len(gx), dtype=bool)
            in_mold[in_box] = occ[gix[in_box], giy[in_box]]
            collar = np.column_stack([gx[~in_mold], gy[~in_mold], rng.normal(0.0, 0.0015, int((~in_mold).sum()))]).astype(np.float32)

            pts_all = np.vstack([pot_pts, collar])
            pts_all[:, 1] += 3.0  # center at north=3.0 along [0..6] corridor
            poses = np.repeat(np.eye(4)[None], 13, axis=0)
            poses[:, :3, 3] = np.column_stack([np.zeros(13), np.linspace(0.0, 6.0, 13), np.full(13, 0.8)])
            rec = Reconstruction(
                points=pts_all, poses=poses,
                meta={"metric": True, "up_axis": "z", "decoder": "real_laser_gt"},
            )
            align(rec, *DEFAULT_ORIGIN, {"metric": True, "up_axis": "z"})
            an = analyze(rec, params)
            gt = [PotholeGT(
                id=f"{mname}:{ply_path.stem}", x=0.0, y=3.0,
                depth_m=gt_depth, area_m2=gt_area, volume_m3=gt_vol,
                diameter_m=2.0 * math.sqrt(gt_area / math.pi), shape="real_laser",
            )]
            s = match_and_score(gt, an["findings"], match_radius_m=0.25)
            s["scene"] = f"{mname}/{ply_path.stem}"
            s["points"] = rec.n
            scores.append(s)

    agg = aggregate_scores(scores, runtime_s=time.perf_counter() - t0)
    return {
        "suite": f"real-laser-{split}",
        "synthetic": False,
        "split": split,
        "dataset": f"rethinking_pothole/{'+'.join(models)} (MIT)",
        "analysis_params_override": params,
        "summary": agg,
        "scenes": scores,
    }


def run_real_video_suite(
    split: str = "dev",
    datasets_dir: Path | None = None,
    max_depth: float | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    """Run REAL Phone-Video -> LingBot-Map -> Align -> Analyze on real asphalt photo sequences (MIT).

    Dev split: stereo_pothole_datasets/dataset1 (22 RGB frames) + rethinking_pothole/model2 (14 RGB frames).
    Held-out Test split: stereo_pothole_datasets/dataset3 (5 RGB frames) + rethinking_pothole/model1 (8 RGB frames).
    """
    base = datasets_dir or default_pothole_datasets_dir()
    if split == "dev":
        jobs = [
            (
                "stereo_dataset1",
                base / "stereo_pothole_datasets" / "dataset1" / "rgb",
                0.475,
                # Median GT across dataset1 calibrated stereo frames (verified vs model1 laser scan)
                PotholeGT("stereo_dataset1:p1", 0.0, 0.0, depth_m=0.0433, area_m2=0.0046, volume_m3=0.000075, diameter_m=0.077, shape="real_video"),
            ),
            (
                "rethinking_model2",
                base / "rethinking_pothole" / "dataset" / "model2" / "left images",
                0.55,
                # Mean GT across model2 BQ Ciclop laser scans
                PotholeGT("rethinking_model2:p1", 0.0, 0.0, depth_m=0.0407, area_m2=0.00596, volume_m3=0.000114, diameter_m=0.087, shape="real_video"),
            ),
        ]
    else:
        jobs = [
            (
                "stereo_dataset3",
                base / "stereo_pothole_datasets" / "dataset3" / "rgb",
                0.467,
                PotholeGT("stereo_dataset3:p1", 0.0, 0.0, depth_m=0.0244, area_m2=0.0042, volume_m3=0.000044, diameter_m=0.073, shape="real_video"),
            ),
            (
                "rethinking_model1",
                base / "rethinking_pothole" / "dataset" / "model1" / "left images",
                0.475,
                PotholeGT("rethinking_model1:p1", 0.0, 0.0, depth_m=0.0412, area_m2=0.00447, volume_m3=0.000102, diameter_m=0.075, shape="real_video"),
            ),
        ]

    t0 = time.perf_counter()
    scores = []
    vram_peaks = []
    an_over = {**CLOSE_RANGE_PARAMS, **(analysis_overrides or {})}
    with tempfile.TemporaryDirectory(prefix=f"iscale_bench_realvid_{split}_") as td:
        td_p = Path(td)
        for name, img_dir, cam_h, gt_item in jobs:
            # Sort numerically (L9..L22 or 01..22)
            def _num_key(p: Path) -> tuple[int, str]:
                digits = "".join(ch for ch in p.stem if ch.isdigit())
                return (int(digits) if digits else 0, p.name)

            imgs = sorted(img_dir.glob("*.png"), key=_num_key)
            fdir = td_p / f"{name}_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            for k, p in enumerate(imgs):
                shutil.copy2(p, fdir / f"{k:06d}.png")
            rec, an, rt, vr = run_lingbot_on_frames(
                fdir, td_p / f"{name}_lb",
                camera_height_m=cam_h, gt_poses_w=None, clip_fps=5.0,
                max_depth=max_depth, analysis_overrides=an_over,
            )
            if vr is not None:
                vram_peaks.append(vr)
            # Without per-frame world GT coords for monocular camera, match any detected pothole
            # closest to scene center (since each clip contains 1 known physical pothole in view)
            potholes = [f for f in an["findings"] if f.get("type") == "pothole"]
            if potholes:
                # Pick closest to the median point cloud XY
                cx, cy = float(np.median(rec.points[:, 0])), float(np.median(rec.points[:, 1]))
                gt_item = PotholeGT(**{**asdict(gt_item), "x": cx, "y": cy})
                s = match_and_score([gt_item], an["findings"], match_radius_m=3.0)
            else:
                s = match_and_score([gt_item], an["findings"], match_radius_m=3.0)
            s["scene"] = name
            s["frames"] = len(imgs)
            s["runtime_s"] = round(rt, 2)
            s["vram_peak_mb"] = vr
            s["points"] = rec.n
            s["align_notes"] = rec.meta.get("align_notes")
            s["coverage"] = [sg.get("metrics", {}).get("coverage") for sg in an["segments"]]
            scores.append(s)

    agg = aggregate_scores(
        scores,
        runtime_s=time.perf_counter() - t0,
        vram_peak_mb=max(vram_peaks) if vram_peaks else None,
    )
    return {
        "suite": f"real-video-{split}",
        "synthetic": False,
        "split": split,
        "dataset": "stereo_pothole_datasets + rethinking_pothole RGB (MIT)",
        "analysis_params_override": an_over,
        "summary": agg,
        "scenes": scores,
    }


def run_benchmark(
    suites: list[str],
    datasets_dir: Path | None = None,
    analysis_overrides: dict | None = None,
) -> dict:
    """Run one or more named benchmark suites and return structured results."""
    results: dict[str, dict] = {}
    for name in suites:
        if name == "synth-forge-dev":
            results[name] = run_synth_forge_suite("dev", analysis_overrides=analysis_overrides)
        elif name == "synth-forge-test":
            results[name] = run_synth_forge_suite("test", analysis_overrides=analysis_overrides)
        elif name == "synth-video-dev":
            results[name] = run_synth_video_suite("dev", use_gps_scale=True, analysis_overrides=analysis_overrides)
        elif name == "synth-video-dev-camh":
            results[name] = run_synth_video_suite("dev", use_gps_scale=False, analysis_overrides=analysis_overrides)
        elif name == "synth-video-test":
            results[name] = run_synth_video_suite("test", use_gps_scale=True, analysis_overrides=analysis_overrides)
        elif name == "real-stereo-dev-default":
            results[name] = run_real_stereo_suite("dev", datasets_dir, default_params_only=True, analysis_overrides=analysis_overrides)
        elif name == "real-stereo-dev":
            results[name] = run_real_stereo_suite("dev", datasets_dir, default_params_only=False, analysis_overrides=analysis_overrides)
        elif name == "real-stereo-test":
            results[name] = run_real_stereo_suite("test", datasets_dir, default_params_only=False, analysis_overrides=analysis_overrides)
        elif name == "real-laser-dev":
            results[name] = run_real_laser_suite("dev", datasets_dir, analysis_overrides=analysis_overrides)
        elif name == "real-laser-test":
            results[name] = run_real_laser_suite("test", datasets_dir, analysis_overrides=analysis_overrides)
        elif name == "real-video-dev":
            results[name] = run_real_video_suite("dev", datasets_dir, analysis_overrides=analysis_overrides)
        elif name == "real-video-test":
            results[name] = run_real_video_suite("test", datasets_dir, analysis_overrides=analysis_overrides)
        else:
            raise ValueError(f"unknown benchmark suite {name!r}")
    return results

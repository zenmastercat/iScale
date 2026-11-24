"""Synthetic sanity check for FORGE loop closure + pose graph (NOT a dataset evaluation).

Method: an M2DGR ground-truth path (positions only) is used to place simulated keyframes; LiDAR scans are
cut from a synthetic street (road, walls) built around that path, and the "odometry" is the ground-truth
path with injected rotation/translation drift. The ESKF, the dynamic filter and the cameras are not used.
It checks that Scan-Context + G-ICP finds revisits and that the GTSAM graph removes injected drift.
Real-data results come from civil/forge/real_eval.py.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from ..align import umeyama
from ..config import ROOT
from .eskf_lio import so3_exp, so3_log
from .loop_closure import LoopClosureDetector
from .pose_graph import PoseGraphOptimizer
from .types import ForgeConfig, Keyframe, LoopConstraint, SensorCalibration


def default_datasets_dir() -> Path:
    return ROOT.parent / "iScale-datasets"


def ecef_to_local_enu(ecef: np.ndarray) -> np.ndarray:
    """Convert (N, 3) ECEF coordinates in meters into local tangent-plane ENU meters around ecef[0]."""
    p0 = ecef[0].astype(np.float64)
    x0, y0, z0 = float(p0[0]), float(p0[1]), float(p0[2])
    lon0 = math.atan2(y0, x0)
    r_xy = math.hypot(x0, y0)
    lat0 = math.atan2(z0, r_xy * (1.0 - 0.00669437999014))

    slon, clon = math.sin(lon0), math.cos(lon0)
    slat, clat = math.sin(lat0), math.cos(lat0)
    R_enu_ecef = np.array(
        [
            [-slon, clon, 0.0],
            [-slat * clon, -slat * slon, clat],
            [clat * clon, clat * slon, slat],
        ],
        dtype=np.float64,
    )
    dp = ecef.astype(np.float64) - p0[None, :]
    return dp @ R_enu_ecef.T


def load_m2dgr_trajectory(gt_path: Path, max_keyframes: int = 48) -> tuple[np.ndarray, np.ndarray, float]:
    """Load an M2DGR GT_*.txt trajectory, convert ECEF -> ENU, and subsample keyframes along arc length."""
    raw = np.loadtxt(gt_path, dtype=np.float64)
    t_all = raw[:, 0] - raw[0, 0]
    enu_all = ecef_to_local_enu(raw[:, 1:4])
    # Filter occasional RTK jump glitches (> 5 m step in 0.01 s)
    steps = np.linalg.norm(np.diff(enu_all, axis=0), axis=1)
    valid = np.concatenate([[True], steps < 2.0])
    t_all = t_all[valid]
    enu_all = enu_all[valid]

    # Compute cumulative horizontal path length
    seg_d = np.linalg.norm(np.diff(enu_all, axis=0), axis=1)
    total_len_m = float(np.sum(seg_d))

    # Subsample keyframes evenly in index
    idx = np.linspace(0, len(t_all) - 1, min(max_keyframes, len(t_all))).astype(np.int64)
    t_kf = t_all[idx]
    pos_kf = enu_all[idx].copy()
    # Smooth elevation relative to start
    pos_kf[:, 2] = (pos_kf[:, 2] - pos_kf[0, 2]) * 0.2

    # Build SE(3) poses with tangent heading along trajectory
    n_kf = len(pos_kf)
    poses = np.zeros((n_kf, 4, 4), dtype=np.float64)
    for i in range(n_kf):
        if i < n_kf - 1:
            d = pos_kf[i + 1] - pos_kf[i]
        else:
            d = pos_kf[i] - pos_kf[i - 1]
        yaw = math.atan2(float(d[1]), float(d[0])) if np.hypot(d[0], d[1]) > 1e-4 else 0.0
        c, s = math.cos(yaw), math.sin(yaw)
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
        T[:3, 3] = pos_kf[i]
        poses[i] = T

    return t_kf, poses, total_len_m


def _build_environment_landmarks(gt_poses: np.ndarray, seed: int = 42) -> np.ndarray:
    """Create a structured 3D street corridor (road surface + curb walls + facade pillars) around gt_poses."""
    rng = np.random.default_rng(seed)
    pos = gt_poses[:, :3, 3]
    pts_list: list[np.ndarray] = []

    for i in range(len(gt_poses)):
        T = gt_poses[i]
        p = T[:3, 3]
        fwd = T[:3, 0]
        left = T[:3, 1]
        # Road surface patch around keyframe
        u = rng.uniform(-4.0, 4.0, 45)
        v = rng.uniform(-3.5, 3.5, 45)
        road = p[None, :] + u[:, None] * fwd[None, :] + v[:, None] * left[None, :]
        road[:, 2] = p[2]
        pts_list.append(road)

        # Left & right building/curb walls with distinct height profile per spatial location
        for side in (-1.0, 1.0):
            u_w = rng.uniform(-4.0, 4.0, 35)
            lat_offset = side * (4.2 + 1.2 * math.sin(0.08 * p[0] + 0.06 * p[1]))
            max_h = 2.2 + 2.5 * abs(math.cos(0.11 * p[0] - 0.09 * p[1]))
            z_w = p[2] + rng.uniform(0.1, max_h, 35)
            wall = p[None, :] + u_w[:, None] * fwd[None, :] + lat_offset * left[None, :]
            wall[:, 2] = z_w
            pts_list.append(wall)

    all_pts = np.vstack(pts_list)
    # Voxel subsample landmarks to ~0.35 m resolution
    from ..pointcloud import voxel_downsample

    idx = voxel_downsample(all_pts.astype(np.float32), 0.35, max_points=35_000)
    return all_pts[idx].astype(np.float64)


def compute_ate_rpe(est_poses: np.ndarray, gt_poses: np.ndarray) -> dict:
    """Compute Umeyama-aligned SE(3) Absolute Trajectory Error (ATE) and Relative Pose Error (RPE)."""
    est_xyz = est_poses[:, :3, 3]
    gt_xyz = gt_poses[:, :3, 3]
    _, R_align, t_align = umeyama(est_xyz, gt_xyz, with_scale=False)
    est_aligned = (est_xyz @ R_align.T) + t_align
    ate_err = np.linalg.norm(est_aligned - gt_xyz, axis=1)

    # Relative Pose Error (RPE) across consecutive keyframes
    rpe_trans: list[float] = []
    rpe_rot_deg: list[float] = []
    for i in range(len(est_poses) - 1):
        dT_gt = np.linalg.inv(gt_poses[i]) @ gt_poses[i + 1]
        dT_est = np.linalg.inv(est_poses[i]) @ est_poses[i + 1]
        dT_err = np.linalg.inv(dT_gt) @ dT_est
        rpe_trans.append(float(np.linalg.norm(dT_err[:3, 3])))
        rpe_rot_deg.append(math.degrees(float(np.linalg.norm(so3_log(dT_err[:3, :3])))))

    return {
        "ate_rmse_m": round(float(np.sqrt(np.mean(ate_err ** 2))), 4),
        "ate_mean_m": round(float(np.mean(ate_err)), 4),
        "ate_median_m": round(float(np.median(ate_err)), 4),
        "ate_std_m": round(float(np.std(ate_err)), 4),
        "ate_max_m": round(float(np.max(ate_err)), 4),
        "rpe_trans_rmse_m": round(float(np.sqrt(np.mean(np.square(rpe_trans)))), 4),
        "rpe_rot_rmse_deg": round(float(np.sqrt(np.mean(np.square(rpe_rot_deg)))), 4),
        "aligned_xyz": est_aligned,
        "ate_series": ate_err,
    }


def evaluate_m2dgr_sequence(seq_name: str, gt_path: Path, seed: int = 10) -> dict:
    """Simulated keyframes along an M2DGR GT path: drifted odometry vs. loop closure + pose graph."""
    rng = np.random.default_rng(seed)
    t_kf, gt_poses, total_len_m = load_m2dgr_trajectory(gt_path, max_keyframes=44)
    n_kf = len(gt_poses)
    world_landmarks = _build_environment_landmarks(gt_poses, seed=seed)
    lm_tree = cKDTree(world_landmarks)

    # Extract local LiDAR scan at each keyframe and simulate realistic IMU + LIO drift
    # Handsfree A9 IMU noise parameters from M2DGR calibration_results.txt
    calib = SensorCalibration(
        gyr_noise=2.3418e-3,
        gyr_bias_walk=1.4428e-5,
        acc_noise=3.7686e-2,
        acc_bias_walk=1.1417e-3,
    )
    cfg = ForgeConfig(
        voxel_size_m=0.25,
        sc_distance_thresh=0.38,
        loop_min_time_s=15.0,
        loop_min_dist_m=20.0,
        sensor_height_m=1.5,
    )

    # Build drifted LIO trajectory by integrating relative motions with realistic IMU gyro/accel bias drift
    lio_poses = np.zeros_like(gt_poses)
    lio_poses[0] = gt_poses[0].copy()
    gyr_bias = np.array([0.0002, -0.00015, 0.0011], dtype=np.float64)
    pos_drift_rate = np.array([0.0035, -0.0025, 0.0005], dtype=np.float64)

    keyframes_lio: list[Keyframe] = []
    keyframes_forge: list[Keyframe] = []

    t_lio_ms = 0.0
    for i in range(n_kf):
        t0 = time.perf_counter_ns()
        T_gt = gt_poses[i]
        # Crop local 3D scan within 28 m radius in true body frame
        near_idx = lm_tree.query_ball_point(T_gt[:3, 3], r=28.0)
        pts_w = world_landmarks[near_idx]
        T_bw_gt = np.linalg.inv(T_gt)
        pts_local = ((pts_w @ T_bw_gt[:3, :3].T) + T_bw_gt[:3, 3]).astype(np.float32)
        # Add 1.5 cm Velodyne VLP-32C range noise
        pts_local += rng.normal(0.0, 0.015, size=pts_local.shape).astype(np.float32)

        if i > 0:
            dt = max(float(t_kf[i] - t_kf[i - 1]), 0.1)
            dT_gt = np.linalg.inv(gt_poses[i - 1]) @ gt_poses[i]
            step_len = float(np.linalg.norm(dT_gt[:3, 3]))
            # Realistic IMU-LiDAR odometry increment with small rotational + translational drift
            drot_noise = so3_exp(gyr_bias * min(dt, 2.5) + rng.normal(0.0, 0.002, 3))
            dtrans_noise = dT_gt[:3, 3] + pos_drift_rate * step_len + rng.normal(0.0, 0.012, 3)
            dT_noisy = np.eye(4, dtype=np.float64)
            dT_noisy[:3, :3] = dT_gt[:3, :3] @ drot_noise
            dT_noisy[:3, 3] = dtrans_noise
            lio_poses[i] = lio_poses[i - 1] @ dT_noisy
        t_lio_ms += (time.perf_counter_ns() - t0) / 1e6

        keyframes_lio.append(
            Keyframe(
                id=i,
                t=float(t_kf[i]),
                pose_w_b=lio_poses[i].copy(),
                points_local=pts_local.copy(),
                raw_points_local=pts_local.copy(),
                dynamic_mask=np.zeros(len(pts_local), dtype=bool),
            )
        )
        keyframes_forge.append(
            Keyframe(
                id=i,
                t=float(t_kf[i]),
                pose_w_b=lio_poses[i].copy(),
                points_local=pts_local.copy(),
                raw_points_local=pts_local.copy(),
                dynamic_mask=np.zeros(len(pts_local), dtype=bool),
            )
        )

    # Run LoopClosureDetector + GTSAM iSAM2 PoseGraphOptimizer on keyframes_forge
    t0_loop = time.perf_counter_ns()
    detector = LoopClosureDetector(config=cfg)
    pgo = PoseGraphOptimizer()
    accepted_loops: list[LoopConstraint] = []

    for i, kf in enumerate(keyframes_forge):
        pgo.add_keyframe(kf.id, kf.pose_w_b, is_first=(i == 0))
        if i > 0:
            T_rel = np.linalg.inv(keyframes_forge[i - 1].pose_w_b) @ kf.pose_w_b
            pgo.add_odometry_factor(keyframes_forge[i - 1].id, kf.id, T_rel)
        detector.add_keyframe(kf)
        if i >= 4:
            loops = detector.detect_for_keyframe(keyframes_forge, i)
            for lc in loops:
                accepted_loops.append(lc)
                pgo.add_loop_factor(lc)
    t_loop_ms = (time.perf_counter_ns() - t0_loop) / 1e6

    t0_pgo = time.perf_counter_ns()
    opt_poses_dict, pgo_tel = pgo.optimize()
    t_pgo_ms = (time.perf_counter_ns() - t0_pgo) / 1e6

    forge_poses = np.stack([opt_poses_dict[i] for i in range(n_kf)], axis=0)

    lio_metrics = compute_ate_rpe(lio_poses, gt_poses)
    forge_metrics = compute_ate_rpe(forge_poses, gt_poses)

    # Ground-truth loop-closure precision & recall analysis
    # A keyframe revisits if some earlier keyframe (time/path gaps satisfied) is < 3 m away in truth
    cum_d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(gt_poses[:, :3, 3], axis=0), axis=1))])
    revisits = set()
    for i in range(4, n_kf):
        for j in range(i - 1):
            if abs(t_kf[i] - t_kf[j]) >= cfg.loop_min_time_s and abs(cum_d[i] - cum_d[j]) >= cfg.loop_min_dist_m:
                if float(np.linalg.norm(gt_poses[i, :3, 3] - gt_poses[j, :3, 3])) < 3.0:
                    revisits.add(i)
                    break
    gt_loop_queries = len(revisits)

    tp_loops = 0
    fp_loops = 0
    closed = set()
    for lc in accepted_loops:
        T_true = np.linalg.inv(gt_poses[lc.from_id]) @ gt_poses[lc.to_id]
        if float(np.linalg.norm((np.linalg.inv(T_true) @ lc.T_from_to)[:3, 3])) < 0.5:  # correct relative pose
            tp_loops += 1
            closed.add(lc.to_id)
        else:
            fp_loops += 1

    precision = round(tp_loops / (tp_loops + fp_loops), 4) if (tp_loops + fp_loops) else None
    recall = round(len(revisits & closed) / len(revisits), 4) if revisits else None

    ate_red_pct = round(
        (lio_metrics["ate_rmse_m"] - forge_metrics["ate_rmse_m"]) / max(lio_metrics["ate_rmse_m"], 1e-6) * 100.0,
        1,
    )

    return {
        "sequence": seq_name,
        "total_length_m": round(total_len_m, 1),
        "keyframes": n_kf,
        "lio_only": {k: v for k, v in lio_metrics.items() if k not in ("aligned_xyz", "ate_series")},
        "forge_slam": {k: v for k, v in forge_metrics.items() if k not in ("aligned_xyz", "ate_series")},
        "ate_reduction_pct": ate_red_pct,
        "loops_accepted": len(accepted_loops),
        "loop_tp": tp_loops,
        "loop_fp": fp_loops,
        "gt_loop_Events": gt_loop_queries,
        "loop_precision": precision,
        "loop_recall": recall,
        "pgo_error_reduction_pct": pgo_tel["error_reduction_pct"],
        "timing_ms": {
            "lio_ms": round(t_lio_ms, 2),
            "loop_detection_ms": round(t_loop_ms, 2),
            "pose_graph_ms": round(t_pgo_ms, 2),
        },
        "_plot": {
            "gt_xyz": gt_poses[:, :3, 3],
            "lio_xyz": lio_metrics["aligned_xyz"],
            "forge_xyz": forge_metrics["aligned_xyz"],
            "lio_ate": lio_metrics["ate_series"],
            "forge_ate": forge_metrics["ate_series"],
            "loops": [(lc.from_id, lc.to_id) for lc in accepted_loops],
        },
        "_keyframes": keyframes_forge,
    }




def run_synthetic_sanity_check(datasets_dir: Path | None = None, out_json: Path | None = None) -> dict:
    """Run the simulation on every M2DGR GT path available and write JSON (no report, no figures)."""
    ds_dir = Path(datasets_dir) if datasets_dir else default_datasets_dir()
    out_json = Path(out_json) if out_json else ds_dir / "eval_logs" / "synthetic_sanity.json"
    results = []
    for name, seed in (("gate_01", 11), ("gate_02", 22), ("street_03", 33), ("street_04", 44)):
        path = ds_dir / "m2dgr" / f"GT_{name}.txt"
        if path.is_file():
            r = evaluate_m2dgr_sequence(name, path, seed=seed)
            results.append({k: v for k, v in r.items() if not k.startswith("_")})
    report = {"method": __doc__.strip(), "sequences": results}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

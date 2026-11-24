"""Stage 7B: End-to-End FORGE SLAM Pipeline Orchestrator (`run_forge_slam`).

Orchestrates Stages 1–6:
1. 15-DOF ESKF LiDAR-Inertial Odometry (`eskf_lio.py`)
2. Ground-Protected Temporal Dynamic Object Removal (`dynamic_filter.py`)
3. Scan-Context + `small_gicp` Loop Closure Detection (`loop_closure.py`)
4. GTSAM iSAM2 Keyframe Pose Graph Optimization (`pose_graph.py`)
5. Bounded-RAM Spatial Tile Memory with LRU `RAM <-> SSD` Hot-Swap (`memory.py`)
6. Radiometric Thermal (°C) + RGB Z-Buffer Registration (`thermal_reg.py`) and
   Keyframe-Anchored 3D Gaussian Splatting (`gsplat.py`)
"""

from __future__ import annotations

import json
from pathlib import Path
import time
import numpy as np

from ..pointcloud import Reconstruction
from .dynamic_filter import TemporalDynamicFilter
from .eskf_lio import ESKFLIO
from .gsplat import train_and_eval_gsplat
from .io import load_forge_sequence
from .loop_closure import LoopClosureDetector
from .memory import SpatialTileMemory
from .pose_graph import PoseGraphOptimizer
from .thermal_reg import register_rgb_and_thermal
from .types import ForgeConfig, ForgeResult, Keyframe, LoopConstraint


def run_forge_slam(
    input_dir: Path,
    work_dir: Path,
    config: ForgeConfig | None = None,
    gps: np.ndarray | None = None,
) -> ForgeResult:
    """Execute the full FORGE SLAM pipeline on a multi-sensor sequence directory."""
    t_start_ns = time.perf_counter_ns()
    cfg = config or ForgeConfig()
    input_dir = Path(input_dir)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    calib, imu_samples, lidar_scans, rgb_frames, thr_frames, seq_gps, _ = load_forge_sequence(input_dir)
    if gps is None:
        gps = seq_gps

    # Stage 1: 15-DOF ESKF LiDAR-Inertial Odometry
    t0 = time.perf_counter_ns()
    lio = ESKFLIO(calib=calib, config=cfg)
    keyframes: list[Keyframe] = []
    imu_idx = 0
    n_imu = len(imu_samples)
    if n_imu > 0 and lidar_scans:
        first_t = min(imu_samples[0].t, lidar_scans[0].t)
        lio.predict_imu(first_t, imu_samples[0].gyro, imu_samples[0].accel)

    last_tel = {}
    for scan_i, scan in enumerate(lidar_scans):
        while imu_idx < n_imu and imu_samples[imu_idx].t <= scan.t:
            s = imu_samples[imu_idx]
            lio.predict_imu(s.t, s.gyro, s.accel)
            imu_idx += 1
        pose_wb, deskewed_local, last_tel = lio.update_lidar(scan)
        keyframes.append(
            Keyframe(
                id=scan_i,
                t=scan.t,
                pose_w_b=pose_wb.copy(),
                points_local=deskewed_local.copy(),
                raw_points_local=deskewed_local.copy(),
                dynamic_mask=np.zeros(len(deskewed_local), dtype=bool),
            )
        )
    t_eskf_ms = (time.perf_counter_ns() - t0) / 1e6

    # Stage 2: Ground-Protected Temporal Dynamic Object Removal
    t0 = time.perf_counter_ns()
    dyn_filter = TemporalDynamicFilter(config=cfg)
    if cfg.enable_dynamic_filter and len(keyframes) >= 2:
        for idx in range(len(keyframes)):
            dyn_filter.filter_keyframe_window(keyframes, idx)
    t_dyn_ms = (time.perf_counter_ns() - t0) / 1e6

    # Stage 3 & 4: Scan-Context + small_gicp Loop Closure & GTSAM iSAM2 Pose Graph
    t0 = time.perf_counter_ns()
    pgo = PoseGraphOptimizer()
    loop_detector = LoopClosureDetector(config=cfg)
    loop_constraints: list[LoopConstraint] = []
    for i, kf in enumerate(keyframes):
        pgo.add_keyframe(kf.id, kf.pose_w_b, is_first=(i == 0))
        if i > 0:
            T_rel = np.linalg.inv(keyframes[i - 1].pose_w_b) @ kf.pose_w_b
            pgo.add_odometry_factor(keyframes[i - 1].id, kf.id, T_rel)
        loop_detector.add_keyframe(kf)
        if cfg.enable_loop_closure and i >= 3:
            found_loops = loop_detector.detect_for_keyframe(keyframes, i)
            for lc in found_loops:
                loop_constraints.append(lc)
                pgo.add_loop_factor(lc)
    t_loop_ms = (time.perf_counter_ns() - t0) / 1e6

    t0 = time.perf_counter_ns()
    opt_poses, pgo_tel = pgo.optimize()
    for kf in keyframes:
        if kf.id in opt_poses:
            kf.pose_w_b = opt_poses[kf.id].copy()
    t_pgo_ms = (time.perf_counter_ns() - t0) / 1e6

    # Stage 5: Bounded-RAM Spatial Tile Memory with LRU RAM <-> SSD Hot-Swap
    t0 = time.perf_counter_ns()
    mem = SpatialTileMemory(
        tiles_dir=work_dir / "forge_tiles",
        tile_size_m=cfg.tile_size_m,
        max_ram_bytes=cfg.max_ram_bytes,
    )
    for kf in keyframes:
        mem.insert_keyframe_points(kf.id, kf.pose_w_b, kf.points_local)
    mem.update_poses({kf.id: kf.pose_w_b for kf in keyframes})
    pts_w, _, _ = mem.export_world_cloud(voxel_size_m=0.04)
    t_mem_ms = (time.perf_counter_ns() - t0) / 1e6

    # Stage 6A: Radiometric Thermal (°C) + RGB Z-Buffer Registration
    t0 = time.perf_counter_ns()
    colors_w, temps_w, thermal_stats = register_rgb_and_thermal(
        pts_w,
        keyframes,
        rgb_frames,
        thr_frames if cfg.enable_thermal else [],
    )
    t_thermal_ms = (time.perf_counter_ns() - t0) / 1e6

    # Stage 6B: Keyframe-Anchored 3D Gaussian Splatting (RGB + Thermal °C)
    t0 = time.perf_counter_ns()
    gsplat_metrics = {}
    if cfg.enable_gsplat and len(pts_w) > 0:
        splat_model, gsplat_metrics = train_and_eval_gsplat(
            pts_w,
            colors_w,
            temps_w,
            keyframes,
            rgb_frames,
            thr_frames,
            min_free_gpu_gb=cfg.min_free_gpu_gb,
            max_gaussians=cfg.max_gaussians,
            iters=12,
        )
        splat_model.save(work_dir / "splats.npz")
    t_gsplat_ms = (time.perf_counter_ns() - t0) / 1e6

    # Save audit artifacts
    all_dyn_masks = np.concatenate([kf.dynamic_mask for kf in keyframes]) if keyframes else np.zeros(0, dtype=bool)
    np.savez_compressed(work_dir / "dynamic_mask.npz", dynamic_mask=all_dyn_masks)

    total_ms = (time.perf_counter_ns() - t_start_ns) / 1e6
    diagnostics = {
        "keyframes": len(keyframes),
        "static_points": int(len(pts_w)),
        "dynamic_points_removed": int(np.count_nonzero(all_dyn_masks)),
        "loop_closures_accepted": len(loop_constraints),
        "loop_summary": loop_detector.summary(),
        "pose_graph": pgo_tel,
        "eskf_last": last_tel,
        "memory": mem.stats(),
        "thermal": thermal_stats,
        "gsplat": gsplat_metrics,
        "timing_ms": {
            "eskf_lio": round(t_eskf_ms, 2),
            "dynamic_filter": round(t_dyn_ms, 2),
            "loop_closure": round(t_loop_ms, 2),
            "pose_graph": round(t_pgo_ms, 2),
            "tile_memory": round(t_mem_ms, 2),
            "thermal_reg": round(t_thermal_ms, 2),
            "gsplat": round(t_gsplat_ms, 2),
            "total": round(total_ms, 2),
        },
    }
    (work_dir / "forge_diagnostics.json").write_text(json.dumps(diagnostics, indent=2))

    poses_arr = np.stack([kf.pose_w_b for kf in keyframes], axis=0) if keyframes else None
    times_arr = np.array([kf.t for kf in keyframes], dtype=np.float64) if keyframes else None

    rec = Reconstruction(
        points=pts_w.astype(np.float32),
        colors=colors_w.astype(np.uint8),
        poses=poses_arr,
        times=times_arr,
        gps=gps,
        temperatures_c=temps_w.astype(np.float32) if (cfg.enable_thermal and len(thr_frames) > 0) else None,
        meta={
            "metric": True,
            "up_axis": "z",
            "decoder": "forge_slam",
            "scale_info": {"method": "metric"},
            "forge_slam": diagnostics,
        },
    )

    return ForgeResult(
        reconstruction=rec,
        keyframes=keyframes,
        loop_constraints=loop_constraints,
        dynamic_mask=all_dyn_masks,
        diagnostics=diagnostics,
    )

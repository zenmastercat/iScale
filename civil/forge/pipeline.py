"""FORGE SLAM orchestrator: a streaming `ForgeSlam` plus the folder-based `run_forge_slam` entry point.

Data flow (all in time order):
1. IMU samples before the first scan level the filter on gravity (static start) and are then integrated.
2. Every LiDAR scan updates the ESKF LIO; a keyframe is taken every `keyframe_dist_m` / `keyframe_angle_deg`.
3. A keyframe is finalised once 3 newer keyframes exist: temporal dynamic filter over +-3 keyframes, Scan-Context
   + G-ICP loop search, pose-graph factors, and its static points go to the RAM/SSD tile memory. Its raw scan is
   then dropped (a 0.2 m copy stays for loop closure), so RAM holds only a short window of raw scans.
4. `finish()` optimises the pose graph, re-poses the tiles, exports the map and registers RGB / thermal frames
   against the per-scan trajectory corrected by the optimised keyframes.
"""

from __future__ import annotations

import json
import resource
import time
from pathlib import Path

import numpy as np

from ..pointcloud import Reconstruction, voxel_downsample
from .dynamic_filter import TemporalDynamicFilter
from .eskf_lio import ESKFLIO
from .gsplat import train_and_eval_gsplat
from .io import load_forge_sequence
from .loop_closure import LoopClosureDetector
from .memory import SpatialTileMemory
from .pose_graph import PoseGraphOptimizer
from .thermal_reg import register_rgb_and_thermal
from .types import CameraFrame, ForgeConfig, ForgeResult, ImuSample, Keyframe, LidarScan, LoopConstraint, SensorCalibration

WINDOW = 3            # keyframes on each side used by the dynamic filter
LOOP_VOXEL_M = 0.2    # resolution of the per-keyframe copy kept for loop closure


class ForgeSlam:
    """Feed IMU samples, LiDAR scans and camera frames in time order, then call `finish()`."""

    def __init__(self, calib: SensorCalibration, work_dir: Path, config: ForgeConfig | None = None) -> None:
        self.cfg = config or ForgeConfig()
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.lio = ESKFLIO(calib=calib, config=self.cfg)
        self.dyn = TemporalDynamicFilter(self.cfg)
        self.loops = LoopClosureDetector(self.cfg)
        self.pgo = PoseGraphOptimizer()
        self.mem = SpatialTileMemory(self.work_dir / "forge_tiles", self.cfg.tile_size_m, self.cfg.max_ram_bytes)
        self.keyframes: list[Keyframe] = []
        self.loop_constraints: list[LoopConstraint] = []
        self.rgb_frames: list[CameraFrame] = []
        self.thr_frames: list[CameraFrame] = []
        self._n_final = 0
        self._pending_imu: list[ImuSample] = []
        self._started = False
        self.static_init = False
        # per-scan trajectory: time, odometry pose, anchor keyframe id
        self._traj_t: list[float] = []
        self._traj_T: list[np.ndarray] = []
        self._traj_kf: list[int] = []
        self.scan_ms: list[float] = []
        self.keyframe_ms: list[float] = []
        self.last_tel: dict = {}
        self.degenerate_scans = 0
        self.dyn_stats = {"input_points": 0, "removed_dynamic_points": 0}
        self.removed_points_w: list[np.ndarray] = []  # audit: world points the dynamic filter took out

    # ---- streaming inputs -------------------------------------------------
    def add_imu(self, s: ImuSample) -> None:
        if not self._started:
            self._pending_imu.append(s)
            return
        self.lio.predict_imu(s.t, s.gyro, s.accel)

    def add_camera(self, f: CameraFrame) -> None:
        frames = self.thr_frames if f.modality == "thermal" else self.rgb_frames
        if not self._started:
            return
        if frames and f.t - frames[-1].t < self.cfg.camera_min_interval_s:
            return
        frames.append(f)

    def add_scan(self, scan: LidarScan) -> None:
        t0 = time.perf_counter()
        if not self._started:
            self._started = True
            imu = self._pending_imu[-400:]
            if imu:
                self.static_init = self.lio.initialize_static(
                    np.array([s.gyro for s in imu]), np.array([s.accel for s in imu])
                )
                for s in imu:
                    self.lio.predict_imu(s.t, s.gyro, s.accel)
            self._pending_imu = []
        pose, pts_b, tel = self.lio.update_lidar(scan)
        self.last_tel = tel
        self.degenerate_scans += int(tel.get("degenerate", False))

        if self.dyn.should_create_keyframe(pose):
            self.dyn.record_keyframe_pose(pose)
            idx = voxel_downsample(pts_b, self.cfg.voxel_size_m)
            raw = np.ascontiguousarray(pts_b[idx], dtype=np.float32)
            self.keyframes.append(
                Keyframe(len(self.keyframes), float(scan.t), pose.copy(), raw, raw.copy(), np.zeros(len(raw), bool))
            )
            while len(self.keyframes) - self._n_final > WINDOW:
                self._finalize(self._n_final)
        self._traj_t.append(float(scan.t))
        self._traj_T.append(pose.copy())
        self._traj_kf.append(len(self.keyframes) - 1)
        self.scan_ms.append((time.perf_counter() - t0) * 1000.0)

    # ---- keyframe finalisation ---------------------------------------------
    def _finalize(self, i: int) -> None:
        t0 = time.perf_counter()
        kfs = self.keyframes
        kf = kfs[i]
        if self.cfg.enable_dynamic_filter and len(kfs) >= 2:
            _, mask, st = self.dyn.filter_keyframe_window(kfs, i)
            self.dyn_stats["input_points"] += st["input_points"]
            self.dyn_stats["removed_dynamic_points"] += st["removed_dynamic_points"]
            if mask.any():
                gone = kf.raw_points_local[mask].astype(np.float64)
                self.removed_points_w.append((gone @ kf.pose_w_b[:3, :3].T + kf.pose_w_b[:3, 3]).astype(np.float32))
        self.mem.insert_keyframe_points(kf.id, kf.pose_w_b, kf.points_local)

        keep = voxel_downsample(kf.points_local, LOOP_VOXEL_M)
        kf.points_local = np.ascontiguousarray(kf.points_local[keep])
        self.pgo.add_keyframe(kf.id, kf.pose_w_b, is_first=(i == 0))
        if i > 0:
            prev = kfs[i - 1]
            self.pgo.add_odometry_factor(prev.id, kf.id, np.linalg.inv(prev.pose_w_b) @ kf.pose_w_b)
        self.loops.add_keyframe(kf)
        if self.cfg.enable_loop_closure:
            for lc in self.loops.detect_for_keyframe(kfs, i):
                self.loop_constraints.append(lc)
                self.pgo.add_loop_factor(lc)
        if i >= WINDOW:  # no longer needed as a neighbour by any keyframe still to be filtered
            old = kfs[i - WINDOW]
            old.raw_points_local = np.zeros((0, 3), np.float32)
        self._n_final = i + 1
        self.keyframe_ms.append((time.perf_counter() - t0) * 1000.0)

    # ---- outputs -------------------------------------------------------------
    def corrected_trajectory(self) -> tuple[np.ndarray, np.ndarray]:
        """Per-scan poses, each re-anchored on its (optimised) keyframe."""
        odom_kf = {kf.id: T for kf, T in zip(self.keyframes, self._odom_kf_poses)}
        out = []
        for T, k in zip(self._traj_T, self._traj_kf):
            if k < 0:
                out.append(T)
                continue
            out.append(self.keyframes[k].pose_w_b @ np.linalg.inv(odom_kf[k]) @ T)
        return np.array(self._traj_t), np.array(out)

    def finish(self, gps: np.ndarray | None = None) -> ForgeResult:
        t0 = time.perf_counter()
        for i in range(self._n_final, len(self.keyframes)):
            self._finalize(i)
        self._odom_kf_poses = [kf.pose_w_b.copy() for kf in self.keyframes]
        pgo_tel: dict = {}
        if self.keyframes:
            opt, pgo_tel = self.pgo.optimize()
            for kf in self.keyframes:
                if kf.id in opt:
                    kf.pose_w_b = opt[kf.id].copy()
        self.mem.update_poses({kf.id: kf.pose_w_b for kf in self.keyframes})
        pts_w, _, _ = self.mem.export_world_cloud(voxel_size_m=0.04)
        traj = self.corrected_trajectory()
        t_map = time.perf_counter()

        colors_w, temps_w, thermal_stats = register_rgb_and_thermal(
            pts_w, self.keyframes, self.rgb_frames, self.thr_frames if self.cfg.enable_thermal else [], trajectory=traj
        )
        t_reg = time.perf_counter()
        gsplat_metrics: dict = {}
        if self.cfg.enable_gsplat and len(pts_w) and self.rgb_frames:
            model, gsplat_metrics = train_and_eval_gsplat(
                pts_w, colors_w, temps_w, self.keyframes, self.rgb_frames, self.thr_frames,
                max_gaussians=self.cfg.max_gaussians, iters=self.cfg.gsplat_iters, trajectory=traj,
            )
            model.save(self.work_dir / "splats.npz")
        t_end = time.perf_counter()

        dyn_masks = [kf.dynamic_mask for kf in self.keyframes]
        all_dyn = np.concatenate(dyn_masks) if dyn_masks else np.zeros(0, bool)
        removed = np.vstack(self.removed_points_w) if self.removed_points_w else np.zeros((0, 3), np.float32)
        np.savez_compressed(self.work_dir / "dynamic_mask.npz", dynamic_mask=all_dyn, removed_points_w_odom=removed)
        diagnostics = {
            "keyframes": len(self.keyframes),
            "scans": len(self._traj_t),
            "static_init": self.static_init,
            "degenerate_scans": self.degenerate_scans,
            "static_points": int(len(pts_w)),
            "dynamic_filter": self.dyn_stats,
            "loop_closures_accepted": len(self.loop_constraints),
            "loop_summary": self.loops.summary(),
            "pose_graph": pgo_tel,
            "eskf_last": self.last_tel,
            "memory": self.mem.stats(),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
            "thermal": thermal_stats,
            "gsplat": gsplat_metrics,
            "timing_ms": {
                "per_scan_median": round(float(np.median(self.scan_ms)), 2) if self.scan_ms else None,
                "per_scan_p95": round(float(np.percentile(self.scan_ms, 95)), 2) if self.scan_ms else None,
                "per_keyframe_median": round(float(np.median(self.keyframe_ms)), 2) if self.keyframe_ms else None,
                "optimise_and_export": round((t_map - t0) * 1000.0, 1),
                "camera_registration": round((t_reg - t_map) * 1000.0, 1),
                "splats": round((t_end - t_reg) * 1000.0, 1),
            },
        }
        (self.work_dir / "forge_diagnostics.json").write_text(json.dumps(diagnostics, indent=2, default=float))

        rec = Reconstruction(
            points=pts_w.astype(np.float32),
            colors=colors_w.astype(np.uint8),
            poses=np.stack([kf.pose_w_b for kf in self.keyframes]) if self.keyframes else None,
            times=np.array([kf.t for kf in self.keyframes]) if self.keyframes else None,
            gps=gps,
            temperatures_c=temps_w.astype(np.float32) if (self.cfg.enable_thermal and self.thr_frames) else None,
            meta={
                "metric": True,
                "up_axis": "z",
                "decoder": "forge_slam",
                "scale_info": {"method": "metric"},
                "forge_slam": diagnostics,
            },
        )
        return ForgeResult(rec, self.keyframes, self.loop_constraints, all_dyn, diagnostics)


def run_forge_slam(
    input_dir: Path,
    work_dir: Path,
    config: ForgeConfig | None = None,
    gps: np.ndarray | None = None,
) -> ForgeResult:
    """Run FORGE SLAM on a calibrated sequence folder (see io.load_forge_sequence)."""
    calib, imu, scans, rgb, thr, seq_gps, _ = load_forge_sequence(Path(input_dir))
    slam = ForgeSlam(calib, Path(work_dir), config)
    # rank 0 = IMU, 1 = scan, 2 = camera at equal times: IMU up to a scan is integrated before the scan
    events = [(s.t, 0, i) for i, s in enumerate(imu)] + [(s.t, 1, i) for i, s in enumerate(scans)]
    events += [(f.t, 2, i) for i, f in enumerate(rgb)] + [(f.t, 3, i) for i, f in enumerate(thr)]
    for _, kind, i in sorted(events):
        if kind == 0:
            slam.add_imu(imu[i])
        elif kind == 1:
            slam.add_scan(scans[i])
        elif kind == 2:
            slam.add_camera(rgb[i])
        else:
            slam.add_camera(thr[i])
    return slam.finish(gps if gps is not None else seq_gps)

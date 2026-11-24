"""TDD tests for FORGE SLAM Stages 3 & 4: Scan-Context + small_gicp Loop Closure and GTSAM iSAM2 Pose Graph."""

from __future__ import annotations

import math
import numpy as np


def _make_landmark_cloud(rng: np.random.Generator) -> np.ndarray:
    """Asymmetric 3D street intersection cloud (buildings/poles at distinct quadrants) for loop closure."""
    pts = []
    # Ground plane
    gx, gy = np.meshgrid(np.linspace(-25, 25, 70), np.linspace(-25, 25, 70))
    pts.append(np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]))
    # 4 asymmetric vertical landmark structures at different radii & heights
    landmarks = [
        (12.0, 5.0, 2.0, 3.0, 4.5),
        (-15.0, 10.0, 3.0, 2.0, 3.2),
        (8.0, -18.0, 1.5, 4.0, 5.5),
        (-9.0, -8.0, 2.5, 2.5, 2.8),
    ]
    for cx, cy, wx, wy, hz in landmarks:
        x = rng.uniform(cx - wx / 2, cx + wx / 2, 350)
        y = rng.uniform(cy - wy / 2, cy + wy / 2, 350)
        z = rng.uniform(0.2, hz, 350)
        pts.append(np.column_stack([x, y, z]))
    return np.vstack(pts).astype(np.float32)


def test_scan_context_rotation_invariance_and_loop_detector():
    from civil.forge.loop_closure import LoopClosureDetector, make_scan_context, scan_context_distance
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(123)
    base_cloud = _make_landmark_cloud(rng)

    # Rotate cloud by 72 degrees around +Z and add slight translation (0.6 m, -0.4 m)
    yaw_true = math.radians(72.0)
    c, s = math.cos(yaw_true), math.sin(yaw_true)
    R_z = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    t_shift = np.array([0.6, -0.4, 0.05], dtype=np.float64)
    # In sensor frame rotated by yaw_true and translated by t_shift:
    # p_w = R_z @ p_b + t_shift => p_b = R_z^T @ (p_w - t_shift)
    rotated_cloud = ((base_cloud.astype(np.float64) - t_shift) @ R_z).astype(np.float32)

    sc0, rk0 = make_scan_context(base_cloud)
    sc1, rk1 = make_scan_context(rotated_cloud)
    dist_sc, shift_col = scan_context_distance(sc0, sc1)
    assert dist_sc < 0.20, f"Scan-Context distance under pure rotation + small shift should be <0.20, got {dist_sc:.3f}"

    # Build a loop trajectory of 20 keyframes around a 20m x 20m block returning to origin at keyframe 19
    cfg = ForgeConfig(sc_distance_thresh=0.35, loop_min_time_s=10.0, loop_min_dist_m=10.0)
    det = LoopClosureDetector(cfg)
    keyframes: list[Keyframe] = []

    waypoints = [
        (0.0, 0.0, 0.0),
        (5.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (15.0, 0.0, 0.5),
        (15.0, 5.0, 1.57),
        (15.0, 10.0, 1.57),
        (15.0, 15.0, 2.2),
        (10.0, 15.0, 3.14),
        (5.0, 15.0, 3.14),
        (0.0, 15.0, 3.8),
        (0.0, 10.0, 4.71),
        (0.0, 5.0, 4.71),
        (0.5, -0.3, math.radians(35.0)),  # Returns near origin (0,0) with 35 deg yaw difference!
    ]

    for k, (x, y, yaw) in enumerate(waypoints):
        ck, sk = math.cos(yaw), math.sin(yaw)
        T_true = np.eye(4, dtype=np.float64)
        T_true[:3, :3] = [[ck, -sk, 0], [sk, ck, 0], [0, 0, 1]]
        T_true[:3, 3] = [x, y, 0.0]

        # Sensor observes world landmarks within 30 m in its local body frame
        rel = base_cloud.astype(np.float64) - T_true[:3, 3]
        in_range = np.linalg.norm(rel, axis=1) <= 30.0
        pts_local = (rel[in_range] @ T_true[:3, :3]).astype(np.float32)

        # Add cumulative drift to the odometry pose of keyframe k
        T_odom = T_true.copy()
        T_odom[:3, 3] += np.array([0.08 * k, -0.05 * k, 0.01 * k])

        kf = Keyframe(
            id=k,
            t=float(k * 3.0),
            pose_w_b=T_odom,
            points_local=pts_local,
            raw_points_local=pts_local,
            dynamic_mask=np.zeros(len(pts_local), dtype=bool),
        )
        det.add_keyframe(kf)
        keyframes.append(kf)

    # Detect loop closure on the final keyframe (id=12, t=36s, returning to id=0 at t=0s)
    loops = det.detect_for_keyframe(keyframes, query_idx=len(keyframes) - 1)
    assert len(loops) >= 1, f"Expected loop closure at return to origin; audit={det.audit_log[-3:]}"
    lc = loops[0]
    assert lc.from_id == 0 and lc.to_id == len(keyframes) - 1
    assert lc.inlier_ratio >= 0.45
    assert lc.rmse <= 0.35

    # Verify relative transform T_from_to matches T_0^{-1} T_12_true = (0.5, -0.3, 0, yaw=35 deg)
    np.testing.assert_allclose(lc.T_from_to[:3, 3], [0.5, -0.3, 0.0], atol=0.12)


def test_gtsam_pose_graph_reduces_loop_ate_by_over_60_percent():
    from civil.forge.pose_graph import PoseGraphOptimizer
    from civil.forge.types import LoopConstraint

    # Create a 40-keyframe closed square loop (perimeter 80 m) with 2.5 m accumulated drift
    n_kf = 40
    true_poses: list[np.ndarray] = []
    odom_poses: list[np.ndarray] = []

    pg = PoseGraphOptimizer()
    T_odom_curr = np.eye(4, dtype=np.float64)

    for k in range(n_kf):
        side = k // 10
        step = k % 10
        if side == 0:
            x, y, yaw = step * 2.0, 0.0, 0.0
        elif side == 1:
            x, y, yaw = 20.0, step * 2.0, math.pi / 2
        elif side == 2:
            x, y, yaw = 20.0 - step * 2.0, 20.0, math.pi
        else:
            x, y, yaw = 0.0, 20.0 - step * 2.0, -math.pi / 2

        c, s = math.cos(yaw), math.sin(yaw)
        T_true = np.eye(4, dtype=np.float64)
        T_true[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
        T_true[:3, 3] = [x, y, 0.0]
        true_poses.append(T_true)

        if k == 0:
            T_odom_curr = T_true.copy()
            odom_poses.append(T_odom_curr.copy())
            pg.add_keyframe(0, T_odom_curr, is_first=True)
        else:
            T_rel_true = np.linalg.inv(true_poses[k - 1]) @ T_true
            # Add systematic drift per step (0.04 m translation + 0.004 rad yaw + 0.015 m z)
            cd, sd = math.cos(0.004), math.sin(0.004)
            T_drift = np.eye(4, dtype=np.float64)
            T_drift[:3, :3] = [[cd, -sd, 0], [sd, cd, 0], [0, 0, 1]]
            T_drift[:3, 3] = [0.03, 0.02, 0.015]
            T_rel_odom = T_rel_true @ T_drift
            T_odom_curr = T_odom_curr @ T_rel_odom
            odom_poses.append(T_odom_curr.copy())
            pg.add_keyframe(k, T_odom_curr, is_first=False)
            pg.add_odometry_factor(k - 1, k, T_rel_odom)

    # Add true loop closure between keyframe 0 and keyframe 39
    T_0_39_true = np.linalg.inv(true_poses[0]) @ true_poses[-1]
    lc = LoopConstraint(from_id=0, to_id=n_kf - 1, T_from_to=T_0_39_true, rmse=0.04, inlier_ratio=0.92, sc_distance=0.11)
    assert pg.add_loop_factor(lc)

    opt_poses, stats = pg.optimize()

    true_xyz = np.array([T[:3, 3] for T in true_poses])
    odom_xyz = np.array([T[:3, 3] for T in odom_poses])
    opt_xyz = np.array([opt_poses[k][:3, 3] for k in range(n_kf)])

    rmse_before = float(np.sqrt(np.mean(np.sum((odom_xyz - true_xyz) ** 2, axis=1))))
    rmse_after = float(np.sqrt(np.mean(np.sum((opt_xyz - true_xyz) ** 2, axis=1))))
    assert rmse_after < 0.35 * rmse_before, f"Expected >65% ATE reduction, got {rmse_before:.3f}m -> {rmse_after:.3f}m"
    assert stats["num_poses"] == n_kf

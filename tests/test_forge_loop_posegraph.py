"""TDD tests for FORGE SLAM Stages 3 & 4: Scan-Context + small_gicp Loop Closure and GTSAM iSAM2 Pose Graph."""

from __future__ import annotations

import math
import numpy as np


def _make_landmark_cloud(rng: np.random.Generator) -> np.ndarray:
    pts = []
    gx, gy = np.meshgrid(np.linspace(-25, 25, 70), np.linspace(-25, 25, 70))
    pts.append(np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]))
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

    yaw_true = math.radians(72.0)
    c, s = math.cos(yaw_true), math.sin(yaw_true)
    R_z = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    t_shift = np.array([0.6, -0.4, 0.05], dtype=np.float64)
    rotated_cloud = ((base_cloud.astype(np.float64) - t_shift) @ R_z).astype(np.float32)

    sc0, _ = make_scan_context(base_cloud)
    sc1, _ = make_scan_context(rotated_cloud)
    dist_sc, _ = scan_context_distance(sc0, sc1)
    assert dist_sc < 0.20

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
        (0.5, -0.3, math.radians(35.0)),
    ]

    for k, (x, y, yaw) in enumerate(waypoints):
        ck, sk = math.cos(yaw), math.sin(yaw)
        T_true = np.eye(4, dtype=np.float64)
        T_true[:3, :3] = [[ck, -sk, 0], [sk, ck, 0], [0, 0, 1]]
        T_true[:3, 3] = [x, y, 0.0]

        rel = base_cloud.astype(np.float64) - T_true[:3, 3]
        in_range = np.linalg.norm(rel, axis=1) <= 30.0
        pts_local = (rel[in_range] @ T_true[:3, :3]).astype(np.float32)

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

    loops = det.detect_for_keyframe(keyframes, query_idx=len(keyframes) - 1)
    assert len(loops) >= 1
    lc = loops[0]
    assert lc.from_id == 0 and lc.to_id == len(keyframes) - 1
    assert lc.inlier_ratio >= 0.45 and lc.rmse <= 0.35
    np.testing.assert_allclose(lc.T_from_to[:3, 3], [0.5, -0.3, 0.0], atol=0.12)


def _street_cloud(rng: np.random.Generator, boxes: list[tuple[float, float]]) -> np.ndarray:
    """Flat ground plus 2.5 m-tall boxes (parked vans, kiosks) at the given (x, y) centres."""
    gx, gy = np.meshgrid(np.linspace(-25, 25, 90), np.linspace(-25, 25, 90))
    pts = [np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])]
    for cx, cy in boxes:
        pts.append(np.column_stack([rng.uniform(cx - 1, cx + 1, 400), rng.uniform(cy - 1, cy + 1, 400), rng.uniform(0.2, 2.5, 400)]))
    return np.vstack(pts).astype(np.float32)


def test_look_alike_place_rejected_by_structure_fitness():
    """Same kind of street, objects 2-4 m elsewhere: Scan-Context may match, the ground always aligns,
    but the above-ground structure does not -> no loop."""
    from civil.forge.loop_closure import LoopClosureDetector
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(55)
    place_a = _street_cloud(rng, [(10, 6), (-12, 9), (6, -14), (-8, -8), (15, -5)])
    place_b = _street_cloud(rng, [(12, 9), (-9, 12), (9, -11), (-11, -6), (12, -8)])
    cfg = ForgeConfig(sc_distance_thresh=0.9, loop_min_time_s=5.0, loop_min_dist_m=5.0)
    det = LoopClosureDetector(cfg)
    kfs = []
    for k in range(5):
        T = np.eye(4)
        T[0, 3] = k * 4.0
        pts = place_a if k == 0 else (place_b if k == 4 else _street_cloud(rng, []))
        kfs.append(Keyframe(k, float(k * 3.0), T, pts, pts, np.zeros(len(pts), bool)))
        det.add_keyframe(kfs[-1])

    assert det.detect_for_keyframe(kfs, query_idx=4) == []
    decisions = [r["decision"] for r in det.audit_log]
    assert "REJECTED_FITNESS_SCORE" in decisions or "REJECTED_INLIER_RATIO" in decisions, decisions


def test_revisit_with_large_offset_rejected_by_overlap_gate():
    """A verified alignment more than loop_max_offset_m away is not accepted, however long the path between."""
    from civil.forge.loop_closure import LoopClosureDetector
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(8)
    world = _street_cloud(rng, [(10, 6), (-12, 9), (6, -14), (-8, -8), (15, -5), (25, 3), (30, -6), (22, 12)])
    cfg = ForgeConfig(sc_distance_thresh=0.9, loop_min_time_s=5.0, loop_min_dist_m=5.0, loop_max_offset_m=10.0)
    det = LoopClosureDetector(cfg)
    kfs = []
    for k, x in enumerate([0.0, 40.0, 80.0, 120.0, 14.0]):  # the last keyframe revisits the start, 14 m off
        T = np.eye(4)
        T[0, 3] = x
        pts = (world - np.array([x, 0.0, 0.0], np.float32)) if k in (0, 4) else _street_cloud(rng, [])
        kfs.append(Keyframe(k, float(k * 30.0), T, pts, pts, np.zeros(len(pts), bool)))
        det.add_keyframe(kfs[-1])
    assert det.detect_for_keyframe(kfs, query_idx=4) == []
    assert "REJECTED_OFFSET" in [r["decision"] for r in det.audit_log]


def test_true_loop_detected_and_pose_graph_reduces_drift_end_to_end():
    from civil.forge.loop_closure import LoopClosureDetector
    from civil.forge.pose_graph import PoseGraphOptimizer
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(21)
    boxes = [(rng.uniform(-40, 60), rng.uniform(-40, 60)) for _ in range(60)]
    gx, gy = np.meshgrid(np.linspace(-45, 65, 160), np.linspace(-45, 65, 160))
    world = np.vstack([np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])] + [
        np.column_stack([rng.uniform(cx - 1, cx + 1, 300), rng.uniform(cy - 1, cy + 1, 300), rng.uniform(0.2, 3.0, 300)])
        for cx, cy in boxes])

    # 20 m square loop, keyframes every 2 m; odometry drifts 0.4 deg of yaw per keyframe
    true_T, odom_T = [], []
    T_odom = np.eye(4)
    for k in range(41):
        side, step = divmod(k, 10)
        x, y = [(step * 2.0, 0.0), (20.0, step * 2.0), (20.0 - step * 2.0, 20.0), (0.0, 20.0 - step * 2.0), (0.0, 0.0)][side]
        T = np.eye(4)
        yaw = [0.0, math.pi / 2, math.pi, -math.pi / 2, 0.0][side]
        T[:3, :3] = [[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]]
        T[:3, 3] = [x, y, 0.0]
        if k:
            d = np.linalg.inv(true_T[-1]) @ T
            drift = np.eye(4)
            drift[:3, :3] = [[math.cos(0.007), -math.sin(0.007), 0], [math.sin(0.007), math.cos(0.007), 0], [0, 0, 1]]
            T_odom = T_odom @ d @ drift
        true_T.append(T)
        odom_T.append(T_odom.copy())

    cfg = ForgeConfig(loop_min_time_s=20.0, loop_min_dist_m=20.0)
    det = LoopClosureDetector(cfg)
    pg = PoseGraphOptimizer()
    kfs, loops = [], []
    for k in range(41):
        rel = world - true_T[k][:3, 3]
        pts = (rel[np.linalg.norm(rel, axis=1) < 30.0] @ true_T[k][:3, :3]).astype(np.float32)
        kfs.append(Keyframe(k, k * 2.0, odom_T[k], pts, pts, np.zeros(len(pts), bool)))
        det.add_keyframe(kfs[-1])
        pg.add_keyframe(k, odom_T[k], is_first=(k == 0))
        if k:
            pg.add_odometry_factor(k - 1, k, np.linalg.inv(odom_T[k - 1]) @ odom_T[k])
        for lc in det.detect_for_keyframe(kfs, k):
            loops.append(lc)
            pg.add_loop_factor(lc)

    from civil.forge.eskf_lio import so3_log

    for lc in loops:  # every accepted constraint must match the true relative pose
        T_true = np.linalg.inv(true_T[lc.from_id]) @ true_T[lc.to_id]
        err = np.linalg.inv(T_true) @ lc.T_from_to
        assert np.linalg.norm(err[:3, 3]) < 0.3, (lc.from_id, lc.to_id, err[:3, 3])
        assert np.degrees(np.linalg.norm(so3_log(err[:3, :3]))) < 2.0
    assert any(lc.to_id >= 38 and lc.from_id <= 2 for lc in loops), "the return to the start must be closed"
    opt, _ = pg.optimize()
    gt = np.array([T[:3, 3] for T in true_T])
    ate_odom = np.sqrt(np.mean(np.sum((np.array([T[:3, 3] for T in odom_T]) - gt) ** 2, 1)))
    ate_opt = np.sqrt(np.mean(np.sum((np.array([opt[k][:3, 3] for k in range(41)]) - gt) ** 2, 1)))
    assert ate_opt < 0.5 * ate_odom, (ate_odom, ate_opt)


def test_gtsam_pose_graph_reduces_loop_ate_by_over_60_percent():
    from civil.forge.pose_graph import PoseGraphOptimizer
    from civil.forge.types import LoopConstraint

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
            cd, sd = math.cos(0.004), math.sin(0.004)
            T_drift = np.eye(4, dtype=np.float64)
            T_drift[:3, :3] = [[cd, -sd, 0], [sd, cd, 0], [0, 0, 1]]
            T_drift[:3, 3] = [0.03, 0.02, 0.015]
            T_rel_odom = T_rel_true @ T_drift
            T_odom_curr = T_odom_curr @ T_rel_odom
            odom_poses.append(T_odom_curr.copy())
            pg.add_keyframe(k, T_odom_curr, is_first=False)
            pg.add_odometry_factor(k - 1, k, T_rel_odom)

    T_0_39_true = np.linalg.inv(true_poses[0]) @ true_poses[-1]
    lc = LoopConstraint(from_id=0, to_id=n_kf - 1, T_from_to=T_0_39_true, rmse=0.04, inlier_ratio=0.92, sc_distance=0.11)
    assert pg.add_loop_factor(lc)

    opt_poses, stats = pg.optimize()

    true_xyz = np.array([T[:3, 3] for T in true_poses])
    odom_xyz = np.array([T[:3, 3] for T in odom_poses])
    opt_xyz = np.array([opt_poses[k][:3, 3] for k in range(n_kf)])

    rmse_before = float(np.sqrt(np.mean(np.sum((odom_xyz - true_xyz) ** 2, axis=1))))
    rmse_after = float(np.sqrt(np.mean(np.sum((opt_xyz - true_xyz) ** 2, axis=1))))
    assert rmse_after < 0.35 * rmse_before
    assert stats["num_poses"] == n_kf


def test_pose_graph_no_loop_unchanged_and_incremental_matches_batch():
    from civil.forge.pose_graph import PoseGraphOptimizer
    from civil.forge.types import LoopConstraint

    pg = PoseGraphOptimizer()
    odom_poses = []
    for k in range(10):
        T = np.eye(4, dtype=np.float64)
        T[:3, 3] = [k * 2.5, 0.2 * k, 0.0]
        odom_poses.append(T)
        pg.add_keyframe(k, T, is_first=(k == 0))
        if k > 0:
            T_rel = np.linalg.inv(odom_poses[k - 1]) @ T
            pg.add_odometry_factor(k - 1, k, T_rel)

    # Without loop closures, optimized trajectory must equal odometry chain
    opt_no_loop, _ = pg.optimize()
    for k in range(10):
        np.testing.assert_allclose(opt_no_loop[k], odom_poses[k], atol=1e-4)

    # Now add a loop closure and compare pure iSAM2 incremental estimate against batch LM polish
    T_loop = np.eye(4)
    T_loop[:3, 3] = [22.4, 1.7, 0.0]
    pg.add_loop_factor(LoopConstraint(from_id=0, to_id=9, T_from_to=T_loop, rmse=0.05, inlier_ratio=0.85, sc_distance=0.15))
    pg._isam.update()
    est_isam = pg._isam.calculateEstimate()
    isam_xyz = np.array([est_isam.atPose3(k).translation() for k in range(10)])

    opt_batch, _ = pg.optimize()
    batch_xyz = np.array([opt_batch[k][:3, 3] for k in range(10)])
    np.testing.assert_allclose(isam_xyz, batch_xyz, atol=0.05)


def test_cauchy_robust_kernel_limits_bad_outlier_loop_factor():
    from civil.forge.pose_graph import PoseGraphOptimizer
    from civil.forge.types import LoopConstraint

    pg = PoseGraphOptimizer()
    for k in range(12):
        T = np.eye(4, dtype=np.float64)
        T[:3, 3] = [k * 2.0, 0.0, 0.0]
        pg.add_keyframe(k, T, is_first=(k == 0))
        if k > 0:
            dT = np.eye(4)
            dT[0, 3] = 2.0
            pg.add_odometry_factor(k - 1, k, dT)

    # Add a valid loop constraint on node 10 (true x=20.0) and a gross 30 m outlier loop factor on node 11 (true x=22.0)
    T_good = np.eye(4)
    T_good[:3, 3] = [20.0, 0.0, 0.0]
    pg.add_loop_factor(LoopConstraint(from_id=0, to_id=10, T_from_to=T_good, rmse=0.03, inlier_ratio=0.95, sc_distance=0.10))

    T_bad = np.eye(4)
    T_bad[:3, 3] = [22.0, 30.0, 0.0]  # 30 m false lateral jump
    # The false loop claims to be as confident as a good one (5 cm RMSE): only the robust kernel can reject it
    pg.add_loop_factor(LoopConstraint(from_id=0, to_id=11, T_from_to=T_bad, rmse=0.05, inlier_ratio=0.90, sc_distance=0.10))

    opt_poses, _ = pg.optimize()
    assert abs(opt_poses[11][1, 3]) < 0.5, f"Outlier loop pulled trajectory too far: y={opt_poses[11][1, 3]:.2f} m"
    assert abs(opt_poses[10][0, 3] - 20.0) < 0.1

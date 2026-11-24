"""TDD tests for FORGE SLAM Stage 1: 15-DOF ESKF LIO Front End and Reconstruction temperatures_c."""

from __future__ import annotations

import numpy as np
import pytest

from civil.pointcloud import Reconstruction


def test_reconstruction_temperatures_c_persistence(tmp_path):
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, -0.05], [2.0, 4.0, 0.02]], dtype=np.float32)
    rgb = np.array([[100, 110, 120], [130, 140, 150], [160, 170, 180]], dtype=np.uint8)
    temps = np.array([28.5, 34.2, 29.1], dtype=np.float32)

    rec = Reconstruction(points=pts, colors=rgb, temperatures_c=temps, meta={"metric": True})
    assert rec.temperatures_c is not None
    assert rec.temperatures_c.dtype == np.float32
    assert len(rec.temperatures_c) == 3

    out = tmp_path / "recon.npz"
    rec.save(out)
    loaded = Reconstruction.load(out)
    assert loaded.temperatures_c is not None
    np.testing.assert_allclose(loaded.temperatures_c, temps, atol=1e-5)

    with pytest.raises(ValueError, match="temperatures_c"):
        Reconstruction(points=pts, temperatures_c=np.array([25.0, 26.0], dtype=np.float32))


def test_eskf_imu_propagation_and_deskew():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    calib = SensorCalibration(T_lidar_imu=np.eye(4))
    lio = ESKFLIO(calib=calib, config=ForgeConfig())

    dt = 0.005
    omega_z = 0.5
    acc_x = 1.0
    g = 9.80665
    lio.predict_imu(0.0, np.zeros(3), np.array([1.0, 0.0, g]))
    for step in range(1, 21):
        t = step * dt
        yaw = omega_z * (t - dt)
        c, s = np.cos(yaw), np.sin(yaw)
        f_b = np.array([c * acc_x, -s * acc_x, g], dtype=np.float64)
        w_b = np.array([0.0, 0.0, omega_z], dtype=np.float64)
        lio.predict_imu(t, w_b, f_b)

    state = lio.state_pose()
    assert abs(state[0, 3] - 0.005) < 5e-4
    yaw_est = np.arctan2(state[1, 0], state[0, 0])
    assert abs(yaw_est - 0.05) < 1e-3

    n_pts = 50
    pt_times = np.linspace(0.0, 0.1, n_pts)
    pts_raw = np.zeros((n_pts, 3), dtype=np.float32)
    pts_world_true = np.column_stack([
        np.full(n_pts, 10.0),
        np.linspace(-2.0, 2.0, n_pts),
        np.zeros(n_pts),
    ])
    for i, tau in enumerate(pt_times):
        T_wb = lio.interpolate_pose(float(tau))
        p_b = (np.linalg.inv(T_wb) @ np.append(pts_world_true[i], 1.0))[:3]
        pts_raw[i] = p_b.astype(np.float32)

    scan = LidarScan(t=0.1, points=pts_raw, point_times=pt_times)
    deskewed_b = lio.deskew_scan(scan)
    T_end = lio.state_pose()
    pts_w_recovered = (deskewed_b.astype(np.float64) @ T_end[:3, :3].T) + T_end[:3, 3]
    np.testing.assert_allclose(pts_w_recovered, pts_world_true, atol=1e-2)


def test_eskf_lidar_update_and_covariance_health():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    rng = np.random.default_rng(42)
    calib = SensorCalibration(T_lidar_imu=np.eye(4))
    lio = ESKFLIO(calib=calib, config=ForgeConfig(voxel_size_m=0.15))

    gx, gy = np.meshgrid(np.linspace(0, 25, 80), np.linspace(-4, 4, 30))
    ground = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    wx, wz = np.meshgrid(np.linspace(0, 25, 60), np.linspace(0, 2.5, 10))
    wall_l = np.column_stack([wx.ravel(), np.full(wx.size, -4.0), wz.ravel()])
    wall_r = np.column_stack([wx.ravel(), np.full(wx.size, 4.0), wz.ravel()])
    ey, ez = np.meshgrid(np.linspace(-4, 4, 25), np.linspace(0, 2.5, 10))
    wall_e = np.column_stack([np.full(ey.size, 25.0), ey.ravel(), ez.ravel()])
    world_cloud = np.vstack([ground, wall_l, wall_r, wall_e]).astype(np.float64)

    scan0 = LidarScan(t=0.0, points=world_cloud.astype(np.float32))
    pose0, _, _ = lio.update_lidar(scan0)
    np.testing.assert_allclose(pose0[:3, 3], [0.0, 0.0, 0.0], atol=1e-3)

    true_pos = np.array([1.20, 0.05, 0.0])
    true_yaw = 0.03
    c, s = np.cos(true_yaw), np.sin(true_yaw)
    R_true = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)

    for step in range(1, 11):
        t = step * 0.01
        lio.predict_imu(t, np.array([0.0, 0.0, 0.25]), np.array([21.0, 0.8, 9.80665]))

    pts_body1 = ((world_cloud - true_pos) @ R_true).astype(np.float32)
    pts_body1 += rng.normal(0.0, 0.003, size=pts_body1.shape).astype(np.float32)
    scan1 = LidarScan(t=0.1, points=pts_body1)
    pose1, _, tel1 = lio.update_lidar(scan1)

    pos_err = float(np.linalg.norm(pose1[:3, 3] - true_pos))
    assert pos_err < 0.04
    assert tel1["cov_max_eigenvalue"] > 0.0
    assert not tel1["divergence_detected"]
    assert np.all(np.linalg.eigvalsh(lio.P) > 0.0)


def test_eskf_gyro_and_accel_bias_convergence():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    # Stationary sensor observing a 3-wall room while IMU has constant gyro bias +0.05 rad/s and accel bias +0.20 m/s^2
    calib = SensorCalibration(gyr_bias_walk=5e-3, acc_bias_walk=2e-2)
    lio = ESKFLIO(calib=calib, config=ForgeConfig(voxel_size_m=0.20))

    gx, gy = np.meshgrid(np.linspace(-5, 5, 35), np.linspace(-5, 5, 35))
    ground = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    wx, wz = np.meshgrid(np.linspace(-5, 5, 30), np.linspace(0, 2.5, 10))
    wall_y = np.column_stack([wx.ravel(), np.full(wx.size, 4.0), wz.ravel()])
    wall_x = np.column_stack([np.full(wx.size, 4.0), wx.ravel(), wz.ravel()])
    room = np.vstack([ground, wall_y, wall_x]).astype(np.float32)

    true_bg = np.array([0.0, 0.0, 0.05], dtype=np.float64)
    true_ba = np.array([0.20, 0.0, 0.0], dtype=np.float64)

    lio.predict_imu(0.0, true_bg, np.array([0.0, 0.0, 9.80665]) + true_ba)
    lio.update_lidar(LidarScan(t=0.0, points=room))

    t_curr = 0.0
    for cycle in range(1, 15):
        for _ in range(10):
            t_curr += 0.01
            lio.predict_imu(t_curr, true_bg, np.array([0.0, 0.0, 9.80665]) + true_ba)
        lio.update_lidar(LidarScan(t=t_curr, points=room))

    # Estimated biases must move significantly toward true_bg and true_ba, and pose stays at origin
    assert np.linalg.norm(lio.bg - true_bg) < np.linalg.norm(true_bg) * 0.55
    assert np.linalg.norm(lio.ba - true_ba) < np.linalg.norm(true_ba) * 0.65
    assert np.linalg.norm(lio.p) < 0.03


def test_eskf_imu_only_drift_bounded_and_out_of_order_timestamps():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, SensorCalibration

    rng = np.random.default_rng(19)
    lio = ESKFLIO(SensorCalibration(), ForgeConfig())
    lio.predict_imu(0.0, np.zeros(3), np.array([0.0, 0.0, 9.80665]))

    # Out-of-order timestamp (t = -0.05 < t_last = 0.0) must be ignored without moving the clock back
    P_before = lio.P.copy()
    lio.predict_imu(-0.05, np.array([5.0, 5.0, 5.0]), np.array([50.0, 50.0, 50.0]))
    np.testing.assert_allclose(lio.P, P_before)
    assert lio.t_last == 0.0
    assert lio.imu_out_of_order == 1

    # Large gap (3.5 s): no integration across it, but position/velocity uncertainty must grow, and it is counted
    lio.predict_imu(3.5, np.zeros(3), np.array([0.0, 0.0, 9.80665]))
    assert lio.imu_gaps == 1
    assert np.trace(lio.P[6:9, 6:9]) > np.trace(P_before[6:9, 6:9]) * 10
    assert np.all(np.isfinite(lio.P))
    times = [t for t, _ in lio._pose_history]
    assert all(b > a for a, b in zip(times, times[1:])), "pose history must stay time-ordered"

    # 1.0 s of 200 Hz noisy IMU-only integration around hover
    for k in range(1, 201):
        t = 3.5 + k * 0.005
        g_noisy = rng.normal(0.0, 2.4e-3, 3)
        a_noisy = np.array([0.0, 0.0, 9.80665]) + rng.normal(0.0, 2.5e-2, 3)
        lio.predict_imu(t, g_noisy, a_noisy)

    assert np.linalg.norm(lio.p) < 0.05
    assert np.all(np.isfinite(lio.P))


def test_eskf_degenerate_flat_road_and_tunnel_flagged_without_diverging():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    # Degenerate flat horizontal plane (only z, roll, pitch are observable -> observable_dofs <= 3)
    lio = ESKFLIO(SensorCalibration(), ForgeConfig(voxel_size_m=0.25))
    gx, gy = np.meshgrid(np.linspace(-10, 10, 50), np.linspace(-10, 10, 50))
    flat_plane = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]).astype(np.float32)

    lio.update_lidar(LidarScan(t=0.0, points=flat_plane))
    lio.predict_imu(0.1, np.zeros(3), np.array([0.0, 0.0, 9.80665]))
    pose, _, tel = lio.update_lidar(LidarScan(t=0.1, points=flat_plane))

    assert tel["observable_dofs"] <= 3, f"Flat plane should have <= 3 observable DOFs, got {tel['observable_dofs']}"
    assert tel["degenerate"]
    assert not tel["divergence_detected"]
    assert np.linalg.norm(pose[:3, 3]) < 0.05


def test_eskf_tunnel_flags_along_axis_degeneracy_and_keeps_imu_motion():
    """In a straight tunnel LiDAR cannot see motion along the axis: flag it and keep the IMU's estimate."""
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    rng = np.random.default_rng(3)
    xs = np.linspace(-30, 30, 240)
    ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    X, A = np.meshgrid(xs, ang)
    tunnel = np.column_stack([X.ravel(), 3.0 * np.cos(A.ravel()), 2.5 * np.sin(A.ravel())])
    tunnel += rng.normal(0, 0.005, tunnel.shape)

    lio = ESKFLIO(SensorCalibration(), ForgeConfig(voxel_size_m=0.2))
    g = np.array([0.0, 0.0, 9.80665])
    lio.predict_imu(0.0, np.zeros(3), g)
    lio.update_lidar(LidarScan(t=0.0, points=tunnel.astype(np.float32)))
    lio.v[:] = [2.0, 0.0, 0.0]  # moving at 2 m/s along the tunnel axis
    t = 0.0
    for _ in range(5):
        for _ in range(20):
            t += 0.005
            lio.predict_imu(t, np.zeros(3), g)
        true_x = 2.0 * t
        scan = tunnel - np.array([true_x, 0.0, 0.0])  # the tunnel looks identical everywhere
        pose, _, tel = lio.update_lidar(LidarScan(t=t, points=scan.astype(np.float32)))
    assert tel["degenerate"]
    assert "x" in tel["degenerate_translation_axes"]
    assert abs(pose[0, 3] - 2.0 * t) < 0.05, "along-axis motion should follow the IMU, not snap back"
    assert abs(pose[1, 3]) < 0.05 and abs(pose[2, 3]) < 0.05


def test_eskf_static_init_aligns_gravity_for_tilted_imu():
    """A tilted, stationary IMU must not be read as accelerating: align gravity and take the gyro bias at start."""
    from civil.forge.eskf_lio import ESKFLIO, so3_exp
    from civil.forge.types import ForgeConfig, SensorCalibration

    rng = np.random.default_rng(5)
    R_true = so3_exp(np.radians([12.0, -8.0, 30.0]))
    f_b = R_true.T @ np.array([0.0, 0.0, 9.80665])
    bg_true = np.array([0.004, -0.003, 0.006])
    gyros = bg_true + rng.normal(0, 2e-3, (200, 3))
    accs = f_b + rng.normal(0, 2e-2, (200, 3))

    lio = ESKFLIO(SensorCalibration(), ForgeConfig())
    assert lio.initialize_static(gyros, accs)
    np.testing.assert_allclose(lio.bg, bg_true, atol=1e-3)
    g_est = lio.R @ f_b
    assert np.degrees(np.arccos(g_est[2] / np.linalg.norm(g_est))) < 0.3

    lio.predict_imu(0.0, gyros[0], accs[0])
    for k in range(1, 401):  # 2 s stationary at 200 Hz
        lio.predict_imu(k * 0.005, bg_true + rng.normal(0, 2e-3, 3), f_b + rng.normal(0, 2e-2, 3))
    assert np.linalg.norm(lio.p) < 0.1, f"tilted static IMU drifted {np.linalg.norm(lio.p):.2f} m in 2 s"

    moving = ESKFLIO(SensorCalibration(), ForgeConfig())
    assert not moving.initialize_static(gyros + np.array([0.0, 0.0, 0.5]), accs)  # turning: not static

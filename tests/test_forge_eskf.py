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

    # Mismatched length must raise ValueError
    with pytest.raises(ValueError, match="temperatures_c"):
        Reconstruction(points=pts, temperatures_c=np.array([25.0, 26.0], dtype=np.float32))


def test_eskf_imu_propagation_and_deskew():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    calib = SensorCalibration(T_lidar_imu=np.eye(4))
    lio = ESKFLIO(calib=calib, config=ForgeConfig())

    # Constant forward acceleration 1.0 m/s^2 along +X and yaw rate 0.5 rad/s around +Z for 0.1 s
    dt = 0.005
    omega_z = 0.5
    acc_x = 1.0
    g = 9.80665
    lio.predict_imu(0.0, np.zeros(3), np.array([1.0, 0.0, g]))
    for step in range(1, 21):
        t = step * dt
        yaw = omega_z * (t - dt)
        # Specific force in body frame = R_wb^T * (a_w - g_w)
        # In world frame, a_w = [acc_x, 0, 0], g_w = [0, 0, -g] -> a_w - g_w = [acc_x, 0, g]
        c, s = np.cos(yaw), np.sin(yaw)
        f_b = np.array([c * acc_x, -s * acc_x, g], dtype=np.float64)
        w_b = np.array([0.0, 0.0, omega_z], dtype=np.float64)
        lio.predict_imu(t, w_b, f_b)

    state = lio.state_pose()
    # Expected x = 0.5 * 1.0 * 0.1^2 = 0.005 m, yaw = 0.05 rad
    assert abs(state[0, 3] - 0.005) < 5e-4
    yaw_est = np.arctan2(state[1, 0], state[0, 0])
    assert abs(yaw_est - 0.05) < 1e-3

    # Test scan deskewing: a static world wall at X_w = 10.0 m observed during [0.0, 0.1] s
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
    # Without deskewing, a 0.05 rad yaw over 10 m produces ~0.50 m error; deskewing must keep it < 0.01 m
    np.testing.assert_allclose(pts_w_recovered, pts_world_true, atol=1e-2)


def test_eskf_lidar_update_and_covariance_health():
    from civil.forge.eskf_lio import ESKFLIO
    from civil.forge.types import ForgeConfig, LidarScan, SensorCalibration

    rng = np.random.default_rng(42)
    calib = SensorCalibration(T_lidar_imu=np.eye(4))
    lio = ESKFLIO(calib=calib, config=ForgeConfig(voxel_size_m=0.15))

    # Build a synthetic 3D street scene (ground z=0 + two side curb walls at y=-4, y=+4 + end wall x=25)
    gx, gy = np.meshgrid(np.linspace(0, 25, 80), np.linspace(-4, 4, 30))
    ground = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    wx, wz = np.meshgrid(np.linspace(0, 25, 60), np.linspace(0, 2.5, 10))
    wall_l = np.column_stack([wx.ravel(), np.full(wx.size, -4.0), wz.ravel()])
    wall_r = np.column_stack([wx.ravel(), np.full(wx.size, 4.0), wz.ravel()])
    ey, ez = np.meshgrid(np.linspace(-4, 4, 25), np.linspace(0, 2.5, 10))
    wall_e = np.column_stack([np.full(ey.size, 25.0), ey.ravel(), ez.ravel()])
    world_cloud = np.vstack([ground, wall_l, wall_r, wall_e]).astype(np.float64)

    # First scan at origin initializes the local map
    scan0 = LidarScan(t=0.0, points=world_cloud.astype(np.float32))
    pose0, _, tel0 = lio.update_lidar(scan0)
    np.testing.assert_allclose(pose0[:3, 3], [0.0, 0.0, 0.0], atol=1e-3)

    # Move true vehicle to x = 1.20 m, y = 0.05 m, yaw = 0.03 rad, but feed slightly noisy IMU
    true_pos = np.array([1.20, 0.05, 0.0])
    true_yaw = 0.03
    c, s = np.cos(true_yaw), np.sin(true_yaw)
    R_true = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
    T_true = np.eye(4)
    T_true[:3, :3] = R_true
    T_true[:3, 3] = true_pos

    # Propagate IMU with slight bias so predicted pose is ~15 cm off
    for step in range(1, 11):
        t = step * 0.01
        lio.predict_imu(t, np.array([0.0, 0.0, 0.25]), np.array([21.0, 0.8, 9.80665]))

    pts_body1 = ((world_cloud - true_pos) @ R_true).astype(np.float32)
    pts_body1 += rng.normal(0.0, 0.003, size=pts_body1.shape).astype(np.float32)
    scan1 = LidarScan(t=0.1, points=pts_body1)
    pose1, _, tel1 = lio.update_lidar(scan1)

    pos_err = float(np.linalg.norm(pose1[:3, 3] - true_pos))
    assert pos_err < 0.04, f"ESKF LIO update position error too large: {pos_err:.4f} m"
    assert tel1["cov_max_eigenvalue"] > 0.0
    assert not tel1["divergence_detected"]
    # Covariance matrix P must remain symmetric positive-definite
    eigvals = np.linalg.eigvalsh(lio.P)
    assert np.all(eigvals > 0.0)

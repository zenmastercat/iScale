"""TDD tests for FORGE SLAM Stage 6: Radiometric Thermal (°C) + RGB Registration & 3D Gaussian Splatting."""

from __future__ import annotations

import numpy as np
import pytest


def test_flir_planck_raw_to_celsius_and_uncalibrated_u8_rejection():
    from civil.forge.thermal_reg import celsius_to_flir_raw, raw_to_celsius

    # KAIST MS2 FLIR A65C reference temperatures: 15.0 C, 28.5 C (asphalt), 42.0 C (hot patch)
    temps_true = np.array([[15.0, 28.5], [35.2, 42.0]], dtype=np.float32)
    raw16 = celsius_to_flir_raw(temps_true)
    recovered = raw_to_celsius(raw16, encoding="flir_raw")
    assert recovered.dtype == np.float32
    np.testing.assert_allclose(recovered, temps_true, atol=1e-2)

    # Centikelvin uint16 encoding: (T + 273.15) * 100
    ck = np.round((temps_true + 273.15) * 100.0).astype(np.uint16)
    rec_ck = raw_to_celsius(ck, encoding="centikelvin")
    np.testing.assert_allclose(rec_ck, temps_true, atol=2e-2)

    # Uncalibrated 8-bit image without linear_range must raise ValueError naming temp_min_c/temp_max_c
    u8_img = np.array([[100, 200]], dtype=np.uint8)
    with pytest.raises(ValueError, match="temp_min_c"):
        raw_to_celsius(u8_img, encoding="linear_u8", linear_range=None)


def test_rgb_and_radiometric_thermal_zbuffer_registration():
    from civil.forge.thermal_reg import celsius_to_flir_raw, register_rgb_and_thermal
    from civil.forge.types import CameraFrame, Keyframe

    # Camera looking straight down (+Z optical axis along -Z world, or forward along +X world):
    # Let's use standard OpenCV camera frame looking along +X world:
    # X_cam = -Y_w, Y_cam = -Z_w, Z_cam = +X_w
    R_wc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)
    T_wc = np.eye(4, dtype=np.float64)
    T_wc[:3, :3] = R_wc
    T_wc[:3, 3] = [0.0, 0.0, 1.5]
    # Keyframe at origin with T_wb = I -> T_lidar_cam = T_wc
    kf = Keyframe(
        id=0,
        t=1.0,
        pose_w_b=np.eye(4, dtype=np.float64),
        points_local=np.zeros((1, 3), dtype=np.float32),
        raw_points_local=np.zeros((1, 3), dtype=np.float32),
        dynamic_mask=np.zeros(1, dtype=bool),
    )

    # Road grid at X_w in [4, 10], Y_w in [-2, 2], Z_w = 0.0
    gx, gy = np.meshgrid(np.linspace(4.0, 10.0, 25), np.linspace(-2.0, 2.0, 25))
    road_pts = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]).astype(np.float32)

    # Synthetic camera 160x120, fx=fy=120, cx=80, cy=60
    K = np.array([[120.0, 0.0, 80.0], [0.0, 120.0, 60.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    D = np.zeros(4, dtype=np.float64)

    # Ground-truth temperature field on road: 28.0 C ambient + 8.0 C warm spot at (X=6.0, Y=0.0)
    true_temp_pts = (28.0 + 8.0 * np.exp(-((road_pts[:, 0] - 6.0) ** 2 + road_pts[:, 1] ** 2) / 1.2)).astype(np.float32)

    # Render synthetic RGB and FLIR raw thermal frame from camera pose T_wc
    H, W = 120, 160
    rgb_img = np.full((H, W, 3), 120, dtype=np.uint8)
    temp_img_c = np.full((H, W), 28.0, dtype=np.float32)
    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    # Ray in camera frame: d_c = [(xx - cx)/fx, (yy - cy)/fy, 1.0]; world ray d_w = R_wc @ d_c
    # Intersection with Z_w = 0 plane from origin (0, 0, 1.5):
    # Z_w = 1.5 + s * (-d_c_y) = 0 => s = 1.5 / d_c_y (for yy > cy)
    dy_c = (yy - 60.0) / 120.0
    dx_c = (xx - 80.0) / 120.0
    valid_ground = dy_c > 0.05
    s_depth = np.where(valid_ground, 1.5 / np.maximum(dy_c, 0.05), 10.0)
    xw_pix = s_depth
    yw_pix = -s_depth * dx_c
    temp_img_c = np.where(
        valid_ground,
        28.0 + 8.0 * np.exp(-((xw_pix - 6.0) ** 2 + yw_pix ** 2) / 1.2),
        20.0,
    ).astype(np.float32)
    rgb_img[..., 0] = np.clip((temp_img_c - 20.0) * 10.0, 0, 255).astype(np.uint8)

    raw_thermal = celsius_to_flir_raw(temp_img_c)

    rgb_frame = CameraFrame(t=1.0, image=rgb_img, intrinsics=K, distortion=D, T_lidar_cam=T_wc, modality="rgb")
    thr_frame = CameraFrame(
        t=1.005,
        image=raw_thermal,
        intrinsics=K,
        distortion=D,
        T_lidar_cam=T_wc,
        modality="thermal",
        thermal_encoding="flir_raw",
    )

    colors_out, temps_out, stats = register_rgb_and_thermal(road_pts, [kf], [rgb_frame], [thr_frame])
    assert colors_out.shape == (len(road_pts), 3)
    assert temps_out.shape == (len(road_pts),)
    assert temps_out.dtype == np.float32

    rmse_c = float(np.sqrt(np.mean((temps_out - true_temp_pts) ** 2)))
    assert rmse_c < 0.35, f"Radiometric thermal registration RMSE too large: {rmse_c:.3f} C"
    assert stats["registered_points"] == len(road_pts)


def test_keyframe_anchored_rgb_thermal_gsplat():
    from civil.forge.gsplat import train_and_eval_gsplat
    from civil.forge.types import CameraFrame, Keyframe

    # 3D planar road patch with 400 points and 6 camera views
    gx, gy = np.meshgrid(np.linspace(3.0, 8.0, 20), np.linspace(-1.5, 1.5, 20))
    pts_w = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]).astype(np.float32)
    temps_c = (26.0 + 6.0 * np.exp(-((pts_w[:, 0] - 5.5) ** 2 + pts_w[:, 1] ** 2) / 1.0)).astype(np.float32)
    colors_rgb = np.column_stack([
        np.clip((temps_c - 24.0) * 20.0, 40, 240),
        np.full(len(pts_w), 110.0),
        np.full(len(pts_w), 95.0),
    ]).astype(np.uint8)

    R_wc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)
    K = np.array([[80.0, 0.0, 48.0], [0.0, 80.0, 36.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    D = np.zeros(4, dtype=np.float64)

    keyframes: list[Keyframe] = []
    rgb_frames: list[CameraFrame] = []
    thr_frames: list[CameraFrame] = []

    for i in range(6):
        T_wb = np.eye(4, dtype=np.float64)
        T_wb[:3, 3] = [i * 0.4, 0.0, 0.0]
        T_lc = np.eye(4, dtype=np.float64)
        T_lc[:3, :3] = R_wc
        T_lc[:3, 3] = [0.0, 0.0, 1.5]
        keyframes.append(
            Keyframe(
                id=i,
                t=float(i),
                pose_w_b=T_wb,
                points_local=(pts_w - T_wb[:3, 3]).astype(np.float32),
                raw_points_local=(pts_w - T_wb[:3, 3]).astype(np.float32),
                dynamic_mask=np.zeros(len(pts_w), dtype=bool),
            )
        )
        # Dummy frames rendered by the model's initial forward pass so held-out PSNR/SSIM & thermal MAE are tested cleanly
        rgb_frames.append(CameraFrame(t=float(i), image=np.zeros((72, 96, 3), dtype=np.uint8), intrinsics=K, distortion=D, T_lidar_cam=T_lc, modality="rgb"))
        thr_frames.append(CameraFrame(t=float(i), image=np.full((72, 96), 28.0, dtype=np.float32), intrinsics=K, distortion=D, T_lidar_cam=T_lc, modality="thermal", thermal_encoding="celsius_f32"))

    model, metrics = train_and_eval_gsplat(
        pts_w,
        colors_rgb,
        temps_c,
        keyframes,
        rgb_frames,
        thr_frames,
        min_free_gpu_gb=4.0,
        max_gaussians=1000,
        iters=25,
        self_supervise_from_cloud=True,
    )
    assert model.num_gaussians == len(pts_w)
    assert metrics["heldout_psnr_db"] >= 24.0
    assert metrics["heldout_ssim"] >= 0.80
    assert metrics["thermal_mae_c"] <= 0.50

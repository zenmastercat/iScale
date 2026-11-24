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


def test_flir_raw_matches_ms2_reference_formula():
    """Absolute °C must equal the MS² dataloader's Raw2Celsius, not just round-trip with our own inverse."""
    from civil.forge.thermal_reg import celsius_to_flir_raw, raw_to_celsius

    R, B, F, O = 380747.0, 1428.0, 1.0, -88.539
    raw = np.array([2800.0, 3100.0, 3600.0, 4200.0])
    ref_c = B / np.log(R / (raw - O) + F) - 273.15  # MS2 utils.Raw2Celsius
    np.testing.assert_allclose(raw_to_celsius(raw, encoding="flir_raw"), ref_c, atol=1e-3)
    ref_raw = R / (np.exp(B / (np.array([20.0, 35.0]) + 273.15)) - F) + O  # MS2 utils.Celsius2Raw
    np.testing.assert_allclose(celsius_to_flir_raw(np.array([20.0, 35.0])), np.round(ref_raw), atol=1.0)


def test_unseen_points_get_nan_not_a_made_up_temperature():
    from civil.forge.thermal_reg import register_rgb_and_thermal
    from civil.forge.types import CameraFrame, Keyframe

    R_wc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    T_wc = np.eye(4)
    T_wc[:3, :3] = R_wc
    T_wc[:3, 3] = [0.0, 0.0, 1.5]
    kf = Keyframe(0, 0.0, np.eye(4), np.zeros((1, 3), np.float32), np.zeros((1, 3), np.float32), np.zeros(1, bool))
    K = np.array([[120.0, 0, 80], [0, 120.0, 60], [0, 0, 1]])
    seen = np.array([[6.0, 0.0, 0.0]], np.float32)
    behind = np.array([[-6.0, 0.0, 0.0]], np.float32)
    thr = CameraFrame(0.0, np.full((120, 160), 31.0, np.float32), K, np.zeros(5), T_wc, "thermal", "celsius_f32")
    _, temps, stats = register_rgb_and_thermal(np.vstack([seen, behind]), [kf], [], [thr])
    assert temps[0] == pytest.approx(31.0, abs=1e-3)
    assert np.isnan(temps[1])
    assert stats["thermal_registered"] == 1


def test_thermal_registration_applies_lens_distortion():
    """STheReO's thermal lens has k1 = -0.36; ignoring it misplaces °C by many pixels at the image edge."""
    import cv2
    from civil.forge.thermal_reg import register_rgb_and_thermal
    from civil.forge.types import CameraFrame, Keyframe

    R_wc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    T_wc = np.eye(4)
    T_wc[:3, :3] = R_wc
    T_wc[:3, 3] = [0.0, 0.0, 1.5]
    kf = Keyframe(0, 0.0, np.eye(4), np.zeros((1, 3), np.float32), np.zeros((1, 3), np.float32), np.zeros(1, bool))
    H, W = 240, 320
    K = np.array([[200.0, 0, 160], [0, 200.0, 120], [0, 0, 1]])
    D = np.array([-0.36, 0.10, 0.0, 0.0, 0.0])

    def temp_at(xw, yw):  # stripes across the road: 2 °C per metre of lateral offset
        return 25.0 + 2.0 * yw + 3.0 * np.sin(xw)

    # Distorted image: each pixel's true ray comes from undistorting its coordinates
    uu, vv = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    und = cv2.undistortPoints(np.stack([uu.ravel(), vv.ravel()], 1)[:, None, :], K, D).reshape(-1, 2)
    xn, yn = und[:, 0], und[:, 1]
    ok = yn > 0.05
    s = np.where(ok, 1.5 / np.maximum(yn, 0.05), 0.0)
    img = np.where(ok, temp_at(s, -s * xn), 10.0).reshape(H, W).astype(np.float32)

    gx, gy = np.meshgrid(np.linspace(3.0, 9.0, 30), np.linspace(-3.0, 3.0, 30))
    pts = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]).astype(np.float32)
    thr = CameraFrame(0.0, img, K, D, T_wc, "thermal", "celsius_f32")
    _, temps, _ = register_rgb_and_thermal(pts, [kf], [], [thr])
    fin = np.isfinite(temps)
    assert fin.sum() > 300
    err = np.abs(temps[fin] - temp_at(pts[fin, 0], pts[fin, 1]))
    assert float(np.median(err)) < 0.15, f"median error {np.median(err):.2f} C"


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


def _plane_view(K, T_wc, H, W, field):
    """Ground-truth image of the z=0 plane seen from T_wc, computed analytically (independent of the splat model)."""
    uu, vv = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    d_c = np.stack([(uu - K[0, 2]) / K[0, 0], (vv - K[1, 2]) / K[1, 1], np.ones_like(uu)], -1)
    d_w = d_c @ T_wc[:3, :3].T
    s = -T_wc[2, 3] / np.where(np.abs(d_w[..., 2]) > 1e-6, d_w[..., 2], -1e-6)
    hit = (s > 0) & (d_w[..., 2] < -1e-3)
    xw = T_wc[0, 3] + s * d_w[..., 0]
    yw = T_wc[1, 3] + s * d_w[..., 1]
    return np.where(hit, field(xw, yw), np.nan), hit


def test_splat_fit_on_independent_views_and_thermal_in_its_own_camera():
    """Held-out views come from an analytic scene, not from the model; thermal is scored in the thermal camera."""
    from civil.forge.gsplat import train_and_eval_gsplat
    from civil.forge.types import CameraFrame, Keyframe

    gx, gy = np.meshgrid(np.linspace(3.0, 9.0, 90), np.linspace(-2.0, 2.0, 60))
    pts_w = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]).astype(np.float32)

    def red(x, y):
        return 128.0 + 100.0 * np.sin(1.3 * x) * np.cos(1.1 * y)

    def temp(x, y):
        return 26.0 + 6.0 * np.exp(-((x - 6.0) ** 2 + y ** 2) / 1.5)

    R_wc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    K_rgb = np.array([[90.0, 0, 64], [0, 90.0, 48], [0, 0, 1]])
    K_thr = np.array([[70.0, 0, 40], [0, 70.0, 32], [0, 0, 1]])
    T_b_rgb = np.eye(4)
    T_b_rgb[:3, :3] = R_wc
    T_b_rgb[:3, 3] = [0.0, 0.0, 1.5]
    T_b_thr = T_b_rgb.copy()
    T_b_thr[:3, 3] = [0.0, 0.5, 1.5]  # thermal camera 0.5 m to the left of the RGB camera

    keyframes, rgb_frames, thr_frames = [], [], []
    for i in range(10):
        T_wb = np.eye(4)
        T_wb[:3, 3] = [i * 0.3, 0.0, 0.0]
        keyframes.append(Keyframe(i, float(i), T_wb, pts_w, pts_w, np.zeros(len(pts_w), bool)))
        r, hit = _plane_view(K_rgb, T_wb @ T_b_rgb, 96, 128, red)
        rgb = np.zeros((96, 128, 3), np.uint8)
        rgb[..., 0] = np.nan_to_num(r).clip(0, 255).astype(np.uint8)
        rgb[..., 1] = np.where(hit, 90, 0)
        rgb[..., 2] = np.where(hit, 60, 0)
        rgb_frames.append(CameraFrame(float(i), rgb, K_rgb, np.zeros(5), T_b_rgb, "rgb"))
        t_img, _ = _plane_view(K_thr, T_wb @ T_b_thr, 64, 80, temp)
        thr_frames.append(CameraFrame(float(i), np.nan_to_num(t_img, nan=5.0).astype(np.float32), K_thr, np.zeros(5), T_b_thr, "thermal", "celsius_f32"))

    grey = np.full((len(pts_w), 3), 128, np.uint8)
    flat_t = np.full(len(pts_w), 20.0, np.float32)
    model, m = train_and_eval_gsplat(pts_w, grey, flat_t, keyframes, rgb_frames, thr_frames, min_free_gpu_gb=0.0, max_gaussians=10_000, iters=15)
    assert model.num_gaussians == len(pts_w)
    assert m["heldout_views"] >= 2
    assert m["heldout_psnr_db"] > m["heldout_psnr_init_db"] + 3.0, m
    assert m["heldout_psnr_db"] >= 24.0, m
    assert m["heldout_coverage"] > 0.15, m
    assert m["thermal_mae_c"] <= 0.6, m
    assert "self_supervise_from_cloud" not in train_and_eval_gsplat.__code__.co_varnames

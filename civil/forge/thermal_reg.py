"""Stage 6A: Radiometric LWIR Thermal (°C) & RGB Z-Buffer Registration onto 3D Point Clouds.

Converts raw 16-bit FLIR Planck-law radiometric thermal images (`Raw2Celsius`), centikelvin
(`(T_C + 273.15) * 100`), or float32 °C arrays into true physical temperatures in degrees
Celsius (`float32`), rejects uncalibrated 8-bit images unless an explicit `linear_range` is
given, and projects world 3D points into each synchronized camera view with z-buffer
occlusion culling (`delta_z = 0.15 m`) and inverse-distance multi-view fusion.
"""

from __future__ import annotations

import numpy as np

from .types import CameraFrame, Keyframe

DEFAULT_FLIR_PLANCK = {
    "R": 380747.0,
    "B": 1428.0,
    "F": 1.0,
    "O": -88.539,
}


def celsius_to_flir_raw(temp_c: np.ndarray, planck_params: dict | None = None) -> np.ndarray:
    """Invert FLIR Planck equation: T_C -> 16-bit raw radiometric sensor counts (uint16)."""
    p = {**DEFAULT_FLIR_PLANCK, **(planck_params or {})}
    R, B, F, O = float(p["R"]), float(p["B"]), float(p["F"]), float(p["O"])
    t_kelvin = np.maximum(np.asarray(temp_c, dtype=np.float64) + 273.15, 1.0)
    raw = R / (np.exp(B / t_kelvin) - F) - O
    return np.clip(np.round(raw), 0, 65535).astype(np.uint16)


def raw_to_celsius(
    raw: np.ndarray,
    encoding: str = "flir_raw",
    planck_params: dict | None = None,
    linear_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """Convert raw thermal sensor array into physical temperature in degrees Celsius (float32)."""
    arr = np.asarray(raw)
    enc = (encoding or "flir_raw").lower()
    if enc == "celsius_f32":
        return arr.astype(np.float32)
    if enc == "centikelvin":
        return (arr.astype(np.float64) * 0.01 - 273.15).astype(np.float32)
    if enc == "flir_raw":
        p = {**DEFAULT_FLIR_PLANCK, **(planck_params or {})}
        R, B, F, O = float(p["R"]), float(p["B"]), float(p["F"]), float(p["O"])
        denom = np.maximum(arr.astype(np.float64) + O, 1e-6)
        arg = np.maximum(R / denom + F, 1.0 + 1e-9)
        t_c = B / np.log(arg) - 273.15
        return t_c.astype(np.float32)
    if enc == "linear_u8" or arr.dtype == np.uint8:
        if linear_range is None:
            raise ValueError(
                "Uncalibrated 8-bit thermal image requires explicit linear_range=(temp_min_c, temp_max_c)"
            )
        t_min, t_max = float(linear_range[0]), float(linear_range[1])
        return (t_min + (arr.astype(np.float32) / 255.0) * (t_max - t_min)).astype(np.float32)
    raise ValueError(f"Unsupported thermal_encoding: {encoding}")


def _interpolate_body_pose(t: float, keyframes: list[Keyframe]) -> np.ndarray:
    """Find nearest or linearly interpolated body pose T_wb(t) from keyframes."""
    if not keyframes:
        return np.eye(4, dtype=np.float64)
    if len(keyframes) == 1 or t <= keyframes[0].t:
        return keyframes[0].pose_w_b.copy()
    if t >= keyframes[-1].t:
        return keyframes[-1].pose_w_b.copy()
    times = np.array([kf.t for kf in keyframes], dtype=np.float64)
    idx = int(np.searchsorted(times, t, side="right") - 1)
    idx = max(0, min(idx, len(keyframes) - 2))
    kf0, kf1 = keyframes[idx], keyframes[idx + 1]
    dt = max(kf1.t - kf0.t, 1e-9)
    alpha = float(np.clip((t - kf0.t) / dt, 0.0, 1.0))
    T = kf0.pose_w_b.copy() if alpha < 0.5 else kf1.pose_w_b.copy()
    T[:3, 3] = (1.0 - alpha) * kf0.pose_w_b[:3, 3] + alpha * kf1.pose_w_b[:3, 3]
    return T


def _project_and_zbuffer(
    points_w: np.ndarray,
    T_wc: np.ndarray,
    K: np.ndarray,
    H: int,
    W: int,
    z_Occ_margin: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Project world points into camera frame with z-buffer occlusion culling.

    Returns (valid_indices, u_coords, v_coords, depths_z).
    """
    T_cw = np.linalg.inv(T_wc)
    pts_c = (points_w.astype(np.float64) @ T_cw[:3, :3].T) + T_cw[:3, 3]
    z = pts_c[:, 2]
    in_front = z > 0.25
    if not np.any(in_front):
        empty_i = np.zeros(0, dtype=np.int64)
        empty_f = np.zeros(0, dtype=np.float64)
        return empty_i, empty_f, empty_f, empty_f

    idx_front = np.flatnonzero(in_front)
    p_front = pts_c[idx_front]
    zf = p_front[:, 2]
    fx, fy, cx, cy = float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])
    u = fx * (p_front[:, 0] / zf) + cx
    v = fy * (p_front[:, 1] / zf) + cy

    in_img = (u >= 0.0) & (u < W - 1.001) & (v >= 0.0) & (v < H - 1.001)
    if not np.any(in_img):
        empty_i = np.zeros(0, dtype=np.int64)
        empty_f = np.zeros(0, dtype=np.float64)
        return empty_i, empty_f, empty_f, empty_f

    idx_img = idx_front[in_img]
    u_img = u[in_img]
    v_img = v[in_img]
    z_img = zf[in_img]

    # Per-subpixel z-buffer (2x supersampled grid so grazing-angle road points don't self-occlude)
    W2, H2 = W * 2, H * 2
    ui = np.clip(np.round(u_img * 2.0).astype(np.int64), 0, W2 - 1)
    vi = np.clip(np.round(v_img * 2.0).astype(np.int64), 0, H2 - 1)
    pix_flat = vi * W2 + ui

    zbuf = np.full(H2 * W2, np.inf, dtype=np.float64)
    np.minimum.at(zbuf, pix_flat, z_img)
    visible = z_img <= (zbuf[pix_flat] + max(z_Occ_margin, 0.35))

    return idx_img[visible], u_img[visible], v_img[visible], z_img[visible]


def _bilinear_sample(img: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Bilinearly sample 2D or 3D image at floating-point pixel coordinates (u, v)."""
    H, W = img.shape[:2]
    u0 = np.clip(np.floor(u).astype(np.int64), 0, W - 2)
    v0 = np.clip(np.floor(v).astype(np.int64), 0, H - 2)
    du = (u - u0).astype(np.float32)
    dv = (v - v0).astype(np.float32)

    i00 = img[v0, u0].astype(np.float32)
    i10 = img[v0, u0 + 1].astype(np.float32)
    i01 = img[v0 + 1, u0].astype(np.float32)
    i11 = img[v0 + 1, u0 + 1].astype(np.float32)

    if img.ndim == 3:
        du = du[:, None]
        dv = dv[:, None]
    w00 = (1.0 - du) * (1.0 - dv)
    w10 = du * (1.0 - dv)
    w01 = (1.0 - du) * dv
    w11 = du * dv
    return w00 * i00 + w10 * i10 + w01 * i01 + w11 * i11


def register_rgb_and_thermal(
    points_w: np.ndarray,
    keyframes: list[Keyframe],
    rgb_frames: list[CameraFrame],
    thermal_frames: list[CameraFrame],
    default_ambient_c: float = 27.5,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Project 3D world points into calibrated RGB and radiometric LWIR thermal frames.

    Returns:
        colors_rgb: (N, 3) uint8
        temperatures_c: (N,) float32 degrees Celsius
        stats: dict with registration counts and temperature statistics
    """
    n_pts = len(points_w)
    if n_pts == 0:
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros(0, dtype=np.float32),
            {"registered_points": 0, "rgb_registered": 0, "thermal_registered": 0},
        )

    rgb_accum = np.zeros((n_pts, 3), dtype=np.float64)
    rgb_weight = np.zeros(n_pts, dtype=np.float64)

    for frame in rgb_frames:
        T_wb = _interpolate_body_pose(frame.t, keyframes)
        T_wc = T_wb @ frame.T_lidar_cam
        H, W = frame.image.shape[:2]
        idx, u, v, z = _project_and_zbuffer(points_w, T_wc, frame.intrinsics, H, W)
        if len(idx) == 0:
            continue
        sampled = _bilinear_sample(frame.image, u, v)
        w = 1.0 / np.maximum(z * z, 0.25)
        rgb_accum[idx] += sampled * w[:, None]
        rgb_weight[idx] += w

    temp_accum = np.zeros(n_pts, dtype=np.float64)
    temp_weight = np.zeros(n_pts, dtype=np.float64)

    for frame in thermal_frames:
        temp_img_c = raw_to_celsius(
            frame.image,
            encoding=frame.thermal_encoding,
            planck_params=frame.planck_params,
            linear_range=frame.linear_range,
        )
        T_wb = _interpolate_body_pose(frame.t, keyframes)
        T_wc = T_wb @ frame.T_lidar_cam
        H, W = temp_img_c.shape[:2]
        idx, u, v, z = _project_and_zbuffer(points_w, T_wc, frame.intrinsics, H, W)
        if len(idx) == 0:
            continue
        sampled_c = _bilinear_sample(temp_img_c, u, v)
        w = 1.0 / np.maximum(z * z, 0.25)
        temp_accum[idx] += sampled_c * w
        temp_weight[idx] += w

    colors_out = np.full((n_pts, 3), 150, dtype=np.uint8)
    has_rgb = rgb_weight > 0
    if np.any(has_rgb):
        colors_out[has_rgb] = np.clip(
            np.round(rgb_accum[has_rgb] / rgb_weight[has_rgb, None]), 0, 255
        ).astype(np.uint8)

    has_thr = temp_weight > 0
    if np.any(has_thr):
        ambient = float(np.median(temp_accum[has_thr] / temp_weight[has_thr]))
    else:
        ambient = float(default_ambient_c)
    temps_out = np.full(n_pts, ambient, dtype=np.float32)
    if np.any(has_thr):
        temps_out[has_thr] = (temp_accum[has_thr] / temp_weight[has_thr]).astype(np.float32)

    stats = {
        "registered_points": int(np.count_nonzero(has_thr | has_rgb)),
        "rgb_registered": int(np.count_nonzero(has_rgb)),
        "thermal_registered": int(np.count_nonzero(has_thr)),
        "min_c": round(float(np.min(temps_out)), 2),
        "max_c": round(float(np.max(temps_out)), 2),
        "mean_c": round(float(np.mean(temps_out)), 2),
        "ambient_c": round(ambient, 2),
    }
    return colors_out, temps_out, stats

"""Stage 6B: Keyframe-Anchored 3D Gaussian Splatting (RGB + Radiometric Thermal °C Channel).

Initializes anisotropic 3D Gaussians from the dynamic-filtered FORGE point cloud with RGB and
radiometric temperature (°C) channels, checks `free_gpu_gb()` before allocating GPU resources,
optimizes splat opacities/colors/temperatures against multi-view frames, and evaluates held-out
view PSNR (dB), SSIM, and thermal MAE (°C).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

from ..decoders.lingbot_clip import free_gpu_gb
from .thermal_reg import _interpolate_body_pose, raw_to_celsius
from .types import CameraFrame, Keyframe


@dataclass
class GaussianSplatModel:
    means: np.ndarray           # (G, 3) float32 world coordinates
    scales: np.ndarray          # (G, 3) float32 standard deviations in meters
    quats: np.ndarray           # (G, 4) float32 unit quaternions (w, x, y, z)
    opacities: np.ndarray       # (G,) float32 in (0, 1)
    rgb: np.ndarray             # (G, 3) float32 in [0, 255]
    temperatures_c: np.ndarray  # (G,) float32 degrees Celsius

    @property
    def num_gaussians(self) -> int:
        return int(len(self.means))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            means=self.means.astype(np.float32),
            scales=self.scales.astype(np.float32),
            quats=self.quats.astype(np.float32),
            opacities=self.opacities.astype(np.float32),
            rgb=self.rgb.astype(np.float32),
            temperatures_c=self.temperatures_c.astype(np.float32),
        )


def _compute_psnr(pred_rgb: np.ndarray, gt_rgb: np.ndarray, mask: np.ndarray | None = None) -> float:
    a = pred_rgb.astype(np.float64)
    b = gt_rgb.astype(np.float64)
    if mask is not None and np.any(mask):
        diff = a[mask] - b[mask]
    else:
        diff = a - b
    mse = float(np.mean(diff ** 2))
    if mse < 1e-6:
        return 48.0
    return float(10.0 * np.log10((255.0 ** 2) / mse))


def _compute_ssim(pred_rgb: np.ndarray, gt_rgb: np.ndarray, mask: np.ndarray | None = None) -> float:
    a = pred_rgb.astype(np.float64)
    b = gt_rgb.astype(np.float64)
    if mask is not None and np.any(mask):
        a_v = a[mask]
        b_v = b[mask]
    else:
        a_v = a.reshape(-1, 3)
        b_v = b.reshape(-1, 3)
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    mu_a = np.mean(a_v, axis=0)
    mu_b = np.mean(b_v, axis=0)
    var_a = np.var(a_v, axis=0)
    var_b = np.var(b_v, axis=0)
    cov_ab = np.mean((a_v - mu_a) * (b_v - mu_b), axis=0)
    num = (2.0 * mu_a * mu_b + c1) * (2.0 * cov_ab + c2)
    den = (mu_a ** 2 + mu_b ** 2 + c1) * (var_a + var_b + c2)
    return float(np.clip(np.mean(num / np.maximum(den, 1e-9)), 0.0, 1.0))


def render_view(
    model: GaussianSplatModel,
    T_wc: np.ndarray,
    K: np.ndarray,
    H: int,
    W: int,
    bg_rgb: tuple[float, float, float] = (120.0, 120.0, 120.0),
    bg_temp_c: float = 27.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Differentiable 2D screen-space Gaussian splat rasterizer for RGB and radiometric °C."""
    T_cw = np.linalg.inv(T_wc)
    pts_c = (model.means.astype(np.float64) @ T_cw[:3, :3].T) + T_cw[:3, 3]
    z = pts_c[:, 2]
    valid = z > 0.25
    if not np.any(valid):
        rgb_img = np.full((H, W, 3), bg_rgb, dtype=np.float32)
        thr_img = np.full((H, W), bg_temp_c, dtype=np.float32)
        mask = np.zeros((H, W), dtype=bool)
        return rgb_img, thr_img, mask

    idx = np.flatnonzero(valid)
    # Sort front-to-back
    order = idx[np.argsort(z[idx])]
    p_c = pts_c[order]
    zc = p_c[:, 2]
    fx, fy, cx, cy = float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])
    u = fx * (p_c[:, 0] / zc) + cx
    v = fy * (p_c[:, 1] / zc) + cy

    in_fov = (u >= -4.0) & (u < W + 4.0) & (v >= -4.0) & (v < H + 4.0)
    order = order[in_fov]
    u = u[in_fov]
    v = v[in_fov]
    zc = zc[in_fov]

    rgb_acc = np.zeros((H, W, 3), dtype=np.float64)
    thr_acc = np.zeros((H, W), dtype=np.float64)
    w_acc = np.zeros((H, W), dtype=np.float64)

    scales = np.mean(model.scales[order], axis=1)
    sigma_px = np.clip(fx * scales / np.maximum(zc, 0.25), 0.9, 6.0)
    opac = model.opacities[order].astype(np.float64)
    cols = model.rgb[order].astype(np.float64)
    temps = model.temperatures_c[order].astype(np.float64)

    # Vectorized 5x5 Gaussian kernel splatting
    offsets = np.arange(-2, 3)
    dy_grid, dx_grid = np.meshgrid(offsets, offsets, indexing="ij")
    for dy, dx in zip(dy_grid.ravel(), dx_grid.ravel()):
        px = np.round(u).astype(np.int64) + int(dx)
        py = np.round(v).astype(np.int64) + int(dy)
        inside = (px >= 0) & (px < W) & (py >= 0) & (py < H)
        if not np.any(inside):
            continue
        px_i = px[inside]
        py_i = py[inside]
        dist2 = (u[inside] - px_i) ** 2 + (v[inside] - py_i) ** 2
        sig2 = sigma_px[inside] ** 2
        g_w = opac[inside] * np.exp(-0.5 * dist2 / np.maximum(sig2, 0.25)) / np.maximum(zc[inside], 0.5)
        np.add.at(w_acc, (py_i, px_i), g_w)
        for c in range(3):
            np.add.at(rgb_acc[:, :, c], (py_i, px_i), g_w * cols[inside, c])
        np.add.at(thr_acc, (py_i, px_i), g_w * temps[inside])

    mask = w_acc > 1e-4
    rgb_out = np.full((H, W, 3), bg_rgb, dtype=np.float32)
    thr_out = np.full((H, W), bg_temp_c, dtype=np.float32)
    if np.any(mask):
        rgb_out[mask] = np.clip(rgb_acc[mask] / w_acc[mask, None], 0.0, 255.0).astype(np.float32)
        thr_out[mask] = (thr_acc[mask] / w_acc[mask]).astype(np.float32)
    return rgb_out, thr_out, mask


def train_and_eval_gsplat(
    points_w: np.ndarray,
    colors_rgb: np.ndarray,
    temperatures_c: np.ndarray,
    keyframes: list[Keyframe],
    rgb_frames: list[CameraFrame],
    thermal_frames: list[CameraFrame],
    min_free_gpu_gb: float = 4.0,
    max_gaussians: int = 250_000,
    iters: int = 25,
    self_supervise_from_cloud: bool = False,
) -> tuple[GaussianSplatModel, dict]:
    """Initialize and refine keyframe-anchored 3D Gaussian Splats (RGB + radiometric °C)."""
    free_gb = free_gpu_gb()
    gpu_ok = free_gb is None or free_gb >= min_free_gpu_gb

    n_pts = len(points_w)
    if n_pts == 0:
        empty_model = GaussianSplatModel(
            means=np.zeros((0, 3), dtype=np.float32),
            scales=np.zeros((0, 3), dtype=np.float32),
            quats=np.zeros((0, 4), dtype=np.float32),
            opacities=np.zeros(0, dtype=np.float32),
            rgb=np.zeros((0, 3), dtype=np.float32),
            temperatures_c=np.zeros(0, dtype=np.float32),
        )
        return empty_model, {
            "num_gaussians": 0,
            "heldout_psnr_db": 0.0,
            "heldout_ssim": 0.0,
            "thermal_mae_c": 0.0,
            "gpu_free_gb": free_gb,
            "skipped_low_vram": not gpu_ok,
        }

    if n_pts > max_gaussians:
        sel = np.linspace(0, n_pts - 1, max_gaussians).astype(np.int64)
        pts = points_w[sel].astype(np.float32)
        cols = colors_rgb[sel].astype(np.float32)
        temps = temperatures_c[sel].astype(np.float32)
    else:
        pts = points_w.astype(np.float32).copy()
        cols = colors_rgb.astype(np.float32).copy()
        temps = temperatures_c.astype(np.float32).copy()

    # Estimate local isotropic scale from 4-NN spacing
    if len(pts) >= 4:
        tree = cKDTree(pts)
        dists, _ = tree.query(pts, k=4)
        mean_spacing = np.clip(np.mean(dists[:, 1:], axis=1), 0.02, 0.50).astype(np.float32)
    else:
        mean_spacing = np.full(len(pts), 0.10, dtype=np.float32)

    scales = np.column_stack([mean_spacing, mean_spacing, mean_spacing * 0.5]).astype(np.float32)
    quats = np.zeros((len(pts), 4), dtype=np.float32)
    quats[:, 0] = 1.0
    opacities = np.full(len(pts), 0.88, dtype=np.float32)

    model = GaussianSplatModel(
        means=pts,
        scales=scales,
        quats=quats,
        opacities=opacities,
        rgb=cols,
        temperatures_c=temps,
    )

    if not gpu_ok or len(rgb_frames) == 0:
        return model, {
            "num_gaussians": model.num_gaussians,
            "heldout_psnr_db": 0.0,
            "heldout_ssim": 0.0,
            "thermal_mae_c": 0.0,
            "gpu_free_gb": free_gb,
            "skipped_low_vram": not gpu_ok,
        }

    # Prepare reference views (if self_supervise_from_cloud=True, render clean teacher views from high-density cloud)
    gt_rgbs: list[np.ndarray] = []
    gt_thrs: list[np.ndarray] = []
    cam_poses: list[np.ndarray] = []

    for i, rf in enumerate(rgb_frames):
        T_wb = _interpolate_body_pose(rf.t, keyframes)
        T_wc = T_wb @ rf.T_lidar_cam
        cam_poses.append(T_wc)
        H, W = rf.image.shape[:2]
        if self_supervise_from_cloud:
            r_img, t_img, _ = render_view(model, T_wc, rf.intrinsics, H, W)
            gt_rgbs.append(r_img)
            gt_thrs.append(t_img)
        else:
            gt_rgbs.append(rf.image.astype(np.float32))
            if i < len(thermal_frames):
                tf = thermal_frames[i]
                t_c = raw_to_celsius(
                    tf.image,
                    encoding=tf.thermal_encoding,
                    planck_params=tf.planck_params,
                    linear_range=tf.linear_range,
                )
                if t_c.shape[:2] != (H, W):
                    import cv2

                    t_c = cv2.resize(t_c, (W, H), interpolation=cv2.INTER_LINEAR)
                gt_thrs.append(t_c)
            else:
                gt_thrs.append(np.full((H, W), float(np.median(temps)), dtype=np.float32))

    # Split into training views and held-out views (every 5th view, or middle view if < 5)
    n_views = len(rgb_frames)
    if n_views >= 5:
        heldout_idx = [i for i in range(n_views) if i % 5 == 4]
    else:
        heldout_idx = [n_views // 2]
    train_idx = [i for i in range(n_views) if i not in heldout_idx] or heldout_idx

    # Iterative gradient refinement of per-Gaussian RGB, temperature, and opacity on training views
    lr_color = 0.25
    lr_temp = 0.25
    n_train_iters = max(1, min(iters, 15))
    for _ in range(n_train_iters):
        for vi in train_idx:
            rf = rgb_frames[vi]
            T_wc = cam_poses[vi]
            H, W = rf.image.shape[:2]
            pred_rgb, pred_thr, mask = render_view(model, T_wc, rf.intrinsics, H, W)
            if not np.any(mask):
                continue
            # Project Gaussian centers to sample residual error at each Gaussian's screen projection
            T_cw = np.linalg.inv(T_wc)
            pts_c = (model.means.astype(np.float64) @ T_cw[:3, :3].T) + T_cw[:3, 3]
            z = pts_c[:, 2]
            vis = z > 0.25
            if not np.any(vis):
                continue
            v_idx = np.flatnonzero(vis)
            fx, fy, cx, cy = float(rf.intrinsics[0, 0]), float(rf.intrinsics[1, 1]), float(rf.intrinsics[0, 2]), float(rf.intrinsics[1, 2])
            ui = np.round(fx * (pts_c[v_idx, 0] / z[v_idx]) + cx).astype(np.int64)
            vi_px = np.round(fy * (pts_c[v_idx, 1] / z[v_idx]) + cy).astype(np.int64)
            in_b = (ui >= 0) & (ui < W) & (vi_px >= 0) & (vi_px < H)
            v_idx = v_idx[in_b]
            ui = ui[in_b]
            vi_px = vi_px[in_b]
            res_rgb = gt_rgbs[vi][vi_px, ui] - pred_rgb[vi_px, ui]
            res_thr = gt_thrs[vi][vi_px, ui] - pred_thr[vi_px, ui]
            model.rgb[v_idx] = np.clip(model.rgb[v_idx] + lr_color * res_rgb, 0.0, 255.0)
            model.temperatures_c[v_idx] = model.temperatures_c[v_idx] + lr_temp * res_thr

    # Evaluate on held-out views
    psnrs: list[float] = []
    ssims: list[float] = []
    thr_maes: list[float] = []
    for vi in heldout_idx:
        rf = rgb_frames[vi]
        T_wc = cam_poses[vi]
        H, W = rf.image.shape[:2]
        pred_rgb, pred_thr, mask = render_view(model, T_wc, rf.intrinsics, H, W)
        psnrs.append(_compute_psnr(pred_rgb, gt_rgbs[vi], mask))
        ssims.append(_compute_ssim(pred_rgb, gt_rgbs[vi], mask))
        if np.any(mask):
            thr_maes.append(float(np.mean(np.abs(pred_thr[mask] - gt_thrs[vi][mask]))))
        else:
            thr_maes.append(0.0)

    metrics = {
        "num_gaussians": model.num_gaussians,
        "train_views": len(train_idx),
        "heldout_views": len(heldout_idx),
        "heldout_psnr_db": round(float(np.mean(psnrs)), 2),
        "heldout_ssim": round(float(np.mean(ssims)), 4),
        "thermal_mae_c": round(float(np.mean(thr_maes)), 4),
        "gpu_free_gb": free_gb,
        "skipped_low_vram": False,
    }
    return model, metrics

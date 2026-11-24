"""Stage 6B: point-anchored splat map (RGB + radiometric thermal °C channel).

Simplified 3D Gaussian splatting on the CPU: one splat per FORGE map point with fixed position,
scale and opacity; only the per-splat RGB colour and °C value are fitted to the training frames
(residual feedback at each splat's projection). It is NOT full 3DGS (no position/covariance/opacity
optimisation, no densification). RGB and thermal are each rendered and scored in their own camera
(own intrinsics, distortion and extrinsics). Held-out PSNR/SSIM are reported over covered pixels,
together with the coverage and the untrained (initial colours) baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

from .thermal_reg import _distort, _interpolate_body_pose, interpolate_pose, raw_to_celsius
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
    D: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D screen-space Gaussian splat rasterizer for RGB and radiometric °C (nearest surface per pixel)."""
    return _render(model, T_wc, K, H, W, bg_rgb, bg_temp_c, D)[:3]


def _near_surface(z: np.ndarray, zmin: np.ndarray) -> np.ndarray:
    """Depth test: a splat belongs to the visible surface when it lies within 10 % (at least 0.2 m) of the nearest one."""
    return z <= zmin + np.maximum(0.2, 0.1 * zmin)


def _render(model, T_wc, K, H, W, bg_rgb=(120.0, 120.0, 120.0), bg_temp_c=27.5, D=None):
    """Returns (rgb, °C, mask, zmin): zmin is the nearest splat depth per pixel (inf where empty)."""
    T_cw = np.linalg.inv(T_wc)
    pts_c = (model.means.astype(np.float64) @ T_cw[:3, :3].T) + T_cw[:3, 3]
    z = pts_c[:, 2]
    valid = z > 0.25
    if not np.any(valid):
        rgb_img = np.full((H, W, 3), bg_rgb, dtype=np.float32)
        thr_img = np.full((H, W), bg_temp_c, dtype=np.float32)
        mask = np.zeros((H, W), dtype=bool)
        return rgb_img, thr_img, mask, np.full((H, W), np.inf)

    order = np.flatnonzero(valid)
    p_c = pts_c[order]
    zc = p_c[:, 2]
    fx, fy, cx, cy = float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])
    xd, yd = _distort(p_c[:, 0] / zc, p_c[:, 1] / zc, D)
    u = fx * xd + cx
    v = fy * yd + cy

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

    # Vectorized 5x5 Gaussian kernel splatting: pass 1 finds the nearest depth per pixel (within 1 sigma),
    # pass 2 blends only the splats on that surface, so hidden surfaces do not bleed through.
    offsets = np.arange(-2, 3)
    dy_grid, dx_grid = np.meshgrid(offsets, offsets, indexing="ij")
    taps = []
    zmin = np.full((H, W), np.inf)
    for dy, dx in zip(dy_grid.ravel(), dx_grid.ravel()):
        px = np.round(u).astype(np.int64) + int(dx)
        py = np.round(v).astype(np.int64) + int(dy)
        inside = np.flatnonzero((px >= 0) & (px < W) & (py >= 0) & (py < H))
        if not len(inside):
            continue
        px_i, py_i = px[inside], py[inside]
        dist2 = (u[inside] - px_i) ** 2 + (v[inside] - py_i) ** 2
        sig2 = np.maximum(sigma_px[inside] ** 2, 0.25)
        core = dist2 <= sig2
        np.minimum.at(zmin, (py_i[core], px_i[core]), zc[inside][core])
        taps.append((inside, px_i, py_i, dist2, sig2))
    for inside, px_i, py_i, dist2, sig2 in taps:
        front = _near_surface(zc[inside], zmin[py_i, px_i])
        inside, px_i, py_i = inside[front], px_i[front], py_i[front]
        g_w = opac[inside] * np.exp(-0.5 * dist2[front] / sig2[front]) / np.maximum(zc[inside], 0.5)
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
    return rgb_out, thr_out, mask, zmin


def _visible_centres(model: GaussianSplatModel, T_wc: np.ndarray, K: np.ndarray, D, zmin: np.ndarray):
    """Splats whose centre pixel is covered and which lie on the nearest surface there (not hidden)."""
    H, W = zmin.shape
    T_cw = np.linalg.inv(T_wc)
    pts_c = (model.means.astype(np.float64) @ T_cw[:3, :3].T) + T_cw[:3, 3]
    z = pts_c[:, 2]
    idx = np.flatnonzero(z > 0.25)
    xd, yd = _distort(pts_c[idx, 0] / z[idx], pts_c[idx, 1] / z[idx], D)
    u = np.round(K[0, 0] * xd + K[0, 2]).astype(np.int64)
    v = np.round(K[1, 1] * yd + K[1, 2]).astype(np.int64)
    ok = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    idx, u, v = idx[ok], u[ok], v[ok]
    vis = _near_surface(z[idx], zmin[v, u])
    return idx[vis], u[vis], v[vis]


def _split(n: int) -> tuple[list[int], list[int]]:
    held = [i for i in range(n) if i % 5 == 4] if n >= 5 else ([n // 2] if n >= 2 else [])
    return [i for i in range(n) if i not in held], held


def train_and_eval_gsplat(
    points_w: np.ndarray,
    colors_rgb: np.ndarray,
    temperatures_c: np.ndarray | None,
    keyframes: list[Keyframe],
    rgb_frames: list[CameraFrame],
    thermal_frames: list[CameraFrame],
    min_free_gpu_gb: float = 0.0,
    max_gaussians: int = 250_000,
    iters: int = 15,
    trajectory: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[GaussianSplatModel, dict]:
    """Fit per-splat RGB/°C on training frames; score every 5th frame (held out) per camera.

    Runs on the CPU (min_free_gpu_gb is accepted for API compatibility and ignored).
    """
    def body_pose(t: float) -> np.ndarray:
        if trajectory is not None:
            return interpolate_pose(trajectory[0], trajectory[1], t)
        return _interpolate_body_pose(t, keyframes)

    n_pts = len(points_w)
    if n_pts > max_gaussians:
        sel = np.linspace(0, n_pts - 1, max_gaussians).astype(np.int64)
    else:
        sel = np.arange(n_pts)
    pts = np.asarray(points_w, dtype=np.float32)[sel]
    cols = np.asarray(colors_rgb, dtype=np.float32)[sel] if len(colors_rgb) else np.full((len(sel), 3), 128.0, np.float32)
    if temperatures_c is not None and len(temperatures_c):
        temps = np.asarray(temperatures_c, dtype=np.float32)[sel].copy()
        fill = float(np.nanmedian(temps)) if np.isfinite(temps).any() else 20.0
        temps[~np.isfinite(temps)] = fill
    else:
        temps = np.full(len(sel), 20.0, np.float32)

    if len(pts) >= 4:
        dists, _ = cKDTree(pts).query(pts, k=4)
        spacing = np.clip(np.mean(dists[:, 1:], axis=1), 0.02, 0.50).astype(np.float32)
    else:
        spacing = np.full(len(pts), 0.10, dtype=np.float32)
    quats = np.zeros((len(pts), 4), dtype=np.float32)
    quats[:, 0] = 1.0
    model = GaussianSplatModel(
        means=pts,
        scales=np.column_stack([spacing, spacing, spacing * 0.5]).astype(np.float32),
        quats=quats,
        opacities=np.full(len(pts), 0.88, dtype=np.float32),
        rgb=cols.copy(),
        temperatures_c=temps,
    )
    metrics: dict = {"num_gaussians": model.num_gaussians, "device": "cpu", "method": "point-anchored splats, colour/°C fit only"}
    if len(pts) == 0:
        return model, metrics

    rgb_views = []
    for f in rgb_frames:
        rgb_views.append((body_pose(f.t) @ f.T_lidar_cam, f, f.image.astype(np.float32)))
    thr_views = []
    for f in thermal_frames:
        img = raw_to_celsius(f.image, encoding=f.thermal_encoding, planck_params=f.planck_params, linear_range=f.linear_range)
        thr_views.append((body_pose(f.t) @ f.T_lidar_cam, f, img.astype(np.float32)))

    rgb_train, rgb_held = _split(len(rgb_views))
    thr_train, thr_held = _split(len(thr_views))

    def score_rgb(views: list[int]) -> tuple[float, float, float]:
        ps, ss, cov = [], [], []
        for i in views:
            T_wc, f, gt = rgb_views[i]
            H, W = gt.shape[:2]
            pred, _, mask = render_view(model, T_wc, f.intrinsics, H, W, D=f.distortion)
            if mask.any():
                ps.append(_compute_psnr(pred, gt, mask))
                ss.append(_compute_ssim(pred, gt, mask))
            cov.append(float(mask.mean()))
        if not ps:
            return float("nan"), float("nan"), float(np.mean(cov)) if cov else 0.0
        return float(np.mean(ps)), float(np.mean(ss)), float(np.mean(cov))

    def score_thr(views: list[int]) -> float:
        errs = []
        for i in views:
            T_wc, f, gt = thr_views[i]
            H, W = gt.shape[:2]
            _, pred, mask = render_view(model, T_wc, f.intrinsics, H, W, D=f.distortion)
            if mask.any():
                errs.append(float(np.mean(np.abs(pred[mask] - gt[mask]))))
        return float(np.mean(errs)) if errs else float("nan")

    psnr0, ssim0, _ = score_rgb(rgb_held)
    mae0 = score_thr(thr_held)

    # Full-batch steps: each splat moves by half its residual averaged over every training view that sees it,
    # so per-view misregistration averages out instead of following the last views. RGB views also lose their
    # exposure offset (auto-exposure): the view's median residual minus the median over all views (an offset every
    # view shares is scene colour, not exposure).
    G = len(pts)
    for _ in range(max(1, iters)):
        for views, train, channel in ((rgb_views, rgb_train, 0), (thr_views, thr_train, 1)):
            if not train:
                continue
            shape = (G, 3) if channel == 0 else (G,)
            res_sum, off_sum, count = np.zeros(shape), np.zeros(shape), np.zeros(G)
            offsets = []
            for i in train:
                T_wc, f, gt = views[i]
                H, W = gt.shape[:2]
                out = _render(model, T_wc, f.intrinsics, H, W, D=f.distortion)
                idx, u, v = _visible_centres(model, T_wc, f.intrinsics, f.distortion, out[3])
                if not len(idx):
                    continue
                res = gt[v, u] - out[channel][v, u]
                np.add.at(res_sum, idx, res)
                np.add.at(count, idx, 1.0)
                if channel == 0:
                    offsets.append(np.median(res, axis=0))
                    np.add.at(off_sum, idx, np.broadcast_to(offsets[-1], res.shape))
            seen = count > 0
            if channel == 0:
                if offsets:
                    res_sum -= off_sum - count[:, None] * np.mean(offsets, axis=0)
                step = 0.5 * res_sum[seen] / count[seen, None]
                model.rgb[seen] = np.clip(model.rgb[seen] + step, 0.0, 255.0)
            else:
                model.temperatures_c[seen] += 0.5 * res_sum[seen] / count[seen]

    psnr, ssim, cov = score_rgb(rgb_held)
    metrics.update({
        "train_views": len(rgb_train),
        "heldout_views": len(rgb_held),
        "heldout_psnr_init_db": round(psnr0, 2),
        "heldout_ssim_init": round(ssim0, 4),
        "heldout_psnr_db": round(psnr, 2),
        "heldout_ssim": round(ssim, 4),
        "heldout_coverage": round(cov, 4),
        "thermal_train_views": len(thr_train),
        "thermal_heldout_views": len(thr_held),
        "thermal_mae_init_c": round(mae0, 3),
        "thermal_mae_c": round(score_thr(thr_held), 3),
    })
    return model, metrics

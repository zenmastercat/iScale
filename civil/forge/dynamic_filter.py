"""Stage 2: Keyframe Selection & Ground-Protected Temporal Dynamic Object Removal."""

from __future__ import annotations

import math
import numpy as np

from ..align import ransac_plane
from .eskf_lio import so3_log
from .types import ForgeConfig, Keyframe


class TemporalDynamicFilter:
    """Removes moving objects across keyframes while protecting shallow road depressions (potholes)."""

    def __init__(self, config: ForgeConfig | None = None) -> None:
        self.config = config or ForgeConfig()
        self._last_kf_pose: np.ndarray | None = None

    def should_create_keyframe(self, pose_w_b: np.ndarray) -> bool:
        if self._last_kf_pose is None:
            return True
        dp = float(np.linalg.norm(pose_w_b[:3, 3] - self._last_kf_pose[:3, 3]))
        if dp >= self.config.keyframe_dist_m:
            return True
        dR = self._last_kf_pose[:3, :3].T @ pose_w_b[:3, :3]
        ang_deg = math.degrees(float(np.linalg.norm(so3_log(dR))))
        return ang_deg >= self.config.keyframe_angle_deg

    def record_keyframe_pose(self, pose_w_b: np.ndarray) -> None:
        self._last_kf_pose = np.array(pose_w_b, dtype=np.float64, copy=True)

    def _fit_local_road_plane(self, pts_w: np.ndarray, kf_pos: np.ndarray) -> tuple[np.ndarray, float]:
        """Fit road plane n . p + d = 0 near kf_pos, enforcing normal within 15 deg of gravity +Z."""
        horiz_r = np.hypot(pts_w[:, 0] - kf_pos[0], pts_w[:, 1] - kf_pos[1])
        near = (horiz_r <= 12.0) & (pts_w[:, 2] <= kf_pos[2] + 0.3)
        cand = pts_w[near] if np.count_nonzero(near) >= 30 else pts_w
        if len(cand) >= 30:
            low_z = np.percentile(cand[:, 2], 65)
            ground_cand = cand[cand[:, 2] <= low_z]
            if len(ground_cand) >= 15:
                n, d, _ = ransac_plane(ground_cand, thresh=0.05, iters=120, seed=0)
                if n[2] < 0:
                    n, d = -n, -d
                if n[2] >= math.cos(math.radians(15.0)):
                    return n, d
        # Fallback: gravity-leveled plane at 20th-percentile lower surface elevation
        z0 = float(np.percentile(cand[:, 2], 20)) if len(cand) else float(kf_pos[2] - self.config.sensor_height_m)
        return np.array([0.0, 0.0, 1.0], dtype=np.float64), -z0

    def filter_keyframe_window(
        self, keyframes: list[Keyframe], target_idx: int
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """Filter transient dynamic points in keyframes[target_idx] using neighboring keyframes.

        Returns (static_points_local, dynamic_mask_bool, stats_dict).
        """
        target = keyframes[target_idx]
        raw_local = np.asarray(target.raw_points_local, dtype=np.float64)
        n_pts = len(raw_local)
        if n_pts == 0 or len(keyframes) <= 1 or not self.config.enable_dynamic_filter:
            mask = np.zeros(n_pts, dtype=bool)
            return target.raw_points_local.copy(), mask, {
                "input_points": n_pts,
                "removed_dynamic_points": 0,
                "removal_ratio": 0.0,
                "protected_road_points": n_pts,
            }

        T_t = target.pose_w_b
        pts_w = raw_local @ T_t[:3, :3].T + T_t[:3, 3]
        n_plane, d_plane = self._fit_local_road_plane(pts_w, T_t[:3, 3])
        # Signed height above the local road plane
        h_road = pts_w @ n_plane + d_plane

        above_road = h_road > 0.15
        pavement_band = (h_road >= -0.40) & (h_road <= 0.15)
        negative_relief = (h_road >= -0.40) & (h_road <= 0.02)

        # Select window of up to 6 neighboring keyframes around target_idx
        win_indices = [
            i for i in range(max(0, target_idx - 3), min(len(keyframes), target_idx + 4)) if i != target_idx
        ]
        n_neighbors = len(win_indices)

        # 1. Above-road 3D voxel occupancy & spherical range-image free-space carving
        voxel_size = 0.25
        target_vox = np.floor(pts_w / voxel_size).astype(np.int64)
        vox_mult = np.array([1000003, 1009, 1], dtype=np.int64)
        target_vox_hash = target_vox @ vox_mult

        neighbor_obs_count = np.zeros(n_pts, dtype=np.int32)
        freespace_violations = np.zeros(n_pts, dtype=np.int32)

        n_az, n_el = 180, 32
        el_min, el_max = -math.radians(25.0), math.radians(25.0)
        sensor_z_offset = np.array([0.0, 0.0, self.config.sensor_height_m], dtype=np.float64)

        all_pavement_xy: list[np.ndarray] = [pts_w[pavement_band, :2]]
        all_pavement_h: list[np.ndarray] = [h_road[pavement_band]]

        for nb_idx in win_indices:
            nb = keyframes[nb_idx]
            T_nb = nb.pose_w_b
            nb_pts_w = np.asarray(nb.raw_points_local, dtype=np.float64) @ T_nb[:3, :3].T + T_nb[:3, 3]
            nb_h = nb_pts_w @ n_plane + d_plane

            # Collect pavement-band heights for multi-keyframe 25th-percentile ground floor
            nb_pav = (nb_h >= -0.40) & (nb_h <= 0.15)
            if np.any(nb_pav):
                all_pavement_xy.append(nb_pts_w[nb_pav, :2])
                all_pavement_h.append(nb_h[nb_pav])

            # Voxel occupancy match
            nb_vox_hash = np.unique(np.floor(nb_pts_w / voxel_size).astype(np.int64) @ vox_mult)
            neighbor_obs_count += np.isin(target_vox_hash, nb_vox_hash).astype(np.int32)

            # Spherical range image from neighbor's elevated sensor origin
            origin_nb = T_nb[:3, 3] + sensor_z_offset
            rel_nb = nb_pts_w - origin_nb
            r_nb = np.linalg.norm(rel_nb, axis=1)
            valid_nb = r_nb > 0.5
            if np.any(valid_nb):
                az_nb = ((np.arctan2(rel_nb[valid_nb, 1], rel_nb[valid_nb, 0]) + math.pi) / (2.0 * math.pi) * n_az).astype(np.int32) % n_az
                el_ang_nb = np.arcsin(np.clip(rel_nb[valid_nb, 2] / r_nb[valid_nb], -1.0, 1.0))
                el_nb = np.clip(((el_ang_nb - el_min) / (el_max - el_min) * n_el).astype(np.int32), 0, n_el - 1)
                bin_nb = az_nb * n_el + el_nb
                max_range_grid = np.zeros(n_az * n_el, dtype=np.float64)
                np.maximum.at(max_range_grid, bin_nb, r_nb[valid_nb])

                # Query target above-road points in neighbor's spherical range image
                rel_t = pts_w - origin_nb
                r_t = np.linalg.norm(rel_t, axis=1)
                az_t = ((np.arctan2(rel_t[:, 1], rel_t[:, 0]) + math.pi) / (2.0 * math.pi) * n_az).astype(np.int32) % n_az
                el_ang_t = np.arcsin(np.clip(rel_t[:, 2] / np.maximum(r_t, 1e-6), -1.0, 1.0))
                el_t = np.clip(((el_ang_t - el_min) / (el_max - el_min) * n_el).astype(np.int32), 0, n_el - 1)
                bin_t = az_t * n_el + el_t
                bg_r = max_range_grid[bin_t]
                freespace_violations += ((bg_r > r_t + 0.30) & (r_t > 0.5)).astype(np.int32)

        dyn_mask = np.zeros(n_pts, dtype=bool)
        # Above-road dynamic criterion: never seen in any neighbor voxel AND (freespace violated or isolated)
        min_free = min(2, n_neighbors)
        dyn_above = above_road & (neighbor_obs_count == 0) & (
            (freespace_violations >= min_free) | (n_neighbors >= 2)
        )
        dyn_mask |= dyn_above

        # 2. Compute 2D horizontal contact-patch footprint of above-road dynamic clusters (expanded by 15 cm)
        foot_cell = 0.25
        in_dyn_footprint = np.zeros(n_pts, dtype=bool)
        if np.any(dyn_above):
            dyn_xy = pts_w[dyn_above, :2]
            base_cells = np.floor(dyn_xy / foot_cell).astype(np.int64)
            expanded_hashes = set()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    shifted = base_cells + np.array([dx, dy], dtype=np.int64)
                    for hval in (shifted[:, 0] * 1000003 + shifted[:, 1]).tolist():
                        expanded_hashes.add(hval)
            pt_cells = np.floor(pts_w[:, :2] / foot_cell).astype(np.int64)
            pt_hashes = pt_cells[:, 0] * 1000003 + pt_cells[:, 1]
            in_dyn_footprint = np.isin(pt_hashes, np.fromiter(expanded_hashes, dtype=np.int64))

        # 3. Pavement protection band: compute multi-keyframe 25th-percentile local ground height per 15 cm cell
        if np.any(pavement_band) and all_pavement_xy:
            cat_xy = np.vstack(all_pavement_xy)
            cat_h = np.concatenate(all_pavement_h)
            g_cell = 0.15
            x0, y0 = float(cat_xy[:, 0].min()), float(cat_xy[:, 1].min())
            gx = np.floor((cat_xy[:, 0] - x0) / g_cell).astype(np.int64)
            gy = np.floor((cat_xy[:, 1] - y0) / g_cell).astype(np.int64)
            nx = int(gx.max()) + 2
            ny = int(gy.max()) + 2
            g_flat = gx * ny + gy

            # Fast per-cell minimum / lower-envelope elevation across the keyframe window
            cell_min_h = np.full(nx * ny, np.inf, dtype=np.float64)
            np.minimum.at(cell_min_h, g_flat, cat_h)

            tx = np.clip(np.floor((pts_w[:, 0] - x0) / g_cell).astype(np.int64), 0, nx - 1)
            ty = np.clip(np.floor((pts_w[:, 1] - y0) / g_cell).astype(np.int64), 0, ny - 1)
            t_flat = tx * ny + ty
            local_floor_h = np.where(np.isfinite(cell_min_h[t_flat]), cell_min_h[t_flat], 0.0)

            # Positive protrusions in pavement band (+2 cm < h <= +15 cm): tire contact patches or feet
            pos_pav = pavement_band & (~negative_relief)
            dyn_pos_pav = pos_pav & (
                (in_dyn_footprint & (h_road - local_floor_h > 0.03))
                | ((neighbor_obs_count == 0) & (h_road - local_floor_h > 0.08))
            )
            dyn_mask |= dyn_pos_pav

            # Negative-relief & flush pavement points (h in [-0.40 m, +0.02 m]): potholes are protected!
            # Only remove if inside a dynamic vehicle footprint AND protruding > 4 cm above a deeper pothole floor
            dyn_neg_pav = negative_relief & in_dyn_footprint & (h_road - local_floor_h > 0.04) & (neighbor_obs_count == 0)
            dyn_mask |= dyn_neg_pav

        static_pts = target.raw_points_local[~dyn_mask].copy()
        target.points_local = static_pts
        target.dynamic_mask = dyn_mask
        removed = int(dyn_mask.sum())
        stats = {
            "input_points": n_pts,
            "removed_dynamic_points": removed,
            "removal_ratio": round(removed / max(n_pts, 1), 4),
            "protected_road_points": int((negative_relief & (~dyn_mask)).sum()),
        }
        return static_pts, dyn_mask, stats

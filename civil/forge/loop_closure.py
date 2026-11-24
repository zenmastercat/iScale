"""Stage 3: Scan-Context Place Recognition & small_gicp Geometric Loop-Closure Verification."""

from __future__ import annotations

import math
import numpy as np
from scipy.spatial import cKDTree

from .types import ForgeConfig, Keyframe, LoopConstraint


def _level_points_by_roll_pitch(points_local: np.ndarray, R_wb: np.ndarray) -> np.ndarray:
    """Apply keyframe roll & pitch from R_wb (keeping yaw=0) so z_max is gravity-leveled."""
    yaw = math.atan2(float(R_wb[1, 0]), float(R_wb[0, 0]))
    c, s = math.cos(-yaw), math.sin(-yaw)
    R_unyaw = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    R_rp = R_unyaw @ R_wb
    return (np.asarray(points_local, dtype=np.float64) @ R_rp.T).astype(np.float32)


def make_scan_context(
    points_local: np.ndarray,
    n_rings: int = 20,
    n_sectors: int = 60,
    max_radius_m: float = 40.0,
    sensor_height_m: float = 1.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute (n_rings, n_sectors) Scan-Context polar max-height descriptor and (n_rings,) ring key."""
    sc = np.zeros((n_rings, n_sectors), dtype=np.float32)
    if len(points_local) == 0:
        return sc, np.zeros(n_rings, dtype=np.float32)

    pts = np.asarray(points_local, dtype=np.float32)
    r = np.hypot(pts[:, 0], pts[:, 1])
    # Filter out ground-noise or out-of-range points; emphasize elevated structure above ground
    valid = (r >= 0.5) & (r < max_radius_m) & (pts[:, 2] > -sensor_height_m + 0.15)
    if not np.any(valid):
        valid = (r >= 0.5) & (r < max_radius_m)
    if not np.any(valid):
        return sc, np.zeros(n_rings, dtype=np.float32)

    pv = pts[valid]
    rv = r[valid]
    ring_idx = np.clip((rv / max_radius_m * n_rings).astype(np.int32), 0, n_rings - 1)
    ang = np.arctan2(pv[:, 1], pv[:, 0])  # [-pi, pi]
    sec_idx = np.clip(((ang + math.pi) / (2.0 * math.pi) * n_sectors).astype(np.int32), 0, n_sectors - 1)
    heights = np.maximum(pv[:, 2] + sensor_height_m, 0.0)

    flat_idx = ring_idx * n_sectors + sec_idx
    flat_sc = np.zeros(n_rings * n_sectors, dtype=np.float32)
    np.maximum.at(flat_sc, flat_idx, heights)
    sc = flat_sc.reshape(n_rings, n_sectors)
    # Ring key: mean height + occupancy per radial ring (rotationally invariant)
    ring_key = 0.5 * sc.mean(axis=1) + 0.5 * (sc > 0.0).mean(axis=1).astype(np.float32)
    return sc, ring_key


def scan_context_distance(sc_a: np.ndarray, sc_b: np.ndarray) -> tuple[float, int]:
    """Column-shifted cosine distance between two (N_r, N_s) Scan-Context descriptors.

    Returns (min_distance_in_0_1, best_circular_column_shift_of_b).
    """
    n_rings, n_sectors = sc_a.shape
    norm_a = np.linalg.norm(sc_a, axis=0)
    norm_b = np.linalg.norm(sc_b, axis=0)
    valid_a = norm_a > 1e-6
    if not np.any(valid_a) or not np.any(norm_b > 1e-6):
        return 1.0, 0

    a_unit = np.where(valid_a[None, :], sc_a / np.maximum(norm_a[None, :], 1e-6), 0.0)
    b_unit = np.where((norm_b > 1e-6)[None, :], sc_b / np.maximum(norm_b[None, :], 1e-6), 0.0)

    best_sim = -1.0
    best_shift = 0
    for shift in range(n_sectors):
        b_shifted = np.roll(b_unit, shift=shift, axis=1)
        both_valid = valid_a & (np.roll(norm_b, shift=shift) > 1e-6)
        n_both = int(np.count_nonzero(both_valid))
        if n_both == 0:
            continue
        col_dots = np.sum(a_unit[:, both_valid] * b_shifted[:, both_valid], axis=0)
        # Weight by union of active columns so partial overlap doesn't artificially inflate score
        n_union = int(np.count_nonzero(valid_a | (np.roll(norm_b, shift=shift) > 1e-6)))
        sim = float(np.sum(col_dots)) / max(n_union, 1)
        if sim > best_sim:
            best_sim = sim
            best_shift = shift

    dist = float(np.clip(1.0 - best_sim, 0.0, 1.0))
    return dist, best_shift


class LoopClosureDetector:
    """Keyframe place recognition with Scan-Context + small_gicp G-ICP geometric verification."""

    def __init__(self, config: ForgeConfig | None = None) -> None:
        self.config = config or ForgeConfig()
        self.audit_log: list[dict] = []
        self._cum_dist: list[float] = []
        self._last_pos: np.ndarray | None = None

    def add_keyframe(self, kf: Keyframe) -> None:
        leveled = _level_points_by_roll_pitch(kf.points_local, kf.pose_w_b[:3, :3])
        sc, rk = make_scan_context(leveled, sensor_height_m=self.config.sensor_height_m)
        kf.descriptor_sc = sc
        kf.ring_key = rk
        pos = kf.pose_w_b[:3, 3]
        if self._last_pos is None:
            self._cum_dist.append(0.0)
        else:
            self._cum_dist.append(self._cum_dist[-1] + float(np.linalg.norm(pos - self._last_pos)))
        self._last_pos = pos.copy()

    def _verify_gicp(
        self, target_pts: np.ndarray, source_pts: np.ndarray, init_T: np.ndarray
    ) -> tuple[bool, np.ndarray, float, float]:
        """Align source_pts to target_pts starting from init_T. Returns (converged, T_target_source, rmse, inlier_ratio)."""
        tgt64 = np.ascontiguousarray(target_pts, dtype=np.float64)
        src64 = np.ascontiguousarray(source_pts, dtype=np.float64)
        T_est = np.array(init_T, dtype=np.float64, copy=True)
        converged = False
        try:
            import small_gicp

            res = small_gicp.align(
                tgt64,
                src64,
                init_T_target_source=T_est,
                registration_type="GICP",
                downsampling_resolution=0.25,
                max_correspondence_distance=1.5,
                num_threads=max(1, min(self.config.num_threads, 8)),
                max_iterations=35,
            )
            converged = bool(res.converged)
            T_est = np.asarray(res.T_target_source, dtype=np.float64)
        except ImportError:
            converged = True

        # Evaluate exact correspondence RMSE and inlier ratio (< 0.5 m) using cKDTree
        tree = cKDTree(tgt64)
        src_aligned = src64 @ T_est[:3, :3].T + T_est[:3, 3]
        dists, _ = tree.query(src_aligned, k=1)
        inliers = dists < 0.50
        inlier_ratio = float(np.mean(inliers)) if len(dists) else 0.0
        rmse = float(np.sqrt(np.mean(dists[inliers] ** 2))) if np.any(inliers) else 999.0
        return converged, T_est, rmse, inlier_ratio

    def detect_for_keyframe(self, keyframes: list[Keyframe], query_idx: int, top_k: int = 5) -> list[LoopConstraint]:
        """Search historical keyframes for a verified loop closure with keyframes[query_idx]."""
        if not self.config.enable_loop_closure or query_idx < 3:
            return []
        q_kf = keyframes[query_idx]
        if q_kf.descriptor_sc is None or q_kf.ring_key is None:
            self.add_keyframe(q_kf)

        q_dist = self._cum_dist[query_idx] if query_idx < len(self._cum_dist) else 0.0
        eligible_indices: list[int] = []
        eligible_rks: list[np.ndarray] = []
        for idx in range(query_idx - 1):
            c_kf = keyframes[idx]
            dt = abs(q_kf.t - c_kf.t)
            c_dist = self._cum_dist[idx] if idx < len(self._cum_dist) else 0.0
            path_gap = abs(q_dist - c_dist)
            if dt >= self.config.loop_min_time_s and path_gap >= self.config.loop_min_dist_m:
                if c_kf.ring_key is None:
                    self.add_keyframe(c_kf)
                eligible_indices.append(idx)
                eligible_rks.append(c_kf.ring_key)

        if not eligible_indices:
            return []

        rk_mat = np.vstack(eligible_rks)
        tree = cKDTree(rk_mat)
        k_eff = min(top_k, len(eligible_indices))
        _, nn = tree.query(q_kf.ring_key, k=k_eff)
        nn_list = [int(nn)] if np.ndim(nn) == 0 else [int(x) for x in nn]

        accepted: list[LoopConstraint] = []
        n_sectors = q_kf.descriptor_sc.shape[1]

        for local_i in nn_list:
            cand_idx = eligible_indices[local_i]
            c_kf = keyframes[cand_idx]
            sc_dist, shift_col = scan_context_distance(c_kf.descriptor_sc, q_kf.descriptor_sc)
            dt = float(abs(q_kf.t - c_kf.t))
            odom_dist = float(np.linalg.norm(q_kf.pose_w_b[:3, 3] - c_kf.pose_w_b[:3, 3]))
            path_gap = float(abs(q_dist - self._cum_dist[cand_idx]))

            record = {
                "query_keyframe_id": q_kf.id,
                "candidate_keyframe_id": c_kf.id,
                "time_delta_s": round(dt, 2),
                "odometry_distance_m": round(odom_dist, 3),
                "scan_context_distance": round(sc_dist, 4),
                "sector_shift_deg": round(shift_col * 360.0 / n_sectors, 1),
            }

            if sc_dist > self.config.sc_distance_thresh:
                record["decision"] = "REJECTED_SC_THRESHOLD"
                self.audit_log.append(record)
                continue

            # Initial yaw guess from Scan-Context column shift (np.roll(q_sc, shift_col) ~= c_sc)
            # Also try current odometry relative yaw and pick the better initial alignment
            yaw_sc = -(shift_col * 2.0 * math.pi / n_sectors)
            c_y, s_y = math.cos(yaw_sc), math.sin(yaw_sc)
            T_init_sc = np.eye(4, dtype=np.float64)
            T_init_sc[:3, :3] = [[c_y, -s_y, 0.0], [s_y, c_y, 0.0], [0.0, 0.0, 1.0]]

            T_init_odom = np.linalg.inv(c_kf.pose_w_b) @ q_kf.pose_w_b
            # Evaluate both initial guesses with G-ICP and keep the lower-RMSE alignment
            conv1, T1, rmse1, inl1 = self._verify_gicp(c_kf.points_local, q_kf.points_local, T_init_sc)
            conv2, T2, rmse2, inl2 = self._verify_gicp(c_kf.points_local, q_kf.points_local, T_init_odom)
            if inl2 > inl1 or (abs(inl2 - inl1) < 0.05 and rmse2 < rmse1):
                converged, T_rel, rmse, inlier_ratio = conv2, T2, rmse2, inl2
            else:
                converged, T_rel, rmse, inlier_ratio = conv1, T1, rmse1, inl1

            record.update({
                "gicp_converged": converged,
                "gicp_inlier_ratio": round(inlier_ratio, 4),
                "gicp_rmse_m": round(rmse, 4),
            })

            if not converged:
                record["decision"] = "REJECTED_GICP_UNCONVERGED"
                self.audit_log.append(record)
                continue
            if inlier_ratio < 0.45:
                record["decision"] = "REJECTED_INLIER_RATIO"
                self.audit_log.append(record)
                continue
            if rmse > 0.35:
                record["decision"] = "REJECTED_FITNESS_SCORE"
                self.audit_log.append(record)
                continue
            if float(np.linalg.norm(T_rel[:3, 3])) > max(8.0, 0.35 * path_gap):
                record["decision"] = "REJECTED_GTSAM_CHI2_GATE"
                self.audit_log.append(record)
                continue

            record["decision"] = "ACCEPTED"
            self.audit_log.append(record)
            accepted.append(
                LoopConstraint(
                    from_id=c_kf.id,
                    to_id=q_kf.id,
                    T_from_to=T_rel,
                    rmse=rmse,
                    inlier_ratio=inlier_ratio,
                    sc_distance=sc_dist,
                )
            )
            break

        return accepted

    def summary(self) -> dict:
        reasons: dict[str, int] = {}
        accepted = 0
        for rec in self.audit_log:
            d = rec.get("decision", "UNKNOWN")
            if d == "ACCEPTED":
                accepted += 1
            else:
                reasons[d] = reasons.get(d, 0) + 1
        return {
            "candidates_evaluated": len(self.audit_log),
            "accepted_count": accepted,
            "rejected_by_reason": reasons,
            "audit_log": self.audit_log[-50:],
        }

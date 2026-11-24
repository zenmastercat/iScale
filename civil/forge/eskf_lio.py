"""Stage 1: 15-DOF Error-State Kalman Filter LiDAR-Inertial Odometry (ESKF LIO) Front End."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from ..pointcloud import voxel_downsample
from .types import ForgeConfig, LidarScan, SensorCalibration

GRAVITY_W = np.array([0.0, 0.0, -9.80665], dtype=np.float64)
IMU_MAX_GAP_S = 0.5          # longer IMU gaps are not integrated; uncertainty is inflated instead
DEGENERATE_EIG_RATIO = 0.02  # a direction whose LiDAR information is < 2 % of the strongest one is unobservable


def skew(v: np.ndarray) -> np.ndarray:
    """3-vector -> 3x3 skew-symmetric matrix [v]_x."""
    return np.array(
        [[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]],
        dtype=np.float64,
    )


def so3_exp(omega: np.ndarray) -> np.ndarray:
    """Rodrigues exponential map exp([omega]_x) -> 3x3 rotation matrix."""
    theta = float(np.linalg.norm(omega))
    if theta < 1e-12:
        return np.eye(3, dtype=np.float64) + skew(omega)
    axis = omega / theta
    K = skew(axis)
    return np.eye(3, dtype=np.float64) + np.sin(theta) * K + (1.0 - np.cos(theta)) * (K @ K)


def so3_log(R: np.ndarray) -> np.ndarray:
    """Logarithmic map log(R)^vee -> 3-vector rotation axis-angle."""
    tr = float(np.clip((np.trace(R) - 1.0) * 0.5, -1.0, 1.0))
    theta = float(np.arccos(tr))
    if theta < 1e-8:
        return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]], dtype=np.float64) * 0.5
    return (theta / (2.0 * np.sin(theta))) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]], dtype=np.float64
    )


class ESKFLIO:
    """15-DOF Error-State Kalman Filter fusing IMU strapdown integration and point-to-plane LiDAR updates.

    Error state ordering: [dtheta (0:3), dp (3:6), dv (6:9), dbg (9:12), dba (12:15)].
    """

    def __init__(self, calib: SensorCalibration | None = None, config: ForgeConfig | None = None) -> None:
        self.calib = calib or SensorCalibration()
        self.config = config or ForgeConfig()

        # Nominal state
        self.R = np.eye(3, dtype=np.float64)
        self.p = np.zeros(3, dtype=np.float64)
        self.v = np.zeros(3, dtype=np.float64)
        self.bg = np.zeros(3, dtype=np.float64)
        self.ba = np.zeros(3, dtype=np.float64)
        self.t_last: float | None = None

        # 15x15 error-state covariance P
        self.P = np.diag(
            [1e-4, 1e-4, 1e-4, 1e-3, 1e-3, 1e-3, 1e-2, 1e-2, 1e-2, 1e-4, 1e-4, 1e-4, 1e-3, 1e-3, 1e-3]
        ).astype(np.float64)

        # History buffer of (t, T_wb) for motion deskewing
        self._pose_history: list[tuple[float, np.ndarray]] = [(0.0, np.eye(4, dtype=np.float64))]

        # Active local map points & precomputed normals in world frame
        self._map_points: np.ndarray | None = None
        self._map_normals: np.ndarray | None = None
        self._map_tree: cKDTree | None = None
        self._scan_count = 0
        self.imu_out_of_order = 0
        self.imu_gaps = 0

    def initialize_static(self, gyros: np.ndarray, accels: np.ndarray) -> bool:
        """Level the filter on gravity and take the gyro bias from a stationary IMU window.

        Returns False (and changes nothing) when the window does not look stationary.
        """
        g = np.asarray(gyros, dtype=np.float64)
        a = np.asarray(accels, dtype=np.float64)
        if len(a) < 10 or len(g) != len(a):
            return False
        if float(np.linalg.norm(g.mean(axis=0))) > 0.05 or float(np.max(a.std(axis=0))) > 0.3:
            return False
        f = a.mean(axis=0)
        z = f / np.linalg.norm(f)
        axis = np.cross(z, [0.0, 0.0, 1.0])
        s_ang = float(np.linalg.norm(axis))
        ang = float(np.arctan2(s_ang, z[2]))
        self.R = so3_exp(axis / s_ang * ang) if s_ang > 1e-9 else np.eye(3)
        self.bg = g.mean(axis=0)
        self.P[0:3, 0:3] = np.eye(3) * 1e-6
        self._pose_history = [(self._pose_history[-1][0], self.state_pose())]
        return True

    def state_pose(self) -> np.ndarray:
        """Current 4x4 body-to-world pose T_wb."""
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = self.R
        T[:3, 3] = self.p
        return T

    def predict_imu(self, t: float, gyro: np.ndarray, accel: np.ndarray) -> None:
        """Propagate 15-DOF nominal state and error covariance across one IMU measurement."""
        t_corr = float(t) + self.calib.time_offset_imu_s
        if self.t_last is None:
            self.t_last = t_corr
            self._pose_history = [(t_corr, self.state_pose())]
            return
        dt = t_corr - self.t_last
        if dt <= 0.0:
            self.imu_out_of_order += 1
            return
        if dt > IMU_MAX_GAP_S:
            # Unknown motion during the gap: do not integrate, widen velocity/position uncertainty instead
            self.imu_gaps += 1
            self.P[6:9, 6:9] += np.eye(3) * (2.0 * dt) ** 2
            self.P[3:6, 3:6] += np.eye(3) * (1.0 * dt) ** 2
            self.t_last = t_corr
            self._pose_history.append((t_corr, self.state_pose()))
            return

        w = np.asarray(gyro, dtype=np.float64) - self.bg
        f = np.asarray(accel, dtype=np.float64) - self.ba

        dR = so3_exp(w * dt)
        a_w = self.R @ f + GRAVITY_W

        self.p = self.p + self.v * dt + 0.5 * a_w * (dt * dt)
        self.v = self.v + a_w * dt
        R_prev = self.R
        self.R = self.R @ dR
        self.t_last = t_corr

        # Error-state transition matrix F
        F = np.eye(15, dtype=np.float64)
        F[0:3, 0:3] = dR.T
        F[0:3, 9:12] = -np.eye(3) * dt
        F[3:6, 6:9] = np.eye(3) * dt
        F[6:9, 0:3] = -R_prev @ skew(f) * dt
        F[6:9, 12:15] = -R_prev * dt

        Q = np.zeros((15, 15), dtype=np.float64)
        Q[0:3, 0:3] = np.eye(3) * (self.calib.gyr_noise ** 2) * dt
        Q[3:6, 3:6] = np.eye(3) * 1e-5 * dt
        Q[6:9, 6:9] = np.eye(3) * (self.calib.acc_noise ** 2) * dt
        Q[9:12, 9:12] = np.eye(3) * (self.calib.gyr_bias_walk ** 2) * dt
        Q[12:15, 12:15] = np.eye(3) * (self.calib.acc_bias_walk ** 2) * dt

        self.P = F @ self.P @ F.T + Q
        self.P = 0.5 * (self.P + self.P.T)

        self._pose_history.append((t_corr, self.state_pose()))
        if len(self._pose_history) > 2000:
            self._pose_history = self._pose_history[-1000:]

    def _push_history(self, t: float) -> None:
        while self._pose_history and self._pose_history[-1][0] >= t:
            self._pose_history.pop()
        self._pose_history.append((t, self.state_pose()))

    def interpolate_pose(self, t: float) -> np.ndarray:
        """SE(3) geodesic interpolation of T_wb(t) from the IMU history buffer."""
        if not self._pose_history:
            return self.state_pose()
        times = [item[0] for item in self._pose_history]
        if t <= times[0]:
            return self._pose_history[0][1].copy()
        if t >= times[-1]:
            return self._pose_history[-1][1].copy()
        idx = int(np.searchsorted(times, t, side="right") - 1)
        t0, T0 = self._pose_history[idx]
        t1, T1 = self._pose_history[idx + 1]
        alpha = (t - t0) / max(t1 - t0, 1e-9)
        dR = so3_exp(alpha * so3_log(T0[:3, :3].T @ T1[:3, :3]))
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = T0[:3, :3] @ dR
        T[:3, 3] = (1.0 - alpha) * T0[:3, 3] + alpha * T1[:3, 3]
        return T

    def deskew_scan(self, scan: LidarScan) -> np.ndarray:
        """Deskew LiDAR points measured across [t_start, t_end] into the scan-end body frame."""
        pts_l = np.asarray(scan.points, dtype=np.float64)
        R_bl = self.calib.T_lidar_imu[:3, :3]
        t_bl = self.calib.T_lidar_imu[:3, 3]
        pts_b = pts_l @ R_bl.T + t_bl
        if scan.point_times is None or len(scan.point_times) != len(pts_b) or len(self._pose_history) < 2:
            return pts_b.astype(np.float32)

        t_end = float(scan.t)
        T_end = self.interpolate_pose(t_end)
        T_end_inv = np.linalg.inv(T_end)

        # Batch deskewing across 16 time bins for vectorization speed while preserving accuracy
        pt_t = np.asarray(scan.point_times, dtype=np.float64)
        t_min, t_max = float(pt_t.min()), float(pt_t.max())
        if t_max - t_min < 1e-6:
            return pts_b.astype(np.float32)

        n_bins = min(32, len(pts_b))
        edges = np.linspace(t_min, t_max, n_bins + 1)
        bin_ids = np.clip(np.digitize(pt_t, edges) - 1, 0, n_bins - 1)
        out = np.empty_like(pts_b)
        for b in range(n_bins):
            mask = bin_ids == b
            if not np.any(mask):
                continue
            t_mid = float(pt_t[mask].mean())
            T_rel = T_end_inv @ self.interpolate_pose(t_mid)
            out[mask] = pts_b[mask] @ T_rel[:3, :3].T + T_rel[:3, 3]
        return out.astype(np.float32)

    @staticmethod
    def _estimate_normals(pts: np.ndarray, k: int = 12) -> tuple[np.ndarray, cKDTree]:
        """Vectorized local PCA plane normal estimation for point-to-plane ESKF measurement updates."""
        tree = cKDTree(pts)
        k_eff = min(k, len(pts))
        if k_eff < 3:
            return np.tile(np.array([0.0, 0.0, 1.0]), (len(pts), 1)), tree
        _, idx = tree.query(pts, k=k_eff)
        neigh = pts[idx]  # (N, k, 3)
        centered = neigh - neigh.mean(axis=1, keepdims=True)
        cov = np.einsum("nki,nkj->nij", centered, centered) / max(k_eff - 1, 1)
        _, _, vh = np.linalg.svd(cov)
        normals = vh[:, -1, :]
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        normals = np.where(norms > 1e-9, normals / np.maximum(norms, 1e-9), np.array([0.0, 0.0, 1.0]))
        return normals, tree

    def _update_local_map(self, pts_w: np.ndarray) -> None:
        if self._map_points is None:
            combined = pts_w
        else:
            combined = np.vstack([self._map_points, pts_w])
            # Keep points within 60 m of current position
            keep = np.linalg.norm(combined - self.p, axis=1) <= 60.0
            if np.count_nonzero(keep) >= 100:
                combined = combined[keep]
        idx = voxel_downsample(combined.astype(np.float32), self.config.voxel_size_m, max_points=30_000)
        self._map_points = combined[idx].astype(np.float64)
        self._map_normals, self._map_tree = self._estimate_normals(self._map_points)

    def update_lidar(self, scan: LidarScan) -> tuple[np.ndarray, np.ndarray, dict]:
        """Deskew scan, perform iterated ESKF point-to-plane measurement update, and return pose + telemetry."""
        if self.t_last is None:
            self.t_last = float(scan.t)
        pts_b = self.deskew_scan(scan)
        sub_idx = voxel_downsample(pts_b, max(self.config.voxel_size_m, 0.12), max_points=2500)
        pts_sub = pts_b[sub_idx].astype(np.float64)

        self._scan_count += 1
        if self._map_points is None or len(self._map_points) < 30 or len(pts_sub) < 10:
            pts_w0 = pts_sub @ self.R.T + self.p
            self._update_local_map(pts_w0)
            self._push_history(float(scan.t))
            tel = self._build_telemetry(0.0, 6)
            return self.state_pose(), pts_b, tel

        # Optional initial refinement via small_gicp if displacement is large, followed by IEKF update
        R_prior = self.R.copy()
        p_prior = self.p.copy()
        v_prior = self.v.copy()
        bg_prior = self.bg.copy()
        ba_prior = self.ba.copy()
        P_prior = self.P.copy()
        P_inv = np.linalg.pinv(P_prior + np.eye(15) * 1e-9)

        sigma_meas = 0.04  # 4 cm LiDAR point-to-plane noise standard deviation
        r_inv_var = 1.0 / (sigma_meas ** 2)
        rms_resid = 0.0
        observable_dofs = 6
        degenerate_axes: list[str] = []
        HTRinvH = np.zeros((15, 15), dtype=np.float64)

        for _ in range(5):
            pts_w = pts_sub @ self.R.T + self.p
            dists, nn_idx = self._map_tree.query(pts_w, k=1)
            valid = dists < 1.2
            if np.count_nonzero(valid) < 15:
                break
            pw_v = pts_w[valid]
            pb_v = pts_sub[valid]
            qw_v = self._map_points[nn_idx[valid]]
            nw_v = self._map_normals[nn_idx[valid]]

            # Point-to-plane residual: r_i = n_i^T (R p_i^b + p - q_i); innovation z_i = -r_i
            res = np.sum(nw_v * (pw_v - qw_v), axis=1)
            # Huber robust weight
            huber_k = 0.15
            abs_r = np.abs(res)
            weights = np.where(abs_r <= huber_k, 1.0, huber_k / np.maximum(abs_r, 1e-9)) * r_inv_var
            rms_resid = float(np.sqrt(np.mean(res ** 2)))

            # Jacobian H_i with respect to [dtheta, dp]:
            # d(R exp([dtheta]_x) p_b)/d(dtheta) = -R [p_b]_x -> d(n^T R p_b)/d(dtheta) = (R^T n x p_b)^T = (p_b x (R^T n))^T
            n_body = nw_v @ self.R
            H_rot = np.cross(pb_v, n_body)  # (M, 3)
            H_pos = nw_v                    # (M, 3)
            H6 = np.hstack([H_rot, H_pos])  # (M, 6)

            w_H6 = H6 * weights[:, None]
            H6T_W_H6 = H6.T @ w_H6
            # Degeneracy per block (rotation, translation): weak eigen-directions carry no LiDAR information
            observable_dofs = 0
            degenerate_axes = []
            for blk in (slice(0, 3), slice(3, 6)):
                ev, evec = np.linalg.eigh(H6T_W_H6[blk, blk])
                weak = ev < DEGENERATE_EIG_RATIO * max(float(ev[-1]), 1e-12)
                observable_dofs += int(np.count_nonzero(~weak))
                if blk.start == 3:
                    for j in np.flatnonzero(weak):
                        degenerate_axes.append("xyz"[int(np.argmax(np.abs(self.R @ evec[:, j])))])

            HTRinvH.fill(0.0)
            HTRinvH[:6, :6] = H6T_W_H6
            HTRinvz = np.zeros(15, dtype=np.float64)
            HTRinvz[:6] = -H6.T @ (weights * res)

            # Prior displacement from (R_prior, p_prior, v_prior, bg_prior, ba_prior)
            dx_prior = np.zeros(15, dtype=np.float64)
            dx_prior[0:3] = so3_log(R_prior.T @ self.R)
            dx_prior[3:6] = self.p - p_prior
            dx_prior[6:9] = self.v - v_prior
            dx_prior[9:12] = self.bg - bg_prior
            dx_prior[12:15] = self.ba - ba_prior

            info_mat = P_inv + HTRinvH
            rhs = HTRinvz - P_inv @ dx_prior
            dx = np.linalg.solve(info_mat + np.eye(15) * 1e-8, rhs)

            self.R = self.R @ so3_exp(dx[0:3])
            self.p = self.p + dx[3:6]
            self.v = self.v + dx[6:9]
            self.bg = self.bg + dx[9:12]
            self.ba = self.ba + dx[12:15]

            if float(np.linalg.norm(dx[:6])) < 1e-4:
                break

        # Joseph-form style stabilized posterior covariance in 15D information form
        info_post = P_inv + HTRinvH
        P_post = np.linalg.inv(info_post + np.eye(15) * 1e-9)
        self.P = 0.5 * (P_post + P_post.T)
        # Ensure positive-definiteness floor
        eigvals, eigvecs = np.linalg.eigh(self.P)
        if np.any(eigvals < 1e-9):
            eigvals = np.maximum(eigvals, 1e-9)
            self.P = eigvecs @ np.diag(eigvals) @ eigvecs.T
            self.P = 0.5 * (self.P + self.P.T)

        pts_w_final = pts_sub @ self.R.T + self.p
        self._update_local_map(pts_w_final)
        self._push_history(float(scan.t))
        tel = self._build_telemetry(rms_resid, observable_dofs, degenerate_axes)
        return self.state_pose(), pts_b, tel

    def _build_telemetry(self, rms_resid: float, observable_dofs: int, degenerate_axes: list[str] | None = None) -> dict:
        eigvals = np.linalg.eigvalsh(self.P)
        max_eig = float(np.max(eigvals))
        min_eig = float(max(np.min(eigvals), 1e-12))
        pos_max_eig = float(np.max(np.linalg.eigvalsh(self.P[3:6, 3:6])))
        diverged = bool(not np.isfinite(max_eig) or pos_max_eig > 25.0)
        if diverged:
            # Clamp covariance to bounded prior and damp velocity
            self.P = np.diag([1e-3] * 3 + [1.0] * 3 + [0.5] * 3 + [1e-4] * 3 + [1e-3] * 3)
            self.v *= 0.5
        return {
            "cov_trace_pos": float(np.trace(self.P[3:6, 3:6])),
            "cov_trace_rot": float(np.trace(self.P[0:3, 0:3])),
            "cov_trace_vel": float(np.trace(self.P[6:9, 6:9])),
            "cov_max_eigenvalue": max_eig,
            "cov_condition_number": max_eig / min_eig,
            "observable_dofs": observable_dofs,
            "degenerate": observable_dofs < 6,
            "degenerate_translation_axes": sorted(set(degenerate_axes or [])),
            "imu_out_of_order": self.imu_out_of_order,
            "imu_gaps": self.imu_gaps,
            "lidar_icp_residual_rms": rms_resid,
            "bias_gyro_norm": float(np.linalg.norm(self.bg)),
            "bias_accel_norm": float(np.linalg.norm(self.ba)),
            "divergence_detected": diverged,
        }

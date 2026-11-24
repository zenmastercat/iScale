"""Stage 4: GTSAM iSAM2 & NonlinearFactorGraph Pose-Graph Optimization."""

from __future__ import annotations

import numpy as np

from .types import LoopConstraint


class PoseGraphOptimizer:
    """Factor-graph pose optimizer over keyframe SE(3) poses using GTSAM (BSD license)."""

    def __init__(self) -> None:
        import gtsam

        self._gtsam = gtsam
        params = gtsam.ISAM2Params()
        params.setRelinearizeThreshold(0.05)
        params.relinearizeSkip = 1
        self._isam = gtsam.ISAM2(params)
        self._full_graph = gtsam.NonlinearFactorGraph()
        self._initial_values = gtsam.Values()
        self._current_poses: dict[int, np.ndarray] = {}
        self._num_factors = 0
        self._loop_count = 0

    def _to_pose3(self, T: np.ndarray):
        return self._gtsam.Pose3(np.asarray(T, dtype=np.float64))

    def add_keyframe(self, kf_id: int, pose_w_b: np.ndarray, is_first: bool = False) -> None:
        gtsam = self._gtsam
        p3 = self._to_pose3(pose_w_b)
        self._current_poses[kf_id] = np.array(pose_w_b, dtype=np.float64, copy=True)
        if not self._initial_values.exists(kf_id):
            self._initial_values.insert(kf_id, p3)
        else:
            self._initial_values.update(kf_id, p3)

        new_graph = gtsam.NonlinearFactorGraph()
        new_vals = gtsam.Values()
        new_vals.insert(kf_id, p3)

        if is_first or kf_id == 0:
            prior_noise = gtsam.noiseModel.Diagonal.Sigmas(np.array([1e-4, 1e-4, 1e-4, 1e-4, 1e-4, 1e-4]))
            factor = gtsam.PriorFactorPose3(kf_id, p3, prior_noise)
            new_graph.add(factor)
            self._full_graph.add(factor)
            self._num_factors += 1

        self._isam.update(new_graph, new_vals)

    def add_odometry_factor(
        self, from_id: int, to_id: int, T_rel: np.ndarray, sigmas: np.ndarray | None = None
    ) -> None:
        gtsam = self._gtsam
        if sigmas is None:
            sigmas = np.array([0.02, 0.02, 0.02, 0.05, 0.05, 0.05], dtype=np.float64)
        noise = gtsam.noiseModel.Diagonal.Sigmas(np.asarray(sigmas, dtype=np.float64))
        rel_p3 = self._to_pose3(T_rel)
        factor = gtsam.BetweenFactorPose3(from_id, to_id, rel_p3, noise)

        new_graph = gtsam.NonlinearFactorGraph()
        new_graph.add(factor)
        self._full_graph.add(factor)
        self._num_factors += 1
        self._isam.update(new_graph, gtsam.Values())

    def add_loop_factor(self, constraint: LoopConstraint) -> bool:
        if constraint.from_id not in self._current_poses or constraint.to_id not in self._current_poses:
            return False
        gtsam = self._gtsam
        s_pos = max(0.02, min(constraint.rmse, 0.25))
        base_noise = gtsam.noiseModel.Diagonal.Sigmas(
            np.array([0.015, 0.015, 0.015, s_pos, s_pos, s_pos], dtype=np.float64)
        )
        cauchy = gtsam.noiseModel.mEstimator.Cauchy.Create(1.0)
        robust_noise = gtsam.noiseModel.Robust.Create(cauchy, base_noise)
        rel_p3 = self._to_pose3(constraint.T_from_to)
        factor = gtsam.BetweenFactorPose3(constraint.from_id, constraint.to_id, rel_p3, robust_noise)

        new_graph = gtsam.NonlinearFactorGraph()
        new_graph.add(factor)
        self._full_graph.add(factor)
        self._num_factors += 1
        self._loop_count += 1
        self._isam.update(new_graph, gtsam.Values())
        return True

    def add_gps_prior(self, kf_id: int, xyz_enu: np.ndarray, sigma_m: float = 0.25) -> None:
        if kf_id not in self._current_poses:
            return
        gtsam = self._gtsam
        T_prior = self._current_poses[kf_id].copy()
        T_prior[:3, 3] = np.asarray(xyz_enu, dtype=np.float64)
        # Weak orientation prior, strong translation prior
        noise = gtsam.noiseModel.Diagonal.Sigmas(
            np.array([10.0, 10.0, 10.0, sigma_m, sigma_m, sigma_m * 1.5], dtype=np.float64)
        )
        factor = gtsam.PriorFactorPose3(kf_id, self._to_pose3(T_prior), noise)
        new_graph = gtsam.NonlinearFactorGraph()
        new_graph.add(factor)
        self._full_graph.add(factor)
        self._num_factors += 1
        self._isam.update(new_graph, gtsam.Values())

    def optimize(self) -> tuple[dict[int, np.ndarray], dict]:
        """Run iSAM2 + Levenberg-Marquardt polish and return {kf_id: T_w_b_4x4} and telemetry."""
        gtsam = self._gtsam
        err_before = float(self._full_graph.error(self._initial_values))
        # Extra iSAM2 relinearization step + batch LM polish for global consistency on closed loops
        self._isam.update()
        est = self._isam.calculateEstimate()
        try:
            lm_params = gtsam.LevenbergMarquardtParams()
            lm_params.setMaxIterations(30)
            lm = gtsam.LevenbergMarquardtOptimizer(self._full_graph, est, lm_params)
            est_lm = lm.optimize()
            if self._full_graph.error(est_lm) <= self._full_graph.error(est):
                est = est_lm
        except Exception:
            pass

        err_after = float(self._full_graph.error(est))
        for kf_id in list(self._current_poses.keys()):
            if est.exists(kf_id):
                p3 = est.atPose3(kf_id)
                self._current_poses[kf_id] = np.asarray(p3.matrix(), dtype=np.float64)

        red_pct = round((err_before - err_after) / max(err_before, 1e-9) * 100.0, 2) if err_before > 0 else 0.0
        telemetry = {
            "initial_error": round(err_before, 4),
            "final_error": round(err_after, 4),
            "error_reduction_pct": red_pct,
            "num_poses": len(self._current_poses),
            "num_factors": self._num_factors,
            "loop_factors": self._loop_count,
        }
        return dict(self._current_poses), telemetry

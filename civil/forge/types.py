"""Pure-NumPy data contracts and configuration dataclasses for FORGE SLAM."""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from ..pointcloud import Reconstruction


@dataclass
class ImuSample:
    t: float
    gyro: np.ndarray   # (3,) rad/s in IMU body frame
    accel: np.ndarray  # (3,) m/s^2 specific force in IMU body frame


@dataclass
class LidarScan:
    t: float
    points: np.ndarray                        # (N, 3) float32 in LiDAR frame
    intensities: np.ndarray | None = None     # (N,) float32
    point_times: np.ndarray | None = None     # (N,) float64 absolute timestamps in seconds


@dataclass
class CameraFrame:
    t: float
    image: np.ndarray                         # (H, W, 3) uint8 RGB or (H, W) uint16/float32 thermal
    intrinsics: np.ndarray                    # (3, 3) float64 K matrix
    distortion: np.ndarray                    # (4,) or (5,) float64 distortion coeffs
    T_lidar_cam: np.ndarray                   # (4, 4) float64 transform from camera to LiDAR (or LiDAR to cam)
    modality: str = "rgb"                     # "rgb" or "thermal"
    thermal_encoding: str = "celsius_f32"     # "flir_raw", "centikelvin", "celsius_f32", "linear_u8"
    planck_params: dict | None = None
    linear_range: tuple[float, float] | None = None


@dataclass
class SensorCalibration:
    T_lidar_imu: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64))
    T_lidar_rgb: np.ndarray | None = None
    T_lidar_thermal: np.ndarray | None = None
    K_rgb: np.ndarray | None = None
    D_rgb: np.ndarray | None = None
    K_thermal: np.ndarray | None = None
    D_thermal: np.ndarray | None = None
    time_offset_imu_s: float = 0.0
    time_offset_rgb_s: float = 0.0
    time_offset_thermal_s: float = 0.0
    thermal_encoding: str = "flir_raw"
    planck_params: dict = field(
        default_factory=lambda: {"R": 380747.0, "B": 1428.0, "F": 1.0, "O": -88.539}
    )
    linear_range: tuple[float, float] | None = None
    gyr_noise: float = 2.4e-3
    acc_noise: float = 2.5e-2
    gyr_bias_walk: float = 2.0e-5
    acc_bias_walk: float = 8.0e-4


@dataclass
class Keyframe:
    id: int
    t: float
    pose_w_b: np.ndarray                      # (4, 4) float64 body-to-world SE(3)
    points_local: np.ndarray                  # (M, 3) float32 static points in body frame
    raw_points_local: np.ndarray              # (N, 3) float32 pre-filter points in body frame
    dynamic_mask: np.ndarray                  # (N,) bool audit mask (True = removed dynamic point)
    colors: np.ndarray | None = None          # (M, 3) uint8
    temperatures_c: np.ndarray | None = None  # (M,) float32 degrees Celsius
    descriptor_sc: np.ndarray | None = None   # (N_r, N_s) float32 Scan-Context
    ring_key: np.ndarray | None = None        # (N_r,) float32 ring key


@dataclass
class LoopConstraint:
    from_id: int
    to_id: int
    T_from_to: np.ndarray  # (4, 4) float64 relative pose T_{from}^{-1} T_{to}
    rmse: float
    inlier_ratio: float
    sc_distance: float


@dataclass
class ForgeConfig:
    keyframe_dist_m: float = 1.0
    keyframe_angle_deg: float = 10.0
    voxel_size_m: float = 0.10
    max_ram_bytes: int = 512 * 1024 * 1024
    tile_size_m: float = 20.0
    enable_dynamic_filter: bool = True
    enable_loop_closure: bool = True
    enable_thermal: bool = True
    enable_gsplat: bool = True
    min_free_gpu_gb: float = 4.0
    max_gaussians: int = 250_000
    num_threads: int = 8
    sc_distance_thresh: float = 0.35
    loop_min_time_s: float = 25.0
    loop_min_dist_m: float = 15.0
    sensor_height_m: float = 1.5
    lidar_origin_b: tuple[float, float, float] = (0.0, 0.0, 0.0)  # LiDAR centre in the body (keyframe) frame
    lidar_vfov_deg: tuple[float, float] = (-25.0, 25.0)            # vertical field of view for free-space checks
    loop_max_offset_m: float = 10.0                                # a verified loop must overlap: |t_rel| below this
    camera_min_interval_s: float = 0.0                             # keep at most one camera frame per interval
    gsplat_iters: int = 12


@dataclass
class ForgeResult:
    reconstruction: Reconstruction
    keyframes: list[Keyframe]
    loop_constraints: list[LoopConstraint]
    dynamic_mask: np.ndarray
    diagnostics: dict

    def to_reconstruction(self) -> Reconstruction:
        return self.reconstruction


# Knobs a survey upload may set (params.forge) and their allowed ranges. Anything else is refused: the pipeline
# runs on the server's single survey worker, so an extreme value would stall or exhaust it for everyone.
FORGE_PARAM_LIMITS: dict[str, tuple[type, float, float]] = {
    "keyframe_dist_m": (float, 0.2, 10.0),
    "keyframe_angle_deg": (float, 1.0, 90.0),
    "voxel_size_m": (float, 0.02, 1.0),
    "max_ram_bytes": (int, 16 * 1024 * 1024, 2 * 1024 * 1024 * 1024),
    "tile_size_m": (float, 5.0, 200.0),
    "min_free_gpu_gb": (float, 1.0, 16.0),
    "max_gaussians": (int, 1_000, 500_000),
    "num_threads": (int, 1, 8),
    "sc_distance_thresh": (float, 0.05, 1.0),
    "loop_min_time_s": (float, 1.0, 3600.0),
    "loop_min_dist_m": (float, 1.0, 1000.0),
    "sensor_height_m": (float, 0.2, 5.0),
    "enable_dynamic_filter": (bool, 0, 1),
    "enable_loop_closure": (bool, 0, 1),
    "enable_thermal": (bool, 0, 1),
    "enable_gsplat": (bool, 0, 1),
}


def validate_forge_params(params: dict) -> dict:
    """Checked ForgeConfig keyword arguments from user params; ValueError names the first bad knob."""
    import math

    out = {}
    for k, v in params.items():
        if k not in FORGE_PARAM_LIMITS:
            raise ValueError(f"unknown forge parameter {k!r}")
        kind, lo, hi = FORGE_PARAM_LIMITS[k]
        if kind is bool:
            if not isinstance(v, bool):
                raise ValueError(f"forge parameter {k} must be true or false")
            out[k] = v
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"forge parameter {k} must be a finite number")
        if kind is int and v != int(v):
            raise ValueError(f"forge parameter {k} must be a whole number")
        if not lo <= v <= hi:
            raise ValueError(f"forge parameter {k} must be between {lo:g} and {hi:g}")
        out[k] = kind(v)
    return out

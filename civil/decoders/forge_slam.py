"""FORGE SLAM decoder for iScale: multi-sensor LiDAR-Inertial-Visual-Thermal SLAM."""

from __future__ import annotations

from pathlib import Path

from ..pointcloud import Reconstruction
from .base import Decoder, DecoderError


class ForgeSlamDecoder(Decoder):
    name = "forge_slam"
    label = "FORGE SLAM (LiDAR + IMU + RGB + Radiometric Thermal °C)"
    description = (
        "Tightly coupled 15-DOF ESKF LiDAR-inertial odometry, ground-protected dynamic object removal, "
        "Scan-Context + G-ICP loop closure, GTSAM iSAM2 pose graph, bounded-RAM tile hot-swap, "
        "radiometric LWIR thermal (°C) registration, and keyframe-anchored 3D Gaussian Splatting."
    )
    accepts = ("lidar", "imu", "rgb", "thermal", "calibration", "gps")

    def available(self) -> tuple[bool, str]:
        try:
            import gtsam  # noqa: F401
            import small_gicp  # noqa: F401
        except ImportError as e:
            return False, f"FORGE SLAM dependency missing: {e}"
        return True, ""

    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        from ..forge.io import preflight_check
        from ..forge.pipeline import run_forge_slam
        from ..forge.types import ForgeConfig, validate_forge_params

        ok, why = self.available()
        if not ok:
            raise DecoderError(why)
        pf = preflight_check(input_dir)
        if not pf["ok"]:
            raise DecoderError("FORGE SLAM input preflight failed: " + "; ".join(pf["issues"]))

        try:
            cfg = ForgeConfig(**validate_forge_params(dict((params or {}).get("forge") or {})))
        except ValueError as e:
            raise DecoderError(f"FORGE SLAM parameters: {e}") from None
        res = run_forge_slam(input_dir, work_dir, config=cfg)
        return res.to_reconstruction()

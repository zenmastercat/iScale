"""FORGE SLAM: Multi-Modal LiDAR-Inertial-Visual-Thermal SLAM for iScale."""

from __future__ import annotations

from .io import create_synthetic_forge_dataset, load_forge_sequence, preflight_check
from .pipeline import run_forge_slam
from .types import (
    CameraFrame,
    ForgeConfig,
    ForgeResult,
    ImuSample,
    Keyframe,
    LidarScan,
    LoopConstraint,
    SensorCalibration,
)

__all__ = [
    "CameraFrame",
    "ForgeConfig",
    "ForgeResult",
    "ImuSample",
    "Keyframe",
    "LidarScan",
    "LoopConstraint",
    "SensorCalibration",
    "create_synthetic_forge_dataset",
    "load_forge_sequence",
    "preflight_check",
    "run_forge_slam",
]

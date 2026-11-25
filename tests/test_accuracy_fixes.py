"""TDD regression tests for 3D pothole measurement accuracy improvements."""

from __future__ import annotations

import math

import numpy as np

from civil.align import align
from civil.analysis import analyze
from civil.pointcloud import Reconstruction


def test_align_levels_ground_when_camera_pitched_40_deg_down_or_walls_dominate():
    """A handheld/dashcam pitched 40 deg down at the road (or driving between tall walls)
    must still align Z to the true road plane below the cameras, not to tilted camera-up."""
    rng = np.random.default_rng(42)
    # Level road at z = 0, plus tall side walls with MORE points than the road
    road = np.c_[rng.uniform(0, 15, 8000), rng.uniform(-3, 3, 8000), rng.normal(0, 0.004, 8000)]
    wall_l = np.c_[rng.uniform(0, 15, 12000), np.full(12000, 3.5), rng.uniform(0, 4.0, 12000)]
    wall_r = np.c_[rng.uniform(0, 15, 12000), np.full(12000, -3.5), rng.uniform(0, 4.0, 12000)]
    pts = np.vstack([road, wall_l, wall_r])

    # OpenCV camera looking +X, pitched 40 deg downward toward road
    R_base = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    p = math.radians(40.0)
    R_pitch = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(p), -math.sin(p)], [0.0, math.sin(p), math.cos(p)]])
    R_wc = R_base @ R_pitch
    poses = np.repeat(np.eye(4)[None], 20, axis=0)
    poses[:, :3, :3] = R_wc
    poses[:, :3, 3] = np.c_[np.linspace(1.0, 14.0, 20), np.zeros(20), np.full(20, 1.2)]

    # Apply an arbitrary 3D rotation to simulate LingBot's unaligned output frame
    rot = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])
    pts_rot = pts @ rot.T
    poses_rot = poses.copy()
    poses_rot[:, :3, :3] = rot @ poses[:, :3, :3]
    poses_rot[:, :3, 3] = poses[:, :3, 3] @ rot.T

    rec = Reconstruction(
        points=pts_rot.astype(np.float32), poses=poses_rot,
        meta={"metric": True, "up_axis": "auto", "camera_convention": "opencv"},
    )
    align(rec, 13.8, 100.5, {})
    # After alignment, the road must be horizontal (traj z stays near 1.2 m, not sloped by 40 deg!)
    traj_z = rec.trajectory()[:, 2]
    assert np.ptp(traj_z) < 0.15, f"Road tilted after align: traj_z span={np.ptp(traj_z):.3f} m"
    assert abs(float(np.median(traj_z)) - 1.2) < 0.15


def test_align_handles_unscaled_compact_lingbot_cloud():
    """Unscaled LingBot clouds can have total extent ~1.0 unit; fixed 0.2 voxel downsampling
    must not collapse them to too few points for ground-plane RANSAC."""
    rng = np.random.default_rng(11)
    # Compact cloud of extent 1.2 units (like close-range LingBot output)
    road = np.c_[rng.uniform(-0.6, 0.6, 5000), rng.uniform(-0.4, 0.4, 5000), rng.normal(0, 0.002, 5000)]
    R_base = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    p = math.radians(35.0)
    R_wc = R_base @ np.array([[1.0, 0.0, 0.0], [0.0, math.cos(p), -math.sin(p)], [0.0, math.sin(p), math.cos(p)]])
    poses = np.repeat(np.eye(4)[None], 10, axis=0)
    poses[:, :3, :3] = R_wc
    poses[:, :3, 3] = np.c_[np.linspace(-0.2, 0.2, 10), np.zeros(10), np.full(10, 0.5)]
    rec = Reconstruction(
        points=road.astype(np.float32), poses=poses,
        meta={"metric": False, "up_axis": "auto", "camera_convention": "opencv"},
    )
    notes = align(rec, 13.8, 100.5, {"camera_height_m": 0.5})
    assert any("dominant (ground) plane" in n for n in notes), notes
    assert np.ptp(rec.trajectory()[:, 2]) < 0.05


def test_analyze_detects_pothole_on_uphill_road_above_z_1m():
    """A sloped road climbing > 2 m over 25 m must not lose its uphill potholes to a global z < 1 m cutoff."""
    rng = np.random.default_rng(7)
    s, o = np.meshgrid(np.arange(0.0, 25.0, 0.05), np.arange(-3.0, 3.0, 0.05), indexing="ij")
    x = o.ravel()
    y = s.ravel()
    z = 0.10 * y + rng.normal(0.0, 0.002, y.size)  # 10% grade: rises from z=0 to z=2.5 m!
    # Pothole at y = 20 m where road elevation is z = 2.0 m (well above z = 1.0 m)
    r2 = x * x + (y - 20.0) ** 2
    z[r2 < 0.35 ** 2] -= 0.07 * (1.0 - r2[r2 < 0.35 ** 2] / (0.35 ** 2))
    poses = np.repeat(np.eye(4)[None], 26, axis=0)
    poses[:, :3, 3] = np.c_[np.zeros(26), np.linspace(0.0, 25.0, 26), 0.10 * np.linspace(0.0, 25.0, 26) + 1.4]
    rec = Reconstruction(
        points=np.c_[x, y, z].astype(np.float32), poses=poses,
        meta={"metric": True, "up_axis": "z"},
    )
    an = analyze(rec)
    potholes = [f for f in an["findings"] if f["type"] == "pothole"]
    assert len(potholes) == 1, f"Expected uphill pothole at y=20 m, got {potholes}"
    assert abs(potholes[0]["y"] - 20.0) < 0.3

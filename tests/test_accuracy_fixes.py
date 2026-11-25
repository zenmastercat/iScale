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


def test_pothole_local_refinement_achieves_accurate_depth_area_volume_on_parabolic_bowl():
    """On a crowned road with a realistic 6.5 cm parabolic bowl (R=0.35 m, noise=5 mm),
    local road-plane refinement must measure depth within 0.6 cm, area within 10%, volume within 12%."""
    rng = np.random.default_rng(19)
    s, o = np.meshgrid(np.arange(0.0, 20.0, 0.03), np.arange(-3.0, 3.0, 0.03), indexing="ij")
    x, y = o.ravel(), s.ravel()
    R, D = 0.35, 0.065
    z = -0.02 * (x * x) / 3.0 + rng.normal(0.0, 0.005, x.size)
    r2 = (x - 0.5) ** 2 + (y - 10.0) ** 2
    inside = r2 < R * R
    z[inside] -= D * (1.0 - r2[inside] / (R * R))
    poses = np.repeat(np.eye(4)[None], 21, axis=0)
    poses[:, :3, 3] = np.c_[np.zeros(21), np.linspace(0.0, 20.0, 21), np.full(21, 1.4)]
    rec = Reconstruction(points=np.c_[x, y, z].astype(np.float32), poses=poses, meta={"metric": True, "up_axis": "z"})
    an = analyze(rec)
    potholes = [f for f in an["findings"] if f["type"] == "pothole"]
    assert len(potholes) == 1, potholes
    m = potholes[0]["metrics"]
    gt_area = math.pi * R * R
    gt_vol = 0.5 * gt_area * D
    assert abs(m["depth_max_m"] - D) < 0.006, f"depth={m['depth_max_m']} vs {D}"
    assert abs(m["area_m2"] - gt_area) / gt_area < 0.10, f"area={m['area_m2']} vs {gt_area:.4f}"
    assert abs(m["volume_m3"] - gt_vol) / gt_vol < 0.12, f"vol={m['volume_m3']} vs {gt_vol:.5f}"


def test_small_dense_pothole_detected_and_measured_accurately_when_min_area_allows():
    """A 9 cm wide, 4.2 cm deep pothole in a dense 5 mm cloud (like real stereo/laser scans)
    must not vanish into a 10 cm cell median or blow up 700% in area."""
    rng = np.random.default_rng(23)
    # Dense patch around pothole + standard collar
    s, o = np.meshgrid(np.arange(1.5, 4.5, 0.006), np.arange(-1.5, 1.5, 0.006), indexing="ij")
    x, y = o.ravel(), s.ravel()
    R, D = 0.045, 0.042
    z = rng.normal(0.0, 0.0015, x.size)
    r2 = x * x + (y - 3.0) ** 2
    inside = r2 < R * R
    z[inside] -= D * (1.0 - r2[inside] / (R * R))
    poses = np.repeat(np.eye(4)[None], 13, axis=0)
    poses[:, :3, 3] = np.c_[np.zeros(13), np.linspace(0.0, 6.0, 13), np.full(13, 0.6)]
    rec = Reconstruction(points=np.c_[x, y, z].astype(np.float32), poses=poses, meta={"metric": True, "up_axis": "z"})
    an = analyze(rec, {"pothole_min_area_m2": 0.002, "pothole_min_depth_m": 0.015})
    potholes = [f for f in an["findings"] if f["type"] == "pothole"]
    assert len(potholes) == 1, potholes
    m = potholes[0]["metrics"]
    gt_area = math.pi * R * R
    gt_vol = 0.5 * gt_area * D
    assert abs(m["depth_max_m"] - D) < 0.006, f"depth={m['depth_max_m']} vs {D}"
    assert abs(m["area_m2"] - gt_area) / gt_area < 0.15, f"area={m['area_m2']} vs {gt_area:.5f}"
    assert abs(m["volume_m3"] - gt_vol) / gt_vol < 0.18, f"vol={m['volume_m3']} vs {gt_vol:.6f}"


def test_sub_10cm_dense_laser_like_pothole_achieves_tight_area_and_depth_accuracy():
    """On a sub-mm dense 9 cm pothole surrounded by a coarser 2 cm road cloud (so the coarse
    10 cm raster sees it as a 20 cm block), fine-cell sizing must adapt to the depression's
    point density rather than the coarse 10 cm box diameter (area err < 10%, depth < 0.3 cm)."""
    rng = np.random.default_rng(31)
    # Dense 2 mm points inside the pothole (mimicking dense scan/reprojection) + 2 cm road around it
    R, D = 0.044, 0.041
    ps, po = np.meshgrid(np.arange(3.0 - R, 3.0 + R, 0.002), np.arange(-R, R, 0.002), indexing="ij")
    px, py = po.ravel(), ps.ravel()
    r2 = px * px + (py - 3.0) ** 2
    inside = r2 < R * R
    px, py = px[inside], py[inside]
    pz = -D * np.sqrt(np.maximum(0.0, 1.0 - (r2[inside] / (R * R)) ** 2))
    # 2 cm road surface outside the pothole
    cs, co = np.meshgrid(np.arange(0.0, 6.0, 0.02), np.arange(-2.5, 2.5, 0.02), indexing="ij")
    cx, cy = co.ravel(), cs.ravel()
    out = (cx * cx + (cy - 3.0) ** 2) >= R * R
    pts = np.vstack([
        np.c_[px, py, pz],
        np.c_[cx[out], cy[out], rng.normal(0.0, 0.001, int(out.sum()))],
    ]).astype(np.float32)
    poses = np.repeat(np.eye(4)[None], 13, axis=0)
    poses[:, :3, 3] = np.c_[np.zeros(13), np.linspace(0.0, 6.0, 13), np.full(13, 0.8)]
    rec = Reconstruction(points=pts, poses=poses, meta={"metric": True, "up_axis": "z"})
    an = analyze(rec, {"pothole_min_area_m2": 0.002, "pothole_min_depth_m": 0.015})
    potholes = [f for f in an["findings"] if f["type"] == "pothole"]
    assert len(potholes) == 1, potholes
    m = potholes[0]["metrics"]
    # Exact analytical area = pi*R^2, volume = (pi/4) * pi*R^2 * D for sqrt(1 - (r/R)^4)
    gt_area = math.pi * R * R
    gt_vol = (math.pi / 4.0) * gt_area * D
    assert abs(m["depth_max_m"] - D) < 0.003, f"depth={m['depth_max_m']} vs {D}"
    assert abs(m["area_m2"] - gt_area) / gt_area < 0.10, f"area={m['area_m2']} vs {gt_area:.5f}"
    assert abs(m["volume_m3"] - gt_vol) / gt_vol < 0.10, f"vol={m['volume_m3']} vs {gt_vol:.6f}"


def test_forge_slam_preserves_near_road_pothole_volume_under_15_pct(tmp_path):
    """FORGE SLAM default keyframes must preserve near-road pothole geometry at ~4 cm resolution
    (matching export_world_cloud) rather than collapsing road points to 10 cm voxels."""
    from civil.bench_potholes import (
        AnalyticalPotholeSpec,
        SyntheticRoadScene,
        run_synth_forge_scene,
    )

    sc = SyntheticRoadScene(
        name="tdd_forge_road_res",
        split="dev",
        length_m=18.0,
        half_width_m=3.5,
        crown_slope=0.02,
        grade_slope=0.0,
        noise_sigma_m=0.010,
        seed=77,
        potholes=[
            AnalyticalPotholeSpec("p1", 6.0, -0.5, 0.25, 0.22, 0.055, 0.1, "parabolic"),
            AnalyticalPotholeSpec("p2", 12.0, 0.4, 0.35, 0.30, 0.080, -0.2, "steep"),
        ],
    )
    res = run_synth_forge_scene(sc, tmp_path)
    assert res["n_matched"] == 2, res
    vol_mae = float(np.mean([m["vol_err_pct"] for m in res["matches"]]))
    area_mae = float(np.mean([m["area_err_pct"] for m in res["matches"]]))
    assert vol_mae < 12.0, f"FORGE volume MAE too high: {vol_mae:.1f}% ({res['matches']})"
    assert area_mae < 18.0, f"FORGE area MAE too high: {area_mae:.1f}% ({res['matches']})"


def test_forge_tile_memory_prefers_closest_range_point_per_voxel(tmp_path):
    """When an early far keyframe and a later close keyframe both observe the same voxel,
    export_world_cloud must keep the closer sensor observation (higher precision, lower grazing drift)."""
    from civil.forge.memory import SpatialTileMemory

    mem = SpatialTileMemory(tmp_path / "tiles", tile_size_m=20.0, max_ram_bytes=64 * 1024 * 1024)
    # KF 0 at x=0 observes a point at world (10.01, 0.01, -0.02) from 10 m away (drifted)
    T0 = np.eye(4)
    mem.insert_keyframe_points(0, T0, np.array([[10.01, 0.01, -0.02]], dtype=np.float32))
    # KF 1 at x=9 observes the same 4 cm voxel at world (10.02, 0.02, -0.035) from only 1 m away (accurate)
    T1 = np.eye(4)
    T1[0, 3] = 9.0
    mem.insert_keyframe_points(1, T1, np.array([[1.02, 0.02, -0.035]], dtype=np.float32))
    pts, _, _ = mem.export_world_cloud(voxel_size_m=0.04)
    assert len(pts) == 1
    assert abs(float(pts[0, 2]) - (-0.035)) < 1e-4, f"Expected close-range z=-0.035, got {pts[0]}"

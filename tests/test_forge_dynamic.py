"""TDD tests for FORGE SLAM Stage 2: Ground-Protected Temporal Dynamic Object Removal."""

from __future__ import annotations

import numpy as np


def _first_hit_scan(world: np.ndarray, origin: np.ndarray, az_deg: float = 0.4, el_deg: float = 1.0) -> np.ndarray:
    """LiDAR-like scan of a densely sampled world: keep the nearest surface point per (azimuth, elevation) cell.

    Returns indices into `world`. Surfaces behind nearer ones are occluded, as with a real sensor.
    """
    rel = world - origin
    r = np.linalg.norm(rel, axis=1)
    az = np.floor((np.degrees(np.arctan2(rel[:, 1], rel[:, 0])) + 180.0) / az_deg).astype(np.int64)
    el = np.floor((np.degrees(np.arcsin(np.clip(rel[:, 2] / np.maximum(r, 1e-9), -1, 1))) + 90.0) / el_deg).astype(np.int64)
    cell = az * 100000 + el
    order = np.lexsort((r, cell))
    first = np.ones(len(order), bool)
    first[1:] = cell[order][1:] != cell[order][:-1]
    hit = order[first]
    return hit[(r[hit] > 0.5) & (r[hit] < 60.0)]


def test_dynamic_filter_removes_moving_car_and_pedestrian_and_preserves_shallow_pothole():
    from civil.forge.dynamic_filter import TemporalDynamicFilter
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(7)
    cfg = ForgeConfig(keyframe_dist_m=1.0, keyframe_angle_deg=10.0)
    filt = TemporalDynamicFilter(cfg)

    # Street: road, a 6 cm pothole, a wall on the left and a building facade on the right (behind the car)
    rx, ry = np.meshgrid(np.arange(-2.0, 50.0, 0.06), np.arange(-8.0, 3.2, 0.06))
    road = np.column_stack([rx.ravel(), ry.ravel(), np.zeros(rx.size)])
    d_hole = np.hypot(road[:, 0] - 8.0, road[:, 1] - 0.5)
    in_hole = d_hole <= 0.40
    road[in_hole, 2] = -0.06 * np.cos(np.pi * d_hole[in_hole] / 0.80)
    wx, wz = np.meshgrid(np.arange(-2.0, 50.0, 0.06), np.arange(0.1, 4.0, 0.06))
    wall = np.column_stack([wx.ravel(), np.full(wx.size, 3.2), wz.ravel()])
    facade = np.column_stack([wx.ravel(), np.full(wx.size, -8.0), wz.ravel() * 1.5])
    ey, ez = np.meshgrid(np.arange(-8.0, 3.2, 0.06), np.arange(0.0, 6.0, 0.06))
    end_wall = np.column_stack([np.full(ey.size, 50.0), ey.ravel(), ez.ravel()])  # street continues to 50 m
    static_world = np.vstack([road, wall, facade, end_wall])
    n_road = len(road)
    car = np.column_stack([rng.uniform(9.5, 11.8, 20000), rng.uniform(-1.6, -0.4, 20000), rng.uniform(0.05, 1.35, 20000)])
    ped = np.column_stack([rng.uniform(6.0, 6.4, 6000), rng.uniform(1.2, 1.6, 6000), rng.uniform(0.05, 1.75, 6000)])

    keyframes: list[Keyframe] = []
    labels = None
    for k in range(5):
        T_wb = np.eye(4, dtype=np.float64)
        T_wb[:3, 3] = [k * 1.2, 0.0, 1.5]  # body = LiDAR, 1.5 m above the road
        assert k == 0 or filt.should_create_keyframe(T_wb)
        filt.record_keyframe_pose(T_wb)
        world = np.vstack([static_world, car, ped]) if k == 2 else static_world
        lab = np.concatenate([np.zeros(n_road, int), np.ones(len(static_world) - n_road, int), np.full(len(car) + len(ped), 2)]) if k == 2 else None
        hit = _first_hit_scan(world, T_wb[:3, 3])
        if k == 2:
            labels = lab[hit]
            hole_hit = np.isin(hit, np.flatnonzero(in_hole))
        pts_local = (world[hit] - T_wb[:3, 3]).astype(np.float32)
        keyframes.append(Keyframe(k, float(k), T_wb, pts_local, pts_local.copy(), np.zeros(len(pts_local), bool)))

    static_pts, dyn_mask, stats = filt.filter_keyframe_window(keyframes, target_idx=2)
    assert len(static_pts) == int((~dyn_mask).sum())
    moving = labels == 2
    assert moving.sum() > 200
    assert float(dyn_mask[moving].mean()) >= 0.85, f"only {dyn_mask[moving].mean():.0%} of moving points removed"
    assert hole_hit.sum() >= 15
    assert float(dyn_mask[hole_hit].mean()) < 0.01
    assert float(dyn_mask[labels == 0].mean()) < 0.02
    assert float(dyn_mask[labels == 1].mean()) < 0.02
    assert stats["removed_dynamic_points"] == int(dyn_mask.sum())


def test_dynamic_filter_preserves_2cm_to_15cm_potholes_and_briefly_occluded_static_objects():
    from civil.forge.dynamic_filter import TemporalDynamicFilter
    from civil.forge.types import ForgeConfig, Keyframe

    filt = TemporalDynamicFilter(ForgeConfig())
    rx, ry = np.meshgrid(np.linspace(2.0, 16.0, 140), np.linspace(-2.5, 2.5, 50))
    road_xy = np.column_stack([rx.ravel(), ry.ravel()])
    road_z = np.zeros(len(road_xy), dtype=np.float64)

    # Plant three potholes of depths 2.5 cm, 7.5 cm, and 14.5 cm
    specs = [(5.0, -0.5, 0.025), (8.0, 0.0, 0.075), (11.0, 0.6, 0.145)]
    hole_masks = []
    for hx, hy, depth_m in specs:
        d = np.hypot(road_xy[:, 0] - hx, road_xy[:, 1] - hy)
        m = d <= 0.35
        road_z[m] = -depth_m * np.cos(math.pi * d[m] / 0.70) if "math" in globals() else -depth_m * np.cos(np.pi * d[m] / 0.70)
        hole_masks.append(m)

    road_w = np.column_stack([road_xy, road_z])
    # Static roadside fire hydrant at x=9.0, y=2.0, z in [0.2, 0.9] visible in keyframes 1 and 2 (occluded in 0, 3, 4)
    hx, hy, hz = np.meshgrid(np.linspace(8.85, 9.15, 4), np.linspace(1.85, 2.15, 4), np.linspace(0.2, 0.9, 5))
    hydrant_w = np.column_stack([hx.ravel(), hy.ravel(), hz.ravel()])

    keyframes: list[Keyframe] = []
    for k in range(5):
        T_wb = np.eye(4, dtype=np.float64)
        T_wb[:3, 3] = [k * 1.0, 0.0, 1.5]
        pts_w = np.vstack([road_w, hydrant_w]) if k in (1, 2) else road_w.copy()
        pts_local = (pts_w - T_wb[:3, 3]).astype(np.float32)
        keyframes.append(
            Keyframe(
                id=k,
                t=float(k),
                pose_w_b=T_wb,
                points_local=pts_local,
                raw_points_local=pts_local.copy(),
                dynamic_mask=np.zeros(len(pts_local), dtype=bool),
            )
        )

    _, dyn_mask, _ = filt.filter_keyframe_window(keyframes, target_idx=2)
    # Every pothole (2.5 cm, 7.5 cm, 14.5 cm) must have 0% erosion
    for idx, m in enumerate(hole_masks):
        lost = float(dyn_mask[: len(road_w)][m].mean())
        assert lost == 0.0, f"Pothole {idx} eroded by {lost:.2%}"
    # Briefly occluded static hydrant (visible in keyframes 1 and 2) must be preserved
    hydrant_lost = float(dyn_mask[len(road_w) :].mean())
    assert hydrant_lost == 0.0, f"Briefly occluded static hydrant falsely removed: {hydrant_lost:.2%}"


def test_dynamic_filter_empty_and_single_keyframe_inputs():
    from civil.forge.dynamic_filter import TemporalDynamicFilter
    from civil.forge.types import ForgeConfig, Keyframe

    filt = TemporalDynamicFilter(ForgeConfig())
    empty_kf = Keyframe(
        id=0,
        t=0.0,
        pose_w_b=np.eye(4),
        points_local=np.zeros((0, 3), dtype=np.float32),
        raw_points_local=np.zeros((0, 3), dtype=np.float32),
        dynamic_mask=np.zeros(0, dtype=bool),
    )
    pts, mask, stats = filt.filter_keyframe_window([empty_kf], target_idx=0)
    assert len(pts) == 0 and len(mask) == 0 and stats["removed_dynamic_points"] == 0

    single_kf = Keyframe(
        id=0,
        t=0.0,
        pose_w_b=np.eye(4),
        points_local=np.ones((25, 3), dtype=np.float32),
        raw_points_local=np.ones((25, 3), dtype=np.float32),
        dynamic_mask=np.zeros(25, dtype=bool),
    )
    pts1, mask1, stats1 = filt.filter_keyframe_window([single_kf], target_idx=0)
    assert len(pts1) == 25 and not np.any(mask1) and stats1["removed_dynamic_points"] == 0


def _ray_cast_scan(world: np.ndarray, origin: np.ndarray, rng: np.random.Generator, keep: float) -> np.ndarray:
    """Sparse first-hit scan: occluded points dropped, then a random subset kept (differs scan to scan)."""
    hit = _first_hit_scan(world, origin, az_deg=0.2, el_deg=0.5)
    hit = hit[rng.random(len(hit)) < keep]
    return world[hit] - origin


def test_sparse_far_static_facade_is_kept_without_free_space_evidence():
    """Far static structure is sampled differently in every scan; 'not re-seen in the same voxel' is not evidence of motion."""
    from civil.forge.dynamic_filter import TemporalDynamicFilter
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(11)
    fx, fz = rng.uniform(-5, 35, 60000), rng.uniform(0.3, 10.0, 60000)
    facade = np.column_stack([fx, np.full(fx.size, 22.0), fz])  # building wall 22 m to the left
    gx, gy = rng.uniform(-5, 35, 40000), rng.uniform(-6, 21, 40000)
    road = np.column_stack([gx, gy, np.zeros(gx.size)])
    parked = np.column_stack([rng.uniform(12, 16, 3000), rng.uniform(-4.5, -3.0, 3000), rng.uniform(0.2, 1.5, 3000)])
    world = np.vstack([facade, road, parked])

    kfs = []
    for k in range(6):
        T = np.eye(4)
        T[:3, 3] = [k * 2.0, 0.0, 1.5]
        pts = _ray_cast_scan(world, T[:3, 3], rng, keep=0.15).astype(np.float32)
        kfs.append(Keyframe(k, float(k), T, pts, pts.copy(), np.zeros(len(pts), bool)))

    target = kfs[3]
    _, mask, _ = TemporalDynamicFilter(ForgeConfig()).filter_keyframe_window(kfs, target_idx=3)
    pts_w = target.raw_points_local.astype(np.float64) + target.pose_w_b[:3, 3]
    on_facade = np.abs(pts_w[:, 1] - 22.0) < 1e-3
    on_parked = (pts_w[:, 1] < -2.9) & (pts_w[:, 2] > 0.15)
    assert float(mask[on_facade].mean()) < 0.02, f"{mask[on_facade].mean():.1%} of a static facade removed"
    assert float(mask[on_parked].mean()) < 0.02, f"{mask[on_parked].mean():.1%} of a parked car removed"

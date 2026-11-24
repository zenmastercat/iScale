"""TDD tests for FORGE SLAM Stage 2: Ground-Protected Temporal Dynamic Object Removal."""

from __future__ import annotations

import numpy as np


def test_dynamic_filter_removes_moving_car_and_preserves_shallow_pothole():
    from civil.forge.dynamic_filter import TemporalDynamicFilter
    from civil.forge.types import ForgeConfig, Keyframe

    rng = np.random.default_rng(7)
    cfg = ForgeConfig(keyframe_dist_m=1.0, keyframe_angle_deg=10.0)
    filt = TemporalDynamicFilter(cfg)

    # Static street: 20 m x 6 m asphalt road at z = 0 with a 6 cm deep, 0.8 m diameter pothole at (8.0, 0.5)
    rx, ry = np.meshgrid(np.linspace(2.0, 18.0, 120), np.linspace(-3.0, 3.0, 50))
    road_xy = np.column_stack([rx.ravel(), ry.ravel()])
    dist_hole = np.hypot(road_xy[:, 0] - 8.0, road_xy[:, 1] - 0.5)
    in_pothole = dist_hole <= 0.40
    road_z = np.where(in_pothole, -0.06 * np.cos(np.pi * dist_hole / 0.80), 0.0)
    road_z += rng.normal(0.0, 0.002, size=road_z.shape)
    static_road_w = np.column_stack([road_xy, road_z])

    # Static curb wall at y = 3.2 m (height 0.2 to 1.5 m)
    wx, wz = np.meshgrid(np.linspace(2.0, 18.0, 60), np.linspace(0.2, 1.5, 12))
    static_wall_w = np.column_stack([wx.ravel(), np.full(wx.size, 3.2), wz.ravel()])
    static_world = np.vstack([static_road_w, static_wall_w])
    n_static = len(static_world)
    pothole_indices = np.flatnonzero(in_pothole)
    assert len(pothole_indices) >= 15

    # Build 5 keyframes spaced 1.2 m apart along +X (sensor height 1.5 m above road, grazing angle ~8 deg)
    # In keyframe 2 (target), a moving vehicle box (length 3.0 m, width 1.6 m, height 0.02..1.4 m)
    # is at x in [9.0, 12.0], y in [-1.8, -0.2]; in other keyframes the vehicle has moved away.
    keyframes: list[Keyframe] = []
    for k in range(5):
        T_wb = np.eye(4, dtype=np.float64)
        T_wb[:3, 3] = [k * 1.2, 0.0, 0.0]
        assert k == 0 or filt.should_create_keyframe(T_wb)
        filt.record_keyframe_pose(T_wb)

        pts_w = static_world.copy()
        if k == 2:
            # Add 400 dynamic car points (including low tire points at z=0.05..0.25 and body at z=0.25..1.4)
            cx = rng.uniform(9.5, 11.8, 400)
            cy = rng.uniform(-1.6, -0.4, 400)
            cz = rng.uniform(0.05, 1.35, 400)
            car_w = np.column_stack([cx, cy, cz])
            pts_w = np.vstack([pts_w, car_w])

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

    static_pts, dyn_mask, stats = filt.filter_keyframe_window(keyframes, target_idx=2)

    assert dyn_mask.dtype == bool
    assert len(dyn_mask) == n_static + 400
    assert len(static_pts) == int((~dyn_mask).sum())

    # 1. Dynamic car removal rate must be >= 85%
    car_mask = dyn_mask[n_static:]
    car_removed_ratio = float(car_mask.mean())
    assert car_removed_ratio >= 0.85, f"Expected >= 85% dynamic vehicle removal, got {car_removed_ratio:.2%}"

    # 2. Pothole points (negative relief -6 cm) must be preserved (< 1% loss)
    pothole_lost = float(dyn_mask[pothole_indices].mean())
    assert pothole_lost < 0.01, f"Pothole points eroded by dynamic filter: {pothole_lost:.2%}"

    # 3. Overall static road preservation (>= 98% retained)
    static_road_lost = float(dyn_mask[: len(static_road_w)].mean())
    assert static_road_lost < 0.02, f"Static road loss too high: {static_road_lost:.2%}"
    assert stats["removed_dynamic_points"] == int(dyn_mask.sum())

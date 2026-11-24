"""TDD tests for FORGE SLAM Stage 5: Spatial Tile Memory with LRU RAM <-> SSD Hot-Swap."""

from __future__ import annotations

import numpy as np


def test_spatial_tile_memory_lru_hotswap_and_zero_io_loop_closure(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    rng = np.random.default_rng(99)
    tiles_dir = tmp_path / "forge_tiles"

    # Set a tiny 64 KB RAM cap so inserting 8 tiles (each ~24 KB) forces deterministic SSD evictions
    with SpatialTileMemory(tiles_dir, tile_size_m=20.0, max_ram_bytes=64 * 1024) as mem:
        poses: dict[int, np.ndarray] = {}
        all_expected_local: dict[int, np.ndarray] = {}

        for kf_id in range(8):
            T_wb = np.eye(4, dtype=np.float64)
            T_wb[:3, 3] = [kf_id * 25.0, 0.0, 0.0]  # Each keyframe lands in a distinct 20m tile
            poses[kf_id] = T_wb
            pts_local = rng.uniform(-3.0, 3.0, size=(1200, 3)).astype(np.float32)
            cols = rng.integers(0, 255, size=(1200, 3), dtype=np.uint8)
            temps = rng.uniform(25.0, 40.0, size=(1200,)).astype(np.float32)
            all_expected_local[kf_id] = pts_local
            mem.insert_keyframe_points(kf_id, T_wb, pts_local, colors=cols, temperatures_c=temps)

            # Active RAM must never exceed max_ram_bytes
            assert mem.active_ram_bytes <= 64 * 1024

        stats1 = mem.stats()
        assert stats1["ssd_evictions_total"] >= 5, f"Expected >= 5 SSD evictions, got {stats1}"
        assert len(list(tiles_dir.glob("tile_*.npz"))) >= 5

        # Now simulate a GTSAM loop closure that shifts all keyframe poses by +10.0 m in Y
        evictions_before_loop = mem.evictions_to_ssd_total
        reloads_before_loop = mem.reloads_from_ssd_total
        updated_poses = {}
        for kf_id, T in poses.items():
            T_new = T.copy()
            T_new[1, 3] += 10.0
            updated_poses[kf_id] = T_new

        mem.update_poses(updated_poses)
        # Updating poses on loop closure must perform ZERO SSD reads or writes!
        assert mem.evictions_to_ssd_total == evictions_before_loop
        assert mem.reloads_from_ssd_total == reloads_before_loop

        # Export full world cloud (without downsampling) and verify all 8 * 1200 = 9600 points
        # reflect the updated +10.0 m Y loop-closure pose shift!
        pts_w, cols_w, temps_w = mem.export_world_cloud(voxel_size_m=None)
        assert len(pts_w) == 8 * 1200
        assert cols_w is not None and len(cols_w) == 8 * 1200
        assert temps_w is not None and len(temps_w) == 8 * 1200
        assert float(np.median(pts_w[:, 1])) > 7.0
        assert mem.reloads_from_ssd_total > reloads_before_loop

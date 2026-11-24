"""TDD tests for FORGE SLAM Stage 5: Spatial Tile Memory with LRU RAM <-> SSD Hot-Swap."""

from __future__ import annotations

import numpy as np
import pytest


def test_spatial_tile_memory_lru_hotswap_and_zero_io_loop_closure(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    rng = np.random.default_rng(99)
    tiles_dir = tmp_path / "forge_tiles"

    # Set a tiny 64 KB RAM cap so inserting 8 tiles (each ~22.8 KB) forces deterministic SSD evictions
    with SpatialTileMemory(tiles_dir, tile_size_m=20.0, max_ram_bytes=64 * 1024) as mem:
        poses: dict[int, np.ndarray] = {}
        for kf_id in range(8):
            T_wb = np.eye(4, dtype=np.float64)
            T_wb[:3, 3] = [kf_id * 25.0, 0.0, 0.0]
            poses[kf_id] = T_wb
            pts_local = rng.uniform(-3.0, 3.0, size=(1200, 3)).astype(np.float32)
            cols = rng.integers(0, 255, size=(1200, 3), dtype=np.uint8)
            temps = rng.uniform(25.0, 40.0, size=(1200,)).astype(np.float32)
            mem.insert_keyframe_points(kf_id, T_wb, pts_local, colors=cols, temperatures_c=temps)

            assert mem.active_ram_bytes <= 64 * 1024
            assert mem.peak_ram_bytes <= 64 * 1024

        stats1 = mem.stats()
        assert stats1["ssd_evictions_total"] >= 5
        assert len(list(tiles_dir.glob("tile_*.npz"))) >= 5

        evictions_before_loop = mem.evictions_to_ssd_total
        reloads_before_loop = mem.reloads_from_ssd_total
        updated_poses = {}
        for kf_id, T in poses.items():
            T_new = T.copy()
            T_new[1, 3] += 10.0
            updated_poses[kf_id] = T_new

        mem.update_poses(updated_poses)
        assert mem.evictions_to_ssd_total == evictions_before_loop
        assert mem.reloads_from_ssd_total == reloads_before_loop

        pts_w, cols_w, temps_w = mem.export_world_cloud(voxel_size_m=None)
        assert len(pts_w) == 8 * 1200
        assert cols_w is not None and len(cols_w) == 8 * 1200
        assert temps_w is not None and len(temps_w) == 8 * 1200
        assert float(np.median(pts_w[:, 1])) > 7.0
        assert mem.reloads_from_ssd_total > reloads_before_loop


def test_memory_evict_and_reload_exact_roundtrip(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    rng = np.random.default_rng(7)
    tiles_dir = tmp_path / "exact_tiles"
    # Each chunk of 100 pts with colors+temps is 100*(12+3+4) = 1900 bytes; cap at 2500 bytes (1 tile in RAM)
    mem = SpatialTileMemory(tiles_dir, tile_size_m=10.0, max_ram_bytes=2500)
    T0 = np.eye(4, dtype=np.float64)
    T1 = np.eye(4, dtype=np.float64)
    T1[:3, 3] = [20.0, 0.0, 0.0]

    pts0 = rng.uniform(-1.0, 1.0, size=(100, 3)).astype(np.float32)
    col0 = rng.integers(0, 255, size=(100, 3), dtype=np.uint8)
    tmp0 = rng.uniform(18.0, 35.0, size=(100,)).astype(np.float32)

    pts1 = rng.uniform(-1.0, 1.0, size=(100, 3)).astype(np.float32)
    col1 = rng.integers(0, 255, size=(100, 3), dtype=np.uint8)
    tmp1 = rng.uniform(18.0, 35.0, size=(100,)).astype(np.float32)

    mem.insert_keyframe_points(0, T0, pts0, colors=col0, temperatures_c=tmp0)
    mem.insert_keyframe_points(1, T1, pts1, colors=col1, temperatures_c=tmp1)
    assert mem.evictions_to_ssd_total == 1
    assert (0, 0) in mem._ssd_tile_keys

    # Reload tile (0, 0) from SSD and verify bit-exact roundtrip
    reloaded = mem._get_or_create_tile((0, 0))
    assert len(reloaded.chunks) == 1
    np.testing.assert_array_equal(reloaded.chunks[0].points_local, pts0)
    np.testing.assert_array_equal(reloaded.chunks[0].colors, col0)
    np.testing.assert_array_equal(reloaded.chunks[0].temperatures_c, tmp0)


def test_memory_lru_eviction_order(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    tiles_dir = tmp_path / "lru_tiles"
    # Each 100-pt xyz-only chunk is 1200 bytes; cap at 2600 bytes so at most 2 tiles fit in RAM
    mem = SpatialTileMemory(tiles_dir, tile_size_m=10.0, max_ram_bytes=2600)
    pts = np.ones((100, 3), dtype=np.float32)

    for kf_id, x in ((0, 0.0), (1, 15.0)):
        T = np.eye(4)
        T[0, 3] = x
        mem.insert_keyframe_points(kf_id, T, pts)

    # Both (0, 0) and (1, 0) are in RAM; touch (0, 0) so (1, 0) becomes least-recently-used
    mem._get_or_create_tile((0, 0))

    # Insert tile (2, 0) at x = 25.0 -> must evict (1, 0), keeping (0, 0) and (2, 0) in RAM
    T2 = np.eye(4)
    T2[0, 3] = 25.0
    mem.insert_keyframe_points(2, T2, pts)
    assert (1, 0) in mem._ssd_tile_keys
    assert (1, 0) not in mem._ram_tiles
    assert (0, 0) in mem._ram_tiles
    assert (2, 0) in mem._ram_tiles


def test_memory_corrupt_and_missing_tile_raises(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    tiles_dir = tmp_path / "corrupt_tiles"
    mem = SpatialTileMemory(tiles_dir, tile_size_m=10.0, max_ram_bytes=1500)
    pts = np.ones((100, 3), dtype=np.float32)

    T0 = np.eye(4)
    T1 = np.eye(4)
    T1[0, 3] = 15.0
    mem.insert_keyframe_points(0, T0, pts)
    mem.insert_keyframe_points(1, T1, pts)  # Evicts (0, 0) to SSD

    tile0_path = tiles_dir / "tile_0_0.npz"
    assert tile0_path.is_file()

    # Overwrite with corrupt bytes
    tile0_path.write_bytes(b"NOT_A_VALID_NPZ_ARCHIVE")
    with pytest.raises(RuntimeError, match="Corrupt SSD tile archive"):
        mem.export_world_cloud(voxel_size_m=None)

    # Delete spilled tile file and verify FileNotFoundError
    tile0_path.unlink()
    with pytest.raises(FileNotFoundError, match="SSD tile file missing"):
        mem.export_world_cloud(voxel_size_m=None)


def test_memory_cleanup_and_path_traversal_guard(tmp_path):
    from civil.forge.memory import SpatialTileMemory

    tiles_dir = tmp_path / "guard_tiles"
    with SpatialTileMemory(tiles_dir, tile_size_m=10.0, max_ram_bytes=1500) as mem:
        pts = np.ones((100, 3), dtype=np.float32)
        T0, T1 = np.eye(4), np.eye(4)
        T1[0, 3] = 15.0
        mem.insert_keyframe_points(0, T0, pts)
        mem.insert_keyframe_points(1, T1, pts)

        # Reject path traversal or non-integer keys
        for bad_key in (("../evil", 0), (0, "../../etc/passwd"), (True, 0), (1.5, 2)):
            with pytest.raises(ValueError):
                mem._tile_path(bad_key)  # type: ignore[arg-type]

        removed = mem.cleanup_ssd()
        assert removed == 1
        assert len(list(tiles_dir.glob("tile_*.npz"))) == 0

    # After context manager exit, RAM must be 0
    assert mem.active_ram_bytes == 0
    assert len(mem._ram_tiles) == 0


def test_tile_larger_than_ram_cap_keeps_every_chunk(tmp_path):
    """Many keyframes in one 20 m tile can exceed the RAM cap; no chunk may be lost or overwritten on spill."""
    from civil.forge.memory import SpatialTileMemory

    rng = np.random.default_rng(4)
    mem = SpatialTileMemory(tmp_path / "big_tile", tile_size_m=20.0, max_ram_bytes=3000)
    chunks = []
    for kf_id in range(6):  # 6 x 1200 B into the same tile, cap 3000 B
        T = np.eye(4)
        T[0, 3] = 1.0 + kf_id
        pts = rng.uniform(-1, 1, (100, 3)).astype(np.float32)
        chunks.append(pts + T[:3, 3].astype(np.float32))
        mem.insert_keyframe_points(kf_id, T, pts)
        assert mem.active_ram_bytes <= 3000
    T_far = np.eye(4)
    T_far[0, 3] = 50.0
    mem.insert_keyframe_points(99, T_far, np.zeros((100, 3), np.float32))  # forces the big tile out again

    pts_w, _, _ = mem.export_world_cloud(voxel_size_m=None)
    assert len(pts_w) == 7 * 100
    for c in chunks:
        assert np.isin(c[:, 0], pts_w[:, 0]).all()

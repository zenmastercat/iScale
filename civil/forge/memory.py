"""Stage 5: Spatial Tile/Octree Memory with LRU RAM <-> SSD Hot-Swap and Zero-I/O Loop-Closure Updates."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
import time

import numpy as np

from ..pointcloud import voxel_downsample


@dataclass
class _TileChunk:
    kf_id: int
    points_local: np.ndarray                  # (M, 3) float32 in keyframe-local frame F_k
    colors: np.ndarray | None = None          # (M, 3) uint8
    temperatures_c: np.ndarray | None = None  # (M,) float32

    @property
    def nbytes(self) -> int:
        b = int(self.points_local.nbytes)
        if self.colors is not None:
            b += int(self.colors.nbytes)
        if self.temperatures_c is not None:
            b += int(self.temperatures_c.nbytes)
        return b


@dataclass
class _Tile:
    ix: int
    iy: int
    chunks: list[_TileChunk] = field(default_factory=list)

    @property
    def nbytes(self) -> int:
        return sum(c.nbytes for c in self.chunks)


class SpatialTileMemory:
    """Out-of-core 2D/3D spatial tile manager with bounded active RAM and LRU SSD hot-swap.

    Point chunks are stored in immutable keyframe-local coordinates F_k so that when loop closure
    updates keyframe poses {kf_id: T_w_k}, zero SSD reads or writes are required.
    """

    def __init__(self, tiles_dir: Path, tile_size_m: float = 20.0, max_ram_bytes: int = 512 * 1024 * 1024) -> None:
        self.tiles_dir = Path(tiles_dir)
        self.tiles_dir.mkdir(parents=True, exist_ok=True)
        self.tile_size_m = float(tile_size_m)
        self.max_ram_bytes = int(max_ram_bytes)

        self._poses: dict[int, np.ndarray] = {}
        self._ram_tiles: OrderedDict[tuple[int, int], _Tile] = OrderedDict()
        self._ssd_tile_keys: set[tuple[int, int]] = set()

        self.active_ram_bytes: int = 0
        self.peak_ram_bytes: int = 0
        self.hits_total: int = 0
        self.misses_total: int = 0
        self.evictions_to_ssd_total: int = 0
        self.reloads_from_ssd_total: int = 0
        self.io_time_ms: float = 0.0

    def __enter__(self) -> "SpatialTileMemory":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Clear in-RAM tile cache and reset active RAM usage to zero."""
        self._ram_tiles.clear()
        self.active_ram_bytes = 0

    def cleanup_ssd(self) -> int:
        """Delete all spilled tile archives from tiles_dir and return count removed."""
        removed = 0
        for key in list(self._ssd_tile_keys):
            p = self._tile_path(key)
            if p.is_file():
                p.unlink()
                removed += 1
        self._ssd_tile_keys.clear()
        return removed

    def _tile_path(self, key: tuple[int, int]) -> Path:
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not isinstance(key[0], (int, np.integer))
            or not isinstance(key[1], (int, np.integer))
            or isinstance(key[0], bool)
            or isinstance(key[1], bool)
        ):
            raise ValueError(f"Tile key must be a pair of integers (ix, iy), got {key!r}")
        ix, iy = int(key[0]), int(key[1])
        base = self.tiles_dir.resolve()
        candidate = (base / f"tile_{ix}_{iy}.npz").resolve()
        if candidate.parent != base:
            raise ValueError(f"Path traversal detected for tile key {key!r}")
        return candidate

    def _evict_lru_if_needed(self, incoming_bytes: int = 0) -> None:
        while self._ram_tiles and (self.active_ram_bytes + incoming_bytes > self.max_ram_bytes):
            victim_key, tile = self._ram_tiles.popitem(last=False)
            self.active_ram_bytes -= tile.nbytes
            self._save_tile_to_ssd(victim_key, tile)

    def _save_tile_to_ssd(self, key: tuple[int, int], tile: _Tile) -> None:
        if not tile.chunks:
            return
        t0 = time.perf_counter()
        path = self._tile_path(key)
        arrays: dict[str, np.ndarray] = {
            "n_chunks": np.array([len(tile.chunks)], dtype=np.int32),
        }
        for i, ch in enumerate(tile.chunks):
            arrays[f"kf_{i}"] = np.array([ch.kf_id], dtype=np.int32)
            arrays[f"pts_{i}"] = ch.points_local
            if ch.colors is not None:
                arrays[f"col_{i}"] = ch.colors
            if ch.temperatures_c is not None:
                arrays[f"tmp_{i}"] = ch.temperatures_c
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, **arrays)
        tmp.replace(path)
        self._ssd_tile_keys.add(key)
        self.evictions_to_ssd_total += 1
        self.io_time_ms += (time.perf_counter() - t0) * 1000.0

    def _load_tile_from_ssd(self, key: tuple[int, int]) -> _Tile:
        t0 = time.perf_counter()
        path = self._tile_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"SSD tile file missing for key {key}: {path}")
        tile = _Tile(ix=int(key[0]), iy=int(key[1]))
        try:
            with np.load(path, allow_pickle=False) as z:
                n_chunks = int(z["n_chunks"][0])
                for i in range(n_chunks):
                    kf_id = int(z[f"kf_{i}"][0])
                    pts = z[f"pts_{i}"].astype(np.float32)
                    col = z[f"col_{i}"].astype(np.uint8) if f"col_{i}" in z else None
                    tmp = z[f"tmp_{i}"].astype(np.float32) if f"tmp_{i}" in z else None
                    tile.chunks.append(_TileChunk(kf_id=kf_id, points_local=pts, colors=col, temperatures_c=tmp))
        except Exception as e:
            raise RuntimeError(f"Corrupt SSD tile archive at {path}: {e}") from e
        self.reloads_from_ssd_total += 1
        self.io_time_ms += (time.perf_counter() - t0) * 1000.0
        return tile

    def _get_or_create_tile(self, key: tuple[int, int]) -> _Tile:
        if key in self._ram_tiles:
            self.hits_total += 1
            self._ram_tiles.move_to_end(key)
            return self._ram_tiles[key]
        self.misses_total += 1
        if key in self._ssd_tile_keys:
            tile = self._load_tile_from_ssd(key)
            if tile.nbytes > self.max_ram_bytes:
                return tile  # too big to cache; served from SSD
            self._evict_lru_if_needed(tile.nbytes)
            self._ram_tiles[key] = tile
            self.active_ram_bytes += tile.nbytes
            self.peak_ram_bytes = max(self.peak_ram_bytes, self.active_ram_bytes)
            return tile
        tile = _Tile(ix=key[0], iy=key[1])
        self._ram_tiles[key] = tile
        return tile

    def insert_keyframe_points(
        self,
        kf_id: int,
        pose_w_b: np.ndarray,
        points_local: np.ndarray,
        colors: np.ndarray | None = None,
        temperatures_c: np.ndarray | None = None,
    ) -> None:
        """Insert a keyframe's static points into its spatial tile in immutable keyframe-local coordinates."""
        if len(points_local) == 0:
            return
        T = np.array(pose_w_b, dtype=np.float64, copy=True)
        self._poses[kf_id] = T
        ix = int(np.floor(T[0, 3] / self.tile_size_m))
        iy = int(np.floor(T[1, 3] / self.tile_size_m))
        key = (ix, iy)

        pts = np.ascontiguousarray(points_local, dtype=np.float32)
        col = np.ascontiguousarray(colors, dtype=np.uint8) if colors is not None else None
        tmp = np.ascontiguousarray(temperatures_c, dtype=np.float32) if temperatures_c is not None else None
        chunk = _TileChunk(kf_id=kf_id, points_local=pts, colors=col, temperatures_c=tmp)

        # Bring the *complete* tile in (RAM hit, SSD reload, or new); a tile is never split between RAM and SSD
        if key in self._ram_tiles:
            self.hits_total += 1
            self._ram_tiles.move_to_end(key)
            tile = self._ram_tiles.pop(key)
            self.active_ram_bytes -= tile.nbytes
        elif key in self._ssd_tile_keys:
            self.misses_total += 1
            tile = self._load_tile_from_ssd(key)
        else:
            self.misses_total += 1
            tile = _Tile(ix=key[0], iy=key[1])
        tile.chunks.append(chunk)

        if tile.nbytes > self.max_ram_bytes:
            # Tile alone exceeds the budget: keep it on SSD only (write-through)
            self._save_tile_to_ssd(key, tile)
            return
        self._evict_lru_if_needed(tile.nbytes)
        self._ram_tiles[key] = tile
        self.active_ram_bytes += tile.nbytes
        self.peak_ram_bytes = max(self.peak_ram_bytes, self.active_ram_bytes)

    def update_poses(self, poses_w_b: dict[int, np.ndarray]) -> None:
        """Update keyframe poses in O(K) RAM time with ZERO SSD I/O."""
        for kf_id, T in poses_w_b.items():
            self._poses[kf_id] = np.array(T, dtype=np.float64, copy=True)

    def export_world_cloud(
        self, voxel_size_m: float | None = 0.05, max_points: int = 10_000_000
    ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
        """Transform all tiles (RAM + SSD) using latest optimized keyframe poses into world coordinates."""
        all_keys = sorted(set(self._ram_tiles.keys()) | self._ssd_tile_keys)
        pts_list: list[np.ndarray] = []
        col_list: list[np.ndarray] = []
        tmp_list: list[np.ndarray] = []
        has_colors = False
        has_temps = False

        for key in all_keys:
            if key in self._ram_tiles:
                tile = self._ram_tiles[key]
                self.hits_total += 1
            else:
                self.misses_total += 1
                tile = self._load_tile_from_ssd(key)

            t_pts: list[np.ndarray] = []
            t_col: list[np.ndarray] = []
            t_tmp: list[np.ndarray] = []
            for ch in tile.chunks:
                T = self._poses.get(ch.kf_id)
                if T is None:
                    continue
                pw = (ch.points_local.astype(np.float64) @ T[:3, :3].T + T[:3, 3]).astype(np.float32)
                t_pts.append(pw)
                if ch.colors is not None:
                    has_colors = True
                    t_col.append(ch.colors)
                if ch.temperatures_c is not None:
                    has_temps = True
                    t_tmp.append(ch.temperatures_c)

            if not t_pts:
                continue
            cat_p = np.vstack(t_pts)
            cat_c = np.vstack(t_col) if (has_colors and len(t_col) == len(t_pts)) else None
            cat_t = np.concatenate(t_tmp) if (has_temps and len(t_tmp) == len(t_pts)) else None

            if voxel_size_m is not None and voxel_size_m > 0:
                idx = voxel_downsample(cat_p, voxel_size_m)
                cat_p = cat_p[idx]
                if cat_c is not None:
                    cat_c = cat_c[idx]
                if cat_t is not None:
                    cat_t = cat_t[idx]

            pts_list.append(cat_p)
            if cat_c is not None:
                col_list.append(cat_c)
            if cat_t is not None:
                tmp_list.append(cat_t)

        if not pts_list:
            return np.zeros((0, 3), dtype=np.float32), None, None

        full_p = np.vstack(pts_list)
        full_c = np.vstack(col_list) if (has_colors and len(col_list) == len(pts_list)) else None
        full_t = np.concatenate(tmp_list) if (has_temps and len(tmp_list) == len(pts_list)) else None

        if voxel_size_m is not None and voxel_size_m > 0 and len(full_p) > 0:
            idx = voxel_downsample(full_p, voxel_size_m, max_points=max_points)
            full_p = full_p[idx]
            if full_c is not None:
                full_c = full_c[idx]
            if full_t is not None:
                full_t = full_t[idx]

        return full_p, full_c, full_t

    def stats(self) -> dict:
        return {
            "max_ram_bytes": self.max_ram_bytes,
            "active_ram_bytes": self.active_ram_bytes,
            "peak_ram_bytes": self.peak_ram_bytes,
            "active_ram_tiles": len(self._ram_tiles),
            "ssd_spilled_tiles": len(self._ssd_tile_keys),
            "ssd_evictions_total": self.evictions_to_ssd_total,
            "ssd_reloads_total": self.reloads_from_ssd_total,
            "hits_total": self.hits_total,
            "misses_total": self.misses_total,
            "io_time_ms": round(self.io_time_ms, 2),
        }

"""Point-cloud container, PLY reader/writer, and geo helpers.

Internal convention for every analysed survey (after civil.align):
  * local metric frame, metres
  * x = east, y = north, z = up (ENU)
  * origin = (origin_lat, origin_lon) of the project
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

EARTH_R = 6_378_137.0


@dataclass
class Reconstruction:
    points: np.ndarray  # (N,3) float32
    colors: np.ndarray | None = None  # (N,3) uint8
    poses: np.ndarray | None = None  # (K,4,4) float64 camera-to-world
    times: np.ndarray | None = None  # (K,) seconds, one per pose
    labels: np.ndarray | None = None  # (N,) int32 class id from a decoder, -1 = none
    label_names: dict[int, str] = field(default_factory=dict)  # class id -> catalog code
    gps: np.ndarray | None = None  # (M,3) [t, lat, lon] optional GPS track
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.points = np.ascontiguousarray(self.points, dtype=np.float32)
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError("points must be (N,3)")
        if self.colors is not None:
            self.colors = np.ascontiguousarray(self.colors, dtype=np.uint8)
            if len(self.colors) != len(self.points):
                raise ValueError("colors length must match points")
        if self.labels is not None:
            self.labels = np.asarray(self.labels, dtype=np.int32)

    @property
    def n(self) -> int:
        return len(self.points)

    def trajectory(self) -> np.ndarray | None:
        """(K,3) camera centres, or None."""
        if self.poses is None or len(self.poses) == 0:
            return None
        return np.asarray(self.poses)[:, :3, 3]

    # ---- persistence -------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {"points": self.points}
        for name in ("colors", "poses", "times", "labels", "gps"):
            v = getattr(self, name)
            if v is not None:
                arrays[name] = v
        arrays["meta"] = np.frombuffer(
            json.dumps({"meta": self.meta, "label_names": {str(k): v for k, v in self.label_names.items()}}).encode(),
            dtype=np.uint8,
        )
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Reconstruction":
        with np.load(path, allow_pickle=False) as z:
            extra = json.loads(bytes(z["meta"]).decode()) if "meta" in z else {}
            return cls(
                points=z["points"],
                colors=z["colors"] if "colors" in z else None,
                poses=z["poses"] if "poses" in z else None,
                times=z["times"] if "times" in z else None,
                labels=z["labels"] if "labels" in z else None,
                gps=z["gps"] if "gps" in z else None,
                label_names={int(k): v for k, v in extra.get("label_names", {}).items()},
                meta=extra.get("meta", {}),
            )


# ---------------------------------------------------------------------------
# PLY
# ---------------------------------------------------------------------------
_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}

MAX_PLY_VERTICES = 200_000_000


def read_ply(path: Path) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """Read vertices from an ASCII or binary PLY. Returns (xyz, rgb|None, label|None).

    Only the vertex element is read; faces and other elements that come after it are ignored.
    """
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("not a PLY file")
        fmt = None
        n_vertex = None
        props: list[tuple[str, str]] = []
        current = None
        elements_before_vertex = False
        while True:
            line = f.readline()
            if not line:
                raise ValueError("PLY header not terminated")
            tok = line.decode("ascii", "replace").split()
            if not tok:
                continue
            if tok[0] == "format":
                fmt = tok[1]
            elif tok[0] == "element":
                current = tok[1]
                if current == "vertex":
                    n_vertex = int(tok[2])
                elif n_vertex is None:
                    elements_before_vertex = True
            elif tok[0] == "property" and current == "vertex":
                if tok[1] == "list":
                    raise ValueError("list properties on vertices are not supported")
                if tok[1] not in _PLY_TYPES:
                    raise ValueError(f"unsupported PLY type {tok[1]}")
                props.append((tok[2], _PLY_TYPES[tok[1]]))
            elif tok[0] == "end_header":
                break
        if n_vertex is None or not props:
            raise ValueError("PLY has no vertex element")
        if elements_before_vertex:
            raise ValueError("PLY with elements before 'vertex' is not supported")
        if n_vertex > MAX_PLY_VERTICES:
            raise ValueError("PLY too large")
        names = [p[0] for p in props]
        for need in ("x", "y", "z"):
            if need not in names:
                raise ValueError("PLY vertex needs x, y, z")
        if fmt == "ascii":
            data = np.loadtxt(f, max_rows=n_vertex, ndmin=2)
            cols = {name: data[:, i] for i, name in enumerate(names)}
        elif fmt in ("binary_little_endian", "binary_big_endian"):
            end = "<" if fmt == "binary_little_endian" else ">"
            dt = np.dtype([(n, end + t) for n, t in props])
            arr = np.fromfile(f, dtype=dt, count=n_vertex)
            if len(arr) != n_vertex:
                raise ValueError("PLY truncated")
            cols = {name: arr[name] for name in names}
        else:
            raise ValueError(f"unsupported PLY format {fmt}")
    xyz = np.stack([cols["x"], cols["y"], cols["z"]], axis=1).astype(np.float32)
    rgb = None
    for r, g, b in (("red", "green", "blue"), ("r", "g", "b")):
        if r in cols and g in cols and b in cols:
            c = np.stack([cols[r], cols[g], cols[b]], axis=1)
            if c.dtype.kind == "f" and c.size and c.max() <= 1.0:
                c = c * 255.0
            rgb = np.clip(c, 0, 255).astype(np.uint8)
            break
    label = None
    for name in ("label", "class", "semantic", "scalar_label"):
        if name in cols:
            label = cols[name].astype(np.int32)
            break
    return xyz, rgb, label


def write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray | None = None, label: np.ndarray | None = None,
              comments: list[str] | None = None, flags: dict[str, np.ndarray] | None = None) -> None:
    """Binary PLY. `flags` adds one uchar column per name (e.g. detector=0/1); `comments` go in the header."""
    n = len(xyz)
    flags = flags or {}
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if rgb is not None:
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    if label is not None:
        fields += [("label", "<i4")]
    fields += [(k, "u1") for k in flags]
    arr = np.empty(n, dtype=fields)
    arr["x"], arr["y"], arr["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    if rgb is not None:
        arr["red"], arr["green"], arr["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    if label is not None:
        arr["label"] = label
    for k, v in flags.items():
        arr[k] = v
    header = ["ply", "format binary_little_endian 1.0"]
    header += [f"comment {c}" for c in (comments or []) if "\n" not in c]
    header += [f"element vertex {n}", "property float x", "property float y", "property float z"]
    if rgb is not None:
        header += ["property uchar red", "property uchar green", "property uchar blue"]
    if label is not None:
        header.append("property int label")
    header += [f"property uchar {k}" for k in flags]
    header.append("end_header")
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode())
        arr.tofile(f)


# ---------------------------------------------------------------------------
# Poses / trajectories (text formats decoders commonly emit)
# ---------------------------------------------------------------------------
def read_poses(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """Read camera poses. Supports:

    * JSON: {"poses": [[16 numbers] or 4x4, ...], "times": [...]} or a bare list of 4x4
    * TUM text: "t tx ty tz qx qy qz qw" per line
    * KITTI text: 12 numbers per line (3x4 row-major)
    Returns (K,4,4) camera-to-world, times or None.
    """
    text = path.read_text()
    if path.suffix.lower() == ".json":
        obj = json.loads(text)
        raw = obj["poses"] if isinstance(obj, dict) else obj
        poses = np.array([np.asarray(p, dtype=np.float64).reshape(4, 4) for p in raw])
        times = np.asarray(obj["times"], dtype=np.float64) if isinstance(obj, dict) and "times" in obj else None
        return poses, times
    rows = [list(map(float, ln.split())) for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows:
        raise ValueError("empty pose file")
    width = len(rows[0])
    arr = np.array(rows)
    if width == 8:  # TUM
        t = arr[:, 0]
        poses = np.repeat(np.eye(4)[None], len(arr), axis=0)
        poses[:, :3, 3] = arr[:, 1:4]
        poses[:, :3, :3] = quat_to_rot(arr[:, 4:8])
        return poses, t
    if width == 12:  # KITTI
        poses = np.repeat(np.eye(4)[None], len(arr), axis=0)
        poses[:, :3, :4] = arr.reshape(-1, 3, 4)
        return poses, None
    if width == 16:
        return arr.reshape(-1, 4, 4), None
    raise ValueError(f"unrecognised pose file layout ({width} columns)")


def quat_to_rot(q: np.ndarray) -> np.ndarray:
    """(K,4) quaternions [qx,qy,qz,qw] -> (K,3,3)."""
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    x, y, z, w = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], axis=1)


def read_gps_csv(path: Path) -> np.ndarray:
    """CSV with header containing t/time, lat/latitude, lon/lng/longitude. Returns (M,3)."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    head = [h.strip().lower() for h in re.split(r"[,;\t]", lines[0])]

    def col(*names: str) -> int:
        for n in names:
            if n in head:
                return head.index(n)
        raise ValueError(f"GPS CSV needs one of {names}")

    it, ila, ilo = col("t", "time", "timestamp", "seconds"), col("lat", "latitude"), col("lon", "lng", "longitude")
    out = []
    for ln in lines[1:]:
        c = re.split(r"[,;\t]", ln)
        out.append((float(c[it]), float(c[ila]), float(c[ilo])))
    return np.array(out, dtype=np.float64)


# ---------------------------------------------------------------------------
# Geo
# ---------------------------------------------------------------------------
def enu_to_latlon(x: np.ndarray, y: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    lat = lat0 + np.degrees(np.asarray(y) / EARTH_R)
    lon = lon0 + np.degrees(np.asarray(x) / (EARTH_R * math.cos(math.radians(lat0))))
    return lat, lon


def latlon_to_enu(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    y = np.radians(np.asarray(lat) - lat0) * EARTH_R
    x = np.radians(np.asarray(lon) - lon0) * EARTH_R * math.cos(math.radians(lat0))
    return x, y


def voxel_downsample(xyz: np.ndarray, size: float, max_points: int | None = None) -> np.ndarray:
    """Indices of one point per voxel (first hit). Optionally cap by random subsampling."""
    if len(xyz) == 0:
        return np.zeros(0, dtype=np.int64)
    keys = np.floor(xyz / size).astype(np.int64)
    keys -= keys.min(axis=0)
    dims = keys.max(axis=0) + 1
    flat = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    _, idx = np.unique(flat, return_index=True)
    if max_points is not None and len(idx) > max_points:
        rng = np.random.default_rng(0)
        idx = np.sort(rng.choice(idx, max_points, replace=False))
    return idx

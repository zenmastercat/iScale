"""Streaming readers for the public datasets used to evaluate FORGE SLAM (data stays outside the repo).

* M2DGR (SJTU-ViSYS, MIT licence): ROS1 bag with Velodyne VLP-32C, Handsfree A9 IMU, RealSense D435i colour
  and a PLUG 617 thermal camera; ground truth from an RTK GNSS-INS (ECEF, TUM format).
* STheReO (SNU/KAIST RPM lab; no licence stated on the site, used for evaluation only): folder with Ouster
  OS1-128 scans, Xsens IMU, stereo RGB (Bayer) and stereo 14-bit FLIR A65 thermal, Novatel CPT-7 INS.

Each reader returns (calibration, time-ordered event iterator). Events are ImuSample / LidarScan / CameraFrame,
so they can be fed straight into pipeline.ForgeSlam. Images are undistorted on load when `undistort=True`
(the frame then carries zero distortion and the new camera matrix).
"""

from __future__ import annotations

import csv
import heapq
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from .types import CameraFrame, ImuSample, LidarScan, SensorCalibration

Event = ImuSample | LidarScan | CameraFrame


def _undistort(img: np.ndarray, K: np.ndarray, D: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    h, w = img.shape[:2]
    newK, _ = cv2.getOptimalNewCameraMatrix(K, D, (w, h), 0.0)
    out = cv2.undistort(img, K, D, None, newK)
    if scale != 1.0:
        out = cv2.resize(out, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        newK = newK.copy()
        newK[:2] *= scale
    return out, newK


# ---------------------------------------------------------------------------------------------- M2DGR
M2DGR_T_LIDAR_D435 = np.array([[0, 0, 1, 0.30456], [-1, 0, 0, 0.00065], [0, -1, 0, 0.65376], [0, 0, 0, 1]], float)
M2DGR_K_D435 = np.array([[617.971050917033, 0, 327.710279392468], [0, 616.445131524790, 253.976983707814], [0, 0, 1]])
M2DGR_D_D435 = np.array([0.148000794688248, -0.217835187249065, 0.0, 0.0])
M2DGR_T_LIDAR_THERMAL = np.array([[0, 0, 1, 0.30456], [-1, 0, 0, 0.17065], [0, -1, 0, 0.65376], [0, 0, 0, 1]], float)
M2DGR_K_THERMAL = np.array([[435.836180277211, 0, 324.452753232850], [0, 435.909430631362, 255.554320082190], [0, 0, 1]])
M2DGR_D_THERMAL = np.array([-0.436107594318055, 0.166413618922992, 0.0, 0.0])
M2DGR_HANDSFREE_IN_LIDAR = np.array([-0.27255, 0.00053, -0.17954])   # IMU position in the LiDAR frame
M2DGR_GNSS_IN_LIDAR = np.array([-0.09825, 0.00582, 0.72673])         # GNSS-INS antenna position in the LiDAR frame


def m2dgr_calibration() -> SensorCalibration:
    """Body = Handsfree IMU frame (axes parallel to the LiDAR's). T_lidar_imu maps LiDAR points into the body."""
    T_b_l = np.eye(4)
    T_b_l[:3, 3] = -M2DGR_HANDSFREE_IN_LIDAR
    return SensorCalibration(
        T_lidar_imu=T_b_l,
        gyr_noise=2.34e-3, acc_noise=3.77e-2, gyr_bias_walk=1.44e-5, acc_bias_walk=8.5e-4,
    )


def _ros_stamp(msg) -> float:
    st = msg.header.stamp
    return float(st.sec) + float(st.nanosec) * 1e-9


def _pointcloud2_xyz_time(msg) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """(N,3) xyz, (N,) intensity, (N,) per-point time offset [s] from a Velodyne PointCloud2."""
    np_types = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}
    names, formats, offsets = [], [], []
    for f in msg.fields:
        names.append(f.name)
        formats.append(np_types[f.datatype])
        offsets.append(f.offset)
    dt = np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": msg.point_step})
    arr = np.frombuffer(bytes(msg.data), dtype=dt, count=msg.width * msg.height)
    xyz = np.column_stack([arr["x"], arr["y"], arr["z"]]).astype(np.float32)
    ok = np.isfinite(xyz).all(1) & (np.linalg.norm(xyz, axis=1) > 0.5)
    inten = arr["intensity"].astype(np.float32)[ok] if "intensity" in names else None
    t = arr["time"].astype(np.float64)[ok] if "time" in names else None
    return xyz[ok], inten, t


def iter_m2dgr_bag(
    bag_path: Path,
    t_start: float | None = None,
    t_end: float | None = None,
    with_rgb: bool = True,
    with_thermal: bool = True,
    image_scale: float = 1.0,
) -> tuple[SensorCalibration, Iterator[Event]]:
    from rosbags.highlevel import AnyReader
    from rosbags.typesys import Stores, get_typestore

    calib = m2dgr_calibration()
    topics = {"/velodyne_points", "/handsfree/imu"}
    if with_rgb:
        topics.add("/camera/color/image_raw/compressed")
    if with_thermal:
        topics.add("/thermal_image_raw")

    def gen() -> Iterator[Event]:
        store = get_typestore(Stores.ROS1_NOETIC)
        with AnyReader([Path(bag_path)], default_typestore=store) as reader:
            conns = [c for c in reader.connections if c.topic in topics]
            lo = None if t_start is None else int(t_start * 1e9)
            hi = None if t_end is None else int(t_end * 1e9)
            for conn, _, raw in reader.messages(connections=conns, start=lo, stop=hi):
                msg = reader.deserialize(raw, conn.msgtype)
                t = _ros_stamp(msg)
                if conn.topic == "/handsfree/imu":
                    g, a = msg.angular_velocity, msg.linear_acceleration
                    yield ImuSample(t, np.array([g.x, g.y, g.z]), np.array([a.x, a.y, a.z]))
                elif conn.topic == "/velodyne_points":
                    xyz, inten, dt = _pointcloud2_xyz_time(msg)
                    # Velodyne 'time' is relative to the header stamp (scan start); stamp the scan at its end
                    if dt is not None and len(dt):
                        yield LidarScan(t + float(dt.max()), xyz, inten, t + dt)
                    else:
                        yield LidarScan(t, xyz, inten, None)
                elif conn.topic == "/camera/color/image_raw/compressed":
                    bgr = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
                    if bgr is None:
                        continue
                    img, K = _undistort(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), M2DGR_K_D435, M2DGR_D_D435, image_scale)
                    yield CameraFrame(t, img, K, np.zeros(5), _body_cam(calib, M2DGR_T_LIDAR_D435), "rgb")
                elif conn.topic == "/thermal_image_raw":
                    img = _ros_image_to_array(msg)
                    if img.ndim == 3:  # published as 8UC3 with three equal channels
                        img = np.ascontiguousarray(img[:, :, 0])
                    img, K = _undistort(img, M2DGR_K_THERMAL, M2DGR_D_THERMAL, image_scale)
                    # PLUG 617 output is not radiometric: kept as relative intensity (no °C)
                    yield CameraFrame(t, img, K, np.zeros(5), _body_cam(calib, M2DGR_T_LIDAR_THERMAL), "thermal",
                                      thermal_encoding="relative")

    return calib, gen()


def _ros_image_to_array(msg) -> np.ndarray:
    enc = msg.encoding.lower()
    dtype = {"mono8": np.uint8, "8uc1": np.uint8, "mono16": np.uint16, "16uc1": np.uint16, "bgr8": np.uint8, "rgb8": np.uint8,
             "8uc3": np.uint8}[enc]
    ch = 3 if enc in ("bgr8", "rgb8", "8uc3") else 1
    arr = np.frombuffer(bytes(msg.data), dtype=dtype)
    if msg.is_bigendian and arr.dtype.itemsize > 1:
        arr = arr.byteswap()
    arr = arr.reshape(msg.height, msg.step // (arr.dtype.itemsize * ch), ch)[:, : msg.width]
    return arr[:, :, 0] if ch == 1 else (cv2.cvtColor(arr, cv2.COLOR_BGR2RGB) if enc == "bgr8" else arr)


def _body_cam(calib: SensorCalibration, T_lidar_cam: np.ndarray) -> np.ndarray:
    """Camera pose in the body frame: T_body_cam = T_body_lidar @ T_lidar_cam."""
    return calib.T_lidar_imu @ T_lidar_cam


def ecef_to_enu(ecef: np.ndarray, origin_ecef: np.ndarray) -> np.ndarray:
    """ECEF -> local ENU at origin (WGS-84)."""
    x, y, z = origin_ecef
    a, e2 = 6378137.0, 6.69437999014e-3
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - e2))
    for _ in range(5):
        n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        lat = np.arctan2(z + e2 * n * np.sin(lat), p)
    sl, cl, so, co = np.sin(lat), np.cos(lat), np.sin(lon), np.cos(lon)
    R = np.array([[-so, co, 0], [-sl * co, -sl * so, cl], [cl * co, cl * so, sl]])
    return (np.asarray(ecef) - origin_ecef) @ R.T


def load_m2dgr_gt(gt_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(times [s], ENU positions of the GNSS-INS antenna [m]) from an M2DGR TUM-format ECEF ground truth."""
    d = np.loadtxt(gt_path)
    return d[:, 0], ecef_to_enu(d[:, 1:4], d[0, 1:4])


# --------------------------------------------------------------------------------------------- STheReO
def _read_matrix(path: Path) -> np.ndarray:
    txt = path.read_text().replace("[", " ").replace("]", " ")
    vals = np.array([float(v) for v in txt.split()])
    return vals.reshape(4, 4)


def _read_cv_yaml(path: Path) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Camera matrix, distortion and size from a ROS / OpenCV camera YAML (with or without the %YAML header)."""
    import yaml  # noqa: PLC0415 - only needed for this dataset

    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_constructor("tag:yaml.org,2002:opencv-matrix", lambda ld, node: ld.construct_mapping(node, deep=True))
    txt = "\n".join(ln for ln in path.read_text().splitlines() if not ln.startswith("%YAML"))
    y = yaml.load(txt, Loader=_Loader)
    K = np.array(y["camera_matrix"]["data"], float).reshape(3, 3)
    D = np.array(y["distortion_coefficients"]["data"], float)
    return K, D, (int(y["image_width"]), int(y["image_height"]))


def sthereo_calibration(seq_dir: Path) -> tuple[SensorCalibration, dict]:
    """Body = Xsens IMU frame. Conventions verified from axes (camera z must point forward):
    imu_2_thermal_left maps thermal -> IMU, lidar_2_thermal_left maps LiDAR -> thermal."""
    c = Path(seq_dir) / "calibration"
    T_imu_thr = _read_matrix(c / "extrinsic" / "imu_2_thermal_left")
    T_thr_lidar = _read_matrix(c / "extrinsic" / "lidar_2_thermal_left")
    T_imu_lidar = T_imu_thr @ T_thr_lidar
    T_thr_rgb = _read_matrix(c / "extrinsic" / "rgb_left_2_thermal_left")
    K_t, D_t, _ = _read_cv_yaml(c / "thermal_14bit_left.yaml")
    K_r, D_r, _ = _read_cv_yaml(c / "left.yaml")
    calib = SensorCalibration(T_lidar_imu=T_imu_lidar, gyr_noise=2e-3, acc_noise=2e-2, gyr_bias_walk=2e-5, acc_bias_walk=5e-4)
    cams = {"T_b_thr": T_imu_thr, "T_b_rgb": T_imu_thr @ T_thr_rgb, "K_t": K_t, "D_t": D_t, "K_r": K_r, "D_r": D_r}
    return calib, cams


def _stamp_files(folder: Path, suffix: str) -> list[tuple[float, Path]]:
    if not folder.is_dir():
        return []
    out = []
    for p in folder.glob(f"*{suffix}"):
        try:
            out.append((int(p.stem) * 1e-9, p))
        except ValueError:
            continue
    return sorted(out)


def iter_sthereo(
    seq_dir: Path,
    t_start: float | None = None,
    t_end: float | None = None,
    with_rgb: bool = True,
    with_thermal: bool = True,
    image_scale: float = 0.5,
    planck_params: dict | None = None,
) -> tuple[SensorCalibration, Iterator[Event]]:
    seq_dir = Path(seq_dir)
    calib, cams = sthereo_calibration(seq_dir)
    sd = seq_dir / "sensor_data"

    def in_range(t: float) -> bool:
        return (t_start is None or t >= t_start) and (t_end is None or t <= t_end)

    def imu_gen() -> Iterator[tuple[float, int, Event]]:
        with open(sd / "xsens_imu.csv", newline="") as fh:
            for row in csv.reader(fh):
                try:
                    v = [float(x) for x in row]
                except ValueError:
                    continue
                t = v[0] * 1e-9
                if in_range(t):  # [t, qx qy qz qw, roll pitch yaw, gx gy gz, ax ay az, mx my mz]
                    yield t, 0, ImuSample(t, np.array(v[8:11]), np.array(v[11:14]))

    def lidar_gen() -> Iterator[tuple[float, int, Event]]:
        for t, p in _stamp_files(sd / "ouster", ".bin"):
            if not in_range(t):
                continue
            a = np.fromfile(p, dtype=np.float32).reshape(-1, 4)
            ok = np.linalg.norm(a[:, :3], axis=1) > 1.0
            # The bin stamp is the acquisition time; per-point times are not provided -> no deskew
            yield t, 1, LidarScan(t, a[ok, :3].copy(), a[ok, 3].copy(), None)

    def cam_gen(folder: str, modality: str) -> Iterator[tuple[float, int, Event]]:
        for t, p in _stamp_files(seq_dir / "image" / folder, ".png"):
            if not in_range(t):
                continue
            img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            if modality == "rgb":
                img = cv2.cvtColor(img, cv2.COLOR_BayerBG2RGB) if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img, K = _undistort(img, cams["K_r"], cams["D_r"], image_scale)
                yield t, 2, CameraFrame(t, img, K, np.zeros(5), cams["T_b_rgb"], "rgb")
            else:
                img, K = _undistort(img.astype(np.float32), cams["K_t"], cams["D_t"], 1.0)
                yield t, 3, CameraFrame(t, img, K, np.zeros(5), cams["T_b_thr"], "thermal",
                                        thermal_encoding="flir_raw", planck_params=planck_params)

    streams = [imu_gen(), lidar_gen()]
    if with_rgb:
        streams.append(cam_gen("stereo_left", "rgb"))
    if with_thermal:
        streams.append(cam_gen("stereo_thermal_14_left", "thermal"))

    def gen() -> Iterator[Event]:
        for _, _, ev in heapq.merge(*streams, key=lambda e: (e[0], e[1])):
            yield ev

    return calib, gen()


def load_sthereo_reference(seq_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """(times [s], ENU positions [m]) of the Novatel CPT-7 INS solution (sensor_data/inspva.csv).

    This is an RTK/INS reference, not survey-grade ground truth."""
    rows = []
    with open(Path(seq_dir) / "sensor_data" / "inspva.csv", newline="") as fh:
        for row in csv.reader(fh):
            try:
                rows.append([float(row[0]), float(row[1]), float(row[2]), float(row[3])])
            except (ValueError, IndexError):
                continue
    d = np.array(rows)
    lat, lon, h = np.radians(d[:, 1]), np.radians(d[:, 2]), d[:, 3]
    a, e2 = 6378137.0, 6.69437999014e-3
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    ecef = np.column_stack([(n + h) * np.cos(lat) * np.cos(lon), (n + h) * np.cos(lat) * np.sin(lon), (n * (1 - e2) + h) * np.sin(lat)])
    return d[:, 0] * 1e-9, ecef_to_enu(ecef, ecef[0])

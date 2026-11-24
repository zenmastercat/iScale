"""Stage 7A: Multi-Sensor Sequence I/O, Pre-Flight Validation, and Synthetic Sequence Generator.

Supports:
1. Structured FORGE sequence directories (`calibration.json`, `imu.csv`, `lidar/scan_*.npy`,
   `rgb/frame_*.png|jpg`, `thermal/frame_*.tiff|png|npy`, optional `gps.csv`, `gt_poses.txt`).
2. Flat uploaded directories (where browser file uploads drop `calibration.json`, `imu.csv`,
   `scan_*.npy`, `rgb_*.png`, `thermal_*.tiff` into `survey_dir/input/`).
Recorded rosbags are not read here (topics and calibration differ per rig); see forge/datasets.py for the
M2DGR bag reader. Calibration keys (calibration.json): T_lidar_imu maps LiDAR points into the IMU/body frame,
T_lidar_rgb / T_lidar_thermal are the camera poses in that body frame; scan_timestamps are absolute seconds
on the IMU clock. A 5th LiDAR column holds per-point absolute times (or offsets within the scan, see below).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .. import images
from ..pointcloud import read_gps_csv
from .thermal_reg import DEFAULT_FLIR_PLANCK, celsius_to_flir_raw
from .types import CameraFrame, ImuSample, LidarScan, SensorCalibration


def _find_lidar_files(input_dir: Path) -> list[Path]:
    if (input_dir / "lidar").is_dir():
        files = sorted((input_dir / "lidar").glob("*.npy")) + sorted((input_dir / "lidar").glob("*.bin"))
        if files:
            return files
    return sorted(input_dir.glob("scan_*.npy")) + sorted(input_dir.glob("lidar_*.npy"))


def _find_rgb_files(input_dir: Path) -> list[Path]:
    if (input_dir / "rgb").is_dir():
        files = sorted((input_dir / "rgb").glob("*.png")) + sorted((input_dir / "rgb").glob("*.jpg"))
        if files:
            return files
    return sorted(input_dir.glob("rgb_*.png")) + sorted(input_dir.glob("rgb_*.jpg"))


def _find_thermal_files(input_dir: Path) -> list[Path]:
    if (input_dir / "thermal").is_dir():
        files = (
            sorted((input_dir / "thermal").glob("*.tiff"))
            + sorted((input_dir / "thermal").glob("*.tif"))
            + sorted((input_dir / "thermal").glob("*.png"))
            + sorted((input_dir / "thermal").glob("*.npy"))
        )
        if files:
            return files
    return (
        sorted(input_dir.glob("thermal_*.tiff"))
        + sorted(input_dir.glob("thermal_*.png"))
        + sorted(input_dir.glob("thermal_*.npy"))
    )


def _find_rosbag(input_dir: Path) -> Path | None:
    if input_dir.is_file() and input_dir.suffix.lower() in (".bag", ".mcap", ".db3"):
        return input_dir
    for ext in ("*.bag", "*.mcap", "*.db3"):
        found = sorted(input_dir.glob(ext))
        if found:
            return found[0]
    return None


# Per-file caps for survey inputs (a single upload may be up to 4 GB in total): every reader below loads a
# whole file into memory, so one oversized file must be refused before it is read.
MAX_FILE_BYTES = {
    "calibration": 1 << 20,    # calibration.json
    "table": 512 << 20,        # imu.csv, gps.csv, gt_poses.txt
    "scan": 256 << 20,         # one LiDAR scan (.npy / .bin): ~10 M points
    "image": 64 << 20,         # one RGB or thermal frame
}


def _input_problems(files: dict[str, list[Path]]) -> tuple[list[str], set[Path]]:
    """Size (and, for images, header pixel-count) problems of the given files, by kind; and the bad files."""
    out, bad = [], set()
    for kind, paths in files.items():
        for f in paths:
            if not f.is_file():
                continue
            size = f.stat().st_size
            if size > MAX_FILE_BYTES[kind]:
                out.append(f"{f.name} is too large ({size} bytes; limit {MAX_FILE_BYTES[kind]} for {kind} files)")
                bad.add(f)
            elif kind == "image" and f.suffix.lower() != ".npy":
                try:
                    images.check_pixels(f)
                except ValueError as e:
                    out.append(f"{f.name}: {e}")
                    bad.add(f)
    return out, bad


def preflight_check(input_path: Path) -> dict:
    """Validate that a multi-sensor directory or bag has calibrated LiDAR, IMU, RGB, and radiometric thermal."""
    input_path = Path(input_path)
    issues: list[str] = []
    if not input_path.exists():
        return {"ok": False, "issues": [f"path does not exist: {input_path}"], "streams": {}, "radiometric_thermal": False}

    bag = _find_rosbag(input_path)
    cal_file = input_path / "calibration.json" if input_path.is_dir() else input_path.parent / "calibration.json"
    imu_file = input_path / "imu.csv" if input_path.is_dir() else None
    lidar_files = _find_lidar_files(input_path) if input_path.is_dir() else []
    rgb_files = _find_rgb_files(input_path) if input_path.is_dir() else []
    thermal_files = _find_thermal_files(input_path) if input_path.is_dir() else []

    tables = [input_path / n for n in ("gps.csv", "gt_poses.txt")] if input_path.is_dir() else []
    size_issues, bad = _input_problems({
        "calibration": [cal_file], "table": ([imu_file] if imu_file else []) + tables,
        "scan": lidar_files, "image": rgb_files + thermal_files,
    })
    issues += size_issues

    cal_data = {}
    if cal_file.is_file() and cal_file not in bad:
        try:
            cal_data = json.loads(cal_file.read_text())
        except Exception as e:  # noqa: BLE001
            issues.append(f"invalid calibration.json: {e}")
    else:
        issues.append("missing calibration.json")

    if bag is not None and not lidar_files:
        issues.append(f"rosbag input ({bag.name}) is not supported by this decoder; export scans, imu.csv and calibration.json")
    if not (imu_file and imu_file.is_file()):
        issues.append("missing imu.csv")
    if len(lidar_files) < 2:
        issues.append(f"need at least 2 LiDAR scans, found {len(lidar_files)}")
    elif cal_data and len(cal_data.get("scan_timestamps") or []) != len(lidar_files):
        issues.append("calibration.json needs scan_timestamps (one per LiDAR scan, IMU clock)")
    for files, keys in ((rgb_files, ("K_rgb", "T_lidar_rgb")), (thermal_files, ("K_thermal", "T_lidar_thermal"))):
        missing = [k for k in keys if files and cal_data.get(k) is None]
        if missing and cal_data:
            issues.append(f"camera frames present but calibration.json lacks {', '.join(missing)}")

    thermal_enc = cal_data.get("thermal_encoding", "flir_raw")
    radiometric_ok = thermal_enc in ("flir_raw", "centikelvin", "celsius_f32")
    if thermal_files and thermal_files[0] not in bad:
        t0 = thermal_files[0]
        img = np.load(t0) if t0.suffix == ".npy" else cv2.imread(str(t0), cv2.IMREAD_UNCHANGED)
        if img is None:
            issues.append(f"could not read thermal image {t0.name}")
        elif img.dtype == np.uint8 and cal_data.get("linear_range") is None:
            radiometric_ok = False
            issues.append("8-bit thermal image without linear_range=(temp_min_c, temp_max_c) in calibration.json")
        else:
            radiometric_ok = True

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "radiometric_thermal": radiometric_ok,
        "thermal_encoding": thermal_enc,
        "has_rosbag": bag is not None,
        "streams": {
            "lidar_scans": len(lidar_files),
            "rgb_frames": len(rgb_files),
            "thermal_frames": len(thermal_files),
            "has_imu": bool(imu_file and imu_file.is_file()),
            "has_gps": bool(input_path.is_dir() and (input_path / "gps.csv").is_file()),
        },
    }


def _parse_calibration(cal_data: dict) -> SensorCalibration:
    def _mat(key: str, default: np.ndarray | None) -> np.ndarray | None:
        if key not in cal_data or cal_data[key] is None:
            return default
        return np.asarray(cal_data[key], dtype=np.float64)

    lr = cal_data.get("linear_range")
    return SensorCalibration(
        T_lidar_imu=_mat("T_lidar_imu", np.eye(4, dtype=np.float64)),
        T_lidar_rgb=_mat("T_lidar_rgb", np.eye(4, dtype=np.float64)),
        T_lidar_thermal=_mat("T_lidar_thermal", np.eye(4, dtype=np.float64)),
        K_rgb=_mat("K_rgb", np.array([[120.0, 0.0, 80.0], [0.0, 120.0, 60.0], [0.0, 0.0, 1.0]])),
        D_rgb=_mat("D_rgb", np.zeros(4, dtype=np.float64)),
        K_thermal=_mat("K_thermal", np.array([[120.0, 0.0, 80.0], [0.0, 120.0, 60.0], [0.0, 0.0, 1.0]])),
        D_thermal=_mat("D_thermal", np.zeros(4, dtype=np.float64)),
        time_offset_imu_s=float(cal_data.get("time_offset_imu_s", 0.0)),
        time_offset_rgb_s=float(cal_data.get("time_offset_rgb_s", 0.0)),
        time_offset_thermal_s=float(cal_data.get("time_offset_thermal_s", 0.0)),
        thermal_encoding=str(cal_data.get("thermal_encoding", "flir_raw")),
        planck_params=dict(cal_data.get("planck_params") or DEFAULT_FLIR_PLANCK),
        linear_range=(float(lr[0]), float(lr[1])) if lr and len(lr) == 2 else None,
        gyr_noise=float(cal_data.get("gyr_noise", 2.4e-3)),
        acc_noise=float(cal_data.get("acc_noise", 2.5e-2)),
        gyr_bias_walk=float(cal_data.get("gyr_bias_walk", 2.0e-5)),
        acc_bias_walk=float(cal_data.get("acc_bias_walk", 8.0e-4)),
    )


def load_forge_sequence(
    input_dir: Path,
) -> tuple[
    SensorCalibration,
    list[ImuSample],
    list[LidarScan],
    list[CameraFrame],
    list[CameraFrame],
    np.ndarray | None,
    np.ndarray | None,
]:
    """Load calibrated multi-sensor FORGE sequence from directory."""
    input_dir = Path(input_dir)
    pf = preflight_check(input_dir)
    if not pf["ok"]:
        raise ValueError(f"FORGE preflight failed: {'; '.join(pf['issues'])}")

    cal_data = json.loads((input_dir / "calibration.json").read_text())
    calib = _parse_calibration(cal_data)
    scan_times = cal_data.get("scan_timestamps")

    # Load IMU samples
    imu_samples: list[ImuSample] = []
    with open(input_dir / "imu.csv", "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or row[0].strip().startswith("#") or row[0].strip().isalpha():
                continue
            vals = [float(x) for x in row[:7]]
            imu_samples.append(
                ImuSample(
                    t=vals[0] + calib.time_offset_imu_s,
                    gyro=np.array(vals[1:4], dtype=np.float64),
                    accel=np.array(vals[4:7], dtype=np.float64),
                )
            )

    # Load LiDAR scans
    lidar_files = _find_lidar_files(input_dir)
    lidar_scans: list[LidarScan] = []
    for i, lf in enumerate(lidar_files):
        raw = np.load(lf) if lf.suffix == ".npy" else np.fromfile(lf, dtype=np.float32).reshape(-1, 4)
        pts = raw[:, :3].astype(np.float32)
        intens = raw[:, 3].astype(np.float32) if raw.shape[1] >= 4 else None
        t_scan = float(scan_times[i]) if scan_times and i < len(scan_times) else float(i) * 0.5
        pt_times = raw[:, 4].astype(np.float64) if raw.shape[1] >= 5 else None
        if pt_times is not None and len(pt_times) and pt_times.max() < 1.0 < t_scan:
            pt_times = t_scan - pt_times.max() + pt_times  # offsets within the scan; the scan stamp is its end
        lidar_scans.append(LidarScan(t=t_scan, points=pts, intensities=intens, point_times=pt_times))

    # Load RGB frames
    rgb_files = _find_rgb_files(input_dir)
    rgb_frames: list[CameraFrame] = []
    for i, rf in enumerate(rgb_files):
        bgr = cv2.imread(str(rf), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        t_cam = (
            float(scan_times[min(i, len(scan_times) - 1)])
            if scan_times
            else (lidar_scans[min(i, len(lidar_scans) - 1)].t if lidar_scans else float(i) * 0.5)
        ) + calib.time_offset_rgb_s
        rgb_frames.append(
            CameraFrame(
                t=t_cam,
                image=rgb,
                intrinsics=calib.K_rgb,
                distortion=calib.D_rgb,
                T_lidar_cam=calib.T_lidar_rgb,
                modality="rgb",
            )
        )

    # Load radiometric thermal frames
    thr_files = _find_thermal_files(input_dir)
    thr_frames: list[CameraFrame] = []
    for i, tf in enumerate(thr_files):
        t_img = np.load(tf) if tf.suffix == ".npy" else cv2.imread(str(tf), cv2.IMREAD_UNCHANGED)
        if t_img is None:
            continue
        if t_img.ndim == 3:
            t_img = t_img[:, :, 0]
        t_cam = (
            float(scan_times[min(i, len(scan_times) - 1)])
            if scan_times
            else (lidar_scans[min(i, len(lidar_scans) - 1)].t if lidar_scans else float(i) * 0.5)
        ) + calib.time_offset_thermal_s
        thr_frames.append(
            CameraFrame(
                t=t_cam,
                image=t_img,
                intrinsics=calib.K_thermal,
                distortion=calib.D_thermal,
                T_lidar_cam=calib.T_lidar_thermal,
                modality="thermal",
                thermal_encoding=calib.thermal_encoding,
                planck_params=calib.planck_params,
                linear_range=calib.linear_range,
            )
        )

    gps = read_gps_csv(input_dir / "gps.csv") if (input_dir / "gps.csv").is_file() else None
    gt_poses = None
    if (input_dir / "gt_poses.txt").is_file():
        gt_poses = np.loadtxt(input_dir / "gt_poses.txt", dtype=np.float64)
        if gt_poses.ndim == 1:
            gt_poses = gt_poses[None, :]

    return calib, imu_samples, lidar_scans, rgb_frames, thr_frames, gps, gt_poses


def create_synthetic_forge_dataset(
    out_dir: Path,
    n_keyframes: int = 10,
    with_pothole: bool = True,
    with_loop: bool = True,
    with_dynamic: bool = True,
) -> Path:
    """Create a complete calibrated multi-sensor FORGE dataset directory on disk.

    Includes:
    - Road corridor (`z = 0.0 m`) with curb walls (`y = +-3.8 m`) for crisp 3D point-to-plane constraints
    - A 6.5 cm deep, 0.95 m diameter road pothole at `(x = 6.0 m, y = 0.0 m)` with a +4.8 °C thermal anomaly
    - Moving vehicle dynamic ghost cluster at `z in [0.4, 1.5] m`
    - 200 Hz IMU (`imu.csv`), 3D LiDAR scans (`lidar/scan_*.npy`), RGB frames (`rgb/frame_*.png`),
      and 16-bit FLIR Planck-law radiometric thermal frames (`thermal/frame_*.tiff`).
    """
    out_dir = Path(out_dir)
    (out_dir / "lidar").mkdir(parents=True, exist_ok=True)
    (out_dir / "rgb").mkdir(parents=True, exist_ok=True)
    (out_dir / "thermal").mkdir(parents=True, exist_ok=True)

    # Build world static road + curb walls + structural pillars
    gx, gy = np.meshgrid(np.linspace(-2.0, 16.0, 140), np.linspace(-3.5, 3.5, 65))
    road_x = gx.ravel()
    road_y = gy.ravel()
    road_z = np.zeros_like(road_x)

    if with_pothole:
        r2 = (road_x - 6.0) ** 2 + (road_y - 0.0) ** 2
        pothole_mask = r2 < (0.48 ** 2)
        road_z[pothole_mask] = -0.065 * np.cos(np.pi * np.sqrt(r2[pothole_mask]) / (2.0 * 0.48)) ** 2

    road_pts = np.column_stack([road_x, road_y, road_z])

    # Side curb walls for horizontal constraint
    wx, wz = np.meshgrid(np.linspace(-2.0, 16.0, 90), np.linspace(0.0, 1.8, 12))
    wall_l = np.column_stack([wx.ravel(), np.full(wx.size, -3.6), wz.ravel()])
    wall_r = np.column_stack([wx.ravel(), np.full(wx.size, 3.6), wz.ravel()])
    # End wall at x = 16.0
    ey, ez = np.meshgrid(np.linspace(-3.6, 3.6, 40), np.linspace(0.0, 1.8, 12))
    wall_end = np.column_stack([np.full(ey.size, 16.0), ey.ravel(), ez.ravel()])

    world_static = np.vstack([road_pts, wall_l, wall_r, wall_end]).astype(np.float64)

    # Trajectory timestamps and poses (forward along X, and if with_loop return near origin on last frame)
    dt_scan = 0.5
    scan_times = [round(i * dt_scan, 4) for i in range(n_keyframes)]
    xs = np.linspace(0.0, 8.0, n_keyframes)
    if with_loop and n_keyframes >= 6:
        half = n_keyframes - 1
        xs = np.concatenate([np.linspace(0.0, 8.0, half), [0.15]])

    poses_wb: list[np.ndarray] = []
    gt_rows: list[list[float]] = []
    for i, t_s in enumerate(scan_times):
        T = np.eye(4, dtype=np.float64)
        T[:3, 3] = [float(xs[i]), 0.0, 0.0]
        poses_wb.append(T)
        q = Rotation.from_matrix(T[:3, :3]).as_quat()  # x, y, z, w
        gt_rows.append([t_s, T[0, 3], T[1, 3], T[2, 3], q[0], q[1], q[2], q[3]])

    np.savetxt(out_dir / "gt_poses.txt", np.asarray(gt_rows, dtype=np.float64), fmt="%.6f")

    # Generate 200 Hz IMU stream consistent with piecewise constant velocity between keyframes
    imu_dt = 0.005
    t_end = scan_times[-1] + 0.05
    n_imu = int(np.round(t_end / imu_dt)) + 1
    with open(out_dir / "imu.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t", "gx", "gy", "gz", "ax", "ay", "az"])
        for k in range(n_imu):
            t_imu = round(k * imu_dt, 5)
            w.writerow([t_imu, 0.0, 0.0, 0.0, 0.0, 0.0, 9.80665])

    # Camera calibration looking forward-down at the road (+X_w forward, -Z_w down)
    R_lc = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)
    T_lc = np.eye(4, dtype=np.float64)
    T_lc[:3, :3] = R_lc
    T_lc[:3, 3] = [0.0, 0.0, 1.5]
    H, W = 120, 160
    K = np.array([[110.0, 0.0, 80.0], [0.0, 110.0, 60.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    D = np.zeros(4, dtype=np.float64)

    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    dy_c = (yy - 60.0) / 110.0
    dx_c = (xx - 80.0) / 110.0
    valid_ground = dy_c > 0.05
    s_depth = np.where(valid_ground, 1.5 / np.maximum(dy_c, 0.05), 12.0)

    for i, (t_s, T_wb) in enumerate(zip(scan_times, poses_wb)):
        T_bw = np.linalg.inv(T_wb)
        pts_b = (world_static @ T_bw[:3, :3].T) + T_bw[:3, 3]
        # Keep points within 18 m of sensor
        in_range = np.linalg.norm(pts_b[:, :2], axis=1) < 18.0
        pts_b = pts_b[in_range]

        if with_dynamic and i < n_keyframes - 1:
            # Add transient moving vehicle cluster at x_w = 3.0 + i * 1.1, y_w = 1.0, z_w in [0.45, 1.35]
            vx, vy, vz = np.meshgrid(
                np.linspace(3.0 + i * 1.1, 3.8 + i * 1.1, 5),
                np.linspace(0.7, 1.3, 4),
                np.linspace(0.45, 1.35, 5),
            )
            veh_w = np.column_stack([vx.ravel(), vy.ravel(), vz.ravel()])
            veh_b = (veh_w @ T_bw[:3, :3].T) + T_bw[:3, 3]
            pts_b = np.vstack([pts_b, veh_b])

        np.save(out_dir / "lidar" / f"scan_{i:04d}.npy", pts_b.astype(np.float32))

        # Render synchronized RGB and 16-bit FLIR Planck raw thermal frame
        xw_pix = T_wb[0, 3] + s_depth
        yw_pix = T_wb[1, 3] - s_depth * dx_c
        r2_pix = (xw_pix - 6.0) ** 2 + (yw_pix - 0.0) ** 2
        temp_c = np.where(
            valid_ground,
            27.5 + (4.8 * np.exp(-r2_pix / 0.35) if with_pothole else 0.0),
            21.0,
        ).astype(np.float32)

        rgb_img = np.full((H, W, 3), 128, dtype=np.uint8)
        rgb_img[..., 0] = np.clip(115.0 + (temp_c - 27.5) * 22.0, 40, 245).astype(np.uint8)
        rgb_img[..., 1] = np.where(r2_pix < 0.25, 85, 128).astype(np.uint8)
        rgb_img[..., 2] = np.where(r2_pix < 0.25, 75, 128).astype(np.uint8)

        cv2.imwrite(str(out_dir / "rgb" / f"frame_{i:04d}.png"), cv2.cvtColor(rgb_img, cv2.COLOR_RGB2BGR))
        raw16 = celsius_to_flir_raw(temp_c)
        cv2.imwrite(str(out_dir / "thermal" / f"frame_{i:04d}.tiff"), raw16)

    cal_json = {
        "T_lidar_imu": np.eye(4).tolist(),
        "T_lidar_rgb": T_lc.tolist(),
        "T_lidar_thermal": T_lc.tolist(),
        "K_rgb": K.tolist(),
        "D_rgb": D.tolist(),
        "K_thermal": K.tolist(),
        "D_thermal": D.tolist(),
        "thermal_encoding": "flir_raw",
        "planck_params": DEFAULT_FLIR_PLANCK,
        "scan_timestamps": scan_times,
    }
    (out_dir / "calibration.json").write_text(json.dumps(cal_json, indent=2))
    return out_dir

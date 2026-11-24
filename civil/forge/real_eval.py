"""Evaluation of FORGE SLAM on recorded public sensor data (M2DGR rosbag, STheReO folder).

Every number written here comes from running the pipeline on the recorded streams and comparing against the
dataset's reference trajectory. Nothing is simulated. Metrics:

* ATE (RMSE of position after a rigid SE(3) Umeyama fit, no scale) and RPE (translation drift over 10 m segments)
  for the LIO-only per-scan trajectory and for full FORGE (keyframes re-anchored on the optimised pose graph).
* Loop closures: an accepted constraint is correct when its translation length matches the reference distance
  between the two keyframe times within 0.5 m. Recall counts keyframes that revisit (reference distance < 3 m to
  a keyframe at least loop_min_time_s / loop_min_dist_m earlier) and got a correct loop.
* Dynamic filter: points removed, their height above the local road, and road-surface erosion.
* Tile memory: run with a low RAM cap; the map must equal the uncapped map.
* Camera registration: LiDAR depth edges projected into the image vs image edges (median pixel distance),
  compared with the same with the extrinsic rotated by 2 degrees and with random image points.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from ..align import umeyama
from .eskf_lio import so3_exp
from .pipeline import ForgeSlam
from .thermal_reg import _project_and_zbuffer, interpolate_pose
from .types import CameraFrame, ForgeConfig, ImuSample, LidarScan


def run_stream(calib, events, work_dir: Path, cfg: ForgeConfig, keep_thermal_frames: bool = False):
    """Feed an event stream into ForgeSlam. Returns (slam, result, extra_thermal_frames, seconds)."""
    slam = ForgeSlam(calib, work_dir, cfg)
    extra_thr: list[CameraFrame] = []
    t0 = time.perf_counter()
    for ev in events:
        if isinstance(ev, ImuSample):
            slam.add_imu(ev)
        elif isinstance(ev, LidarScan):
            slam.add_scan(ev)
        elif ev.modality == "thermal" and keep_thermal_frames:
            if not extra_thr or ev.t - extra_thr[-1].t >= cfg.camera_min_interval_s:
                extra_thr.append(ev)
        else:
            slam.add_camera(ev)
    lio_t = np.array(slam._traj_t)
    lio_T = np.array(slam._traj_T)
    res = slam.finish()
    return slam, res, (lio_t, lio_T), extra_thr, time.perf_counter() - t0


# ------------------------------------------------------------------------------------------ trajectories
def associate(t_est: np.ndarray, t_ref: np.ndarray, p_ref: np.ndarray, max_dt: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Reference positions linearly interpolated at estimate times (only where both sides are within max_dt)."""
    j = np.clip(np.searchsorted(t_ref, t_est), 1, len(t_ref) - 1)
    t0, t1 = t_ref[j - 1], t_ref[j]
    ok = (t_est >= t_ref[0]) & (t_est <= t_ref[-1]) & (np.minimum(t_est - t0, t1 - t_est) <= max_dt)
    a = ((t_est - t0) / np.maximum(t1 - t0, 1e-9))[:, None]
    return ok, (1 - a) * p_ref[j - 1] + a * p_ref[j]


def ate_rpe(t_est: np.ndarray, p_est: np.ndarray, t_ref: np.ndarray, p_ref: np.ndarray, seg_m: float = 10.0) -> dict:
    ok, ref = associate(t_est, t_ref, p_ref)
    est, ref = p_est[ok], ref[ok]
    _, R, t = umeyama(est, ref, with_scale=False)
    aligned = est @ R.T + t
    err = np.linalg.norm(aligned - ref, axis=1)
    # RPE: for each start, the first sample >= seg_m further along the reference path
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(ref, axis=0), axis=1))])
    rpe = []
    for i in range(len(ref)):
        k = int(np.searchsorted(s, s[i] + seg_m))
        if k >= len(ref):
            break
        rpe.append(np.linalg.norm((aligned[k] - aligned[i]) - (ref[k] - ref[i])))
    rpe = np.array(rpe) if rpe else np.array([np.nan])
    return {
        "samples": int(ok.sum()),
        "path_length_m": round(float(s[-1]), 1),
        "ate_rmse_m": round(float(np.sqrt(np.mean(err ** 2))), 3),
        "ate_median_m": round(float(np.median(err)), 3),
        "ate_max_m": round(float(err.max()), 3),
        f"rpe_{int(seg_m)}m_rmse_m": round(float(np.sqrt(np.nanmean(rpe ** 2))), 3),
        f"rpe_{int(seg_m)}m_pct": round(float(np.sqrt(np.nanmean(rpe ** 2)) / seg_m * 100.0), 2),
        "_aligned": aligned, "_ref": ref, "_err": err, "_t": t_est[ok],
    }


def point_in_body(T: np.ndarray, p_b: np.ndarray) -> np.ndarray:
    return T[:, :3, :3] @ p_b + T[:, :3, 3]


# ------------------------------------------------------------------------------------------ loops
def loop_precision_recall(slam: ForgeSlam, t_ref: np.ndarray, p_ref: np.ndarray, revisit_m: float = 3.0) -> dict:
    cfg = slam.cfg
    kfs = slam.keyframes
    t_kf = np.array([k.t for k in kfs])
    ok, ref = associate(t_kf, t_ref, p_ref, max_dt=0.2)
    tp = []
    for lc in slam.loop_constraints:
        i, j = lc.from_id, lc.to_id
        if not (ok[i] and ok[j]):
            continue
        d_ref = float(np.linalg.norm(ref[j] - ref[i]))
        tp.append(abs(float(np.linalg.norm(lc.T_from_to[:3, 3])) - d_ref) < 0.5)
    # revisit queries from the reference
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(ref, axis=0), axis=1))])
    revisit = []
    for j in range(len(kfs)):
        if not ok[j]:
            continue
        prev = np.flatnonzero(ok[:j] & (t_kf[j] - t_kf[:j] >= cfg.loop_min_time_s) & (s[j] - s[:j] >= cfg.loop_min_dist_m))
        if len(prev) and np.min(np.linalg.norm(ref[prev] - ref[j], axis=1)) < revisit_m:
            revisit.append(j)
    correct_q = {lc.to_id for lc, good in zip(slam.loop_constraints, tp) if good}
    found = sum(1 for j in revisit if j in correct_q)
    return {
        "accepted": len(slam.loop_constraints),
        "correct": int(sum(tp)),
        "precision": round(sum(tp) / len(tp), 3) if tp else None,
        "revisit_keyframes": len(revisit),
        "revisits_closed": found,
        "recall": round(found / len(revisit), 3) if revisit else None,
        "rejections": slam.loops.summary()["rejected_by_reason"],
    }


# ------------------------------------------------------------------------------------------ camera edges
_DEPTH_BINS = (0.0, 4.0, 8.0, 16.0, 32.0, 1e9)


def _depth_edge_points(u: np.ndarray, v: np.ndarray, z: np.ndarray, H: int, W: int, fx: float,
                       spacing_m: float, jump_m: float = 1.0) -> np.ndarray:
    """Mask of visible points on the near side of a depth jump.

    Map points are sparse, so each one fills its own footprint (fx * spacing / z pixels, per depth bin) in a
    dense nearest-depth image; far points that would leak through the gaps of a nearer surface are hidden.
    """
    ui, vi = u.astype(int), v.astype(int)
    dense = np.full((H, W), np.inf, np.float32)
    bins = np.digitize(z, _DEPTH_BINS) - 1
    radius = {}
    for b in np.unique(bins):
        m = bins == b
        r = int(np.clip(math.ceil(fx * spacing_m / max(_DEPTH_BINS[b], 1.0) / 2), 1, 12))
        radius[b] = r
        layer = np.full((H, W), np.inf, np.float32)
        np.minimum.at(layer, (vi[m], ui[m]), z[m].astype(np.float32))
        dense = np.minimum(dense, cv2.erode(layer, np.ones((2 * r + 1, 2 * r + 1), np.uint8)))
    visible = z <= dense[vi, ui] + np.maximum(0.2, 0.1 * z)
    far = np.where(np.isfinite(dense), dense, 0).astype(np.float32)
    edge = np.zeros(len(z), bool)
    for b, r in radius.items():
        m = bins == b
        k = 2 * (r + 2) + 1
        edge[m] = cv2.dilate(far, np.ones((k, k), np.uint8))[vi[m], ui[m]] > z[m] + jump_m
    return visible & edge


def edge_alignment(points_w: np.ndarray, frames: list[CameraFrame], traj, n_frames: int = 12,
                   perturb_deg: float = 2.0, time_offsets: tuple[float, ...] = (0.0,), spacing_m: float = 0.1) -> dict:
    """Median pixel distance from projected LiDAR depth edges to image edges (Canny) over sampled frames.

    The control rotates the camera by perturb_deg about the in-image diagonal axis, so every edge moves."""
    if not frames:
        return {}
    rng = np.random.default_rng(0)
    pick = np.linspace(0, len(frames) - 1, min(n_frames, len(frames))).astype(int)
    R_p = np.eye(4)
    R_p[:3, :3] = so3_exp(np.radians(perturb_deg) * np.array([1.0, 1.0, 0.0]) / math.sqrt(2))

    def frame_err(f: CameraFrame, T_wc: np.ndarray) -> tuple[float, int]:
        img = f.image.astype(np.float32)
        if img.ndim == 3:
            img = img.mean(axis=2)
        lo, hi = np.percentile(img, [1, 99])
        g = np.clip((img - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
        edges = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 30, 90)
        ey, ex = np.nonzero(edges)
        if len(ex) < 50:
            return float("nan"), 0
        H, W = g.shape
        idx, u, v, z = _project_and_zbuffer(points_w, T_wc, f.intrinsics, H, W)
        if len(idx) < 200:
            return float("nan"), 0
        sel = _depth_edge_points(u, v, z, H, W, float(f.intrinsics[0, 0]), spacing_m) & (z < 40)
        if sel.sum() < 30:
            return float("nan"), 0
        d, _ = cKDTree(np.column_stack([ex, ey])).query(np.column_stack([u[sel], v[sel]]))
        return float(np.median(d)), int(sel.sum())

    out = {}
    for off in time_offsets:
        errs, errs_p, n = [], [], 0
        for i in pick:
            f = frames[i]
            T_wc = interpolate_pose(traj[0], traj[1], f.t + off) @ f.T_lidar_cam
            e, k = frame_err(f, T_wc)
            ep, _ = frame_err(f, T_wc @ R_p)
            if np.isfinite(e):
                errs.append(e)
                errs_p.append(ep)
                n += k
        out[f"{off:+.3f}s"] = {
            "median_px": round(float(np.nanmedian(errs)), 2) if errs else None,
            "median_px_extrinsic_rotated_2deg": round(float(np.nanmedian(errs_p)), 2) if errs_p else None,
            "frames": len(errs),
            "edge_points": n,
        }
    # chance level: random pixels to nearest image edge
    f = frames[pick[0]]
    img = f.image.astype(np.float32).mean(axis=2) if f.image.ndim == 3 else f.image.astype(np.float32)
    lo, hi = np.percentile(img, [1, 99])
    g = np.clip((img - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    ey, ex = np.nonzero(cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 30, 90))
    if len(ex):
        rnd = rng.uniform([0, 0], [g.shape[1], g.shape[0]], (2000, 2))
        out["random_pixels_median_px"] = round(float(np.median(cKDTree(np.column_stack([ex, ey])).query(rnd)[0])), 2)
    return out


# ------------------------------------------------------------------------------------------ dynamic filter
def dynamic_summary(slam: ForgeSlam) -> dict:
    st = slam.dyn_stats
    return {**st, "removed_pct": round(100.0 * st["removed_dynamic_points"] / max(st["input_points"], 1), 3)}


def same_points(a: np.ndarray, b: np.ndarray, tol_m: float = 1e-6) -> bool:
    """Same point set, order ignored: every point has a partner within tol_m, both ways."""
    if len(a) != len(b):
        return False
    if not len(a):
        return True
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return bool(cKDTree(b).query(a, distance_upper_bound=2 * tol_m)[0].max() <= tol_m
                and cKDTree(a).query(b, distance_upper_bound=2 * tol_m)[0].max() <= tol_m)


def save_json(obj, path: Path) -> None:
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if not str(k).startswith("_")}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        return o

    Path(path).write_text(json.dumps(clean(obj), indent=2))


def evaluate_dataset(
    name: str,
    make_stream,
    t_ref: np.ndarray,
    p_ref: np.ndarray,
    ref_point_b: np.ndarray,
    out_dir: Path,
    cfg: ForgeConfig,
    ram_cap_bytes: int,
    thermal_is_radiometric: bool,
) -> dict:
    """Full FORGE run + low-RAM-cap run on one recorded sequence; writes JSON, trajectories and the map."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    calib, events = make_stream(with_cameras=True)
    slam, res, (lio_t, lio_T), extra_thr, secs = run_stream(calib, events, out_dir / "full", cfg,
                                                           keep_thermal_frames=not thermal_is_radiometric)
    full_t, full_T = slam.corrected_trajectory()
    lio_p = point_in_body(lio_T, ref_point_b)
    full_p = point_in_body(full_T, ref_point_b)
    m_lio = ate_rpe(lio_t, lio_p, t_ref, p_ref)
    m_full = ate_rpe(full_t, full_p, t_ref, p_ref)
    np.savez_compressed(out_dir / "trajectories.npz", t=lio_t, lio=lio_p, forge=full_p,
                        t_ref=t_ref, p_ref=p_ref, lio_aligned=m_lio["_aligned"], forge_aligned=m_full["_aligned"],
                        t_aligned=m_lio["_t"], ref_aligned=m_lio["_ref"], forge_ref=m_full["_ref"])
    res.reconstruction.save(out_dir / "full" / "recon.npz")

    traj = (full_t, full_T)
    pts = res.reconstruction.points
    thr_frames = slam.thr_frames if thermal_is_radiometric else extra_thr
    offsets = (-0.1, -0.05, 0.0, 0.05, 0.1)
    reg = {
        "thermal": edge_alignment(pts, thr_frames, traj, time_offsets=offsets),
        "rgb": edge_alignment(pts, slam.rgb_frames, traj, time_offsets=offsets),
    }

    # Same stream, LiDAR + IMU only, RAM cap low enough to force spills: the map must not change
    cap_cfg = ForgeConfig(**{**cfg.__dict__, "max_ram_bytes": ram_cap_bytes, "enable_gsplat": False, "enable_thermal": False})
    calib2, events2 = make_stream(with_cameras=False)
    slam2, res2, _, _, secs2 = run_stream(calib2, events2, out_dir / "ramcap", cap_cfg)
    mem_full, mem_cap = res.diagnostics["memory"], res2.diagnostics["memory"]

    report = {
        "sequence": name,
        "scans": res.diagnostics["scans"],
        "keyframes": res.diagnostics["keyframes"],
        "wall_time_s": round(secs, 1),
        "static_init": res.diagnostics["static_init"],
        "degenerate_scans": res.diagnostics["degenerate_scans"],
        "lio_only": m_lio,
        "forge": m_full,
        "loops": loop_precision_recall(slam, t_ref, p_ref),
        "pose_graph": res.diagnostics["pose_graph"],
        "dynamic_filter": dynamic_summary(slam),
        "map_points": int(len(pts)),
        "memory_uncapped": mem_full,
        "memory_capped": {**mem_cap, "map_points": int(len(res2.reconstruction.points)),
                          "map_identical_to_uncapped": same_points(res2.reconstruction.points, pts),
                          "peak_rss_mb": res2.diagnostics["peak_rss_mb"], "wall_time_s": round(secs2, 1)},
        "peak_rss_mb": res.diagnostics["peak_rss_mb"],
        "timing_ms": res.diagnostics["timing_ms"],
        "camera_registration": reg,
        "thermal_map": res.diagnostics["thermal"],
        "splats": res.diagnostics["gsplat"],
        "camera_frames": {"rgb": len(slam.rgb_frames), "thermal": len(thr_frames)},
    }
    save_json(report, out_dir / "report.json")
    return report


def make_figures(run_dir: Path, out_prefix: Path, title: str) -> list[str]:
    """Top-down trajectories, position error over time, and dynamic points removed (on the static map)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run_dir, out_prefix = Path(run_dir), Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    tr = np.load(run_dir / "trajectories.npz")
    paths = []

    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    ax[0].plot(tr["ref_aligned"][:, 0], tr["ref_aligned"][:, 1], "k-", lw=2, label="reference")
    ax[0].plot(tr["lio_aligned"][:, 0], tr["lio_aligned"][:, 1], "-", color="tab:orange", lw=1, label="LIO only")
    ax[0].plot(tr["forge_aligned"][:, 0], tr["forge_aligned"][:, 1], "-", color="tab:blue", lw=1, label="FORGE")
    ax[0].set_aspect("equal")
    ax[0].set_xlabel("east [m]")
    ax[0].set_ylabel("north [m]")
    ax[0].legend()
    ax[0].set_title(f"{title}: trajectories (SE(3)-aligned)")
    t = tr["t_aligned"] - tr["t_aligned"][0]
    ax[1].plot(t, np.linalg.norm(tr["lio_aligned"] - tr["ref_aligned"], axis=1), color="tab:orange", label="LIO only")
    n = min(len(t), len(tr["forge_aligned"]))
    ax[1].plot(t[:n], np.linalg.norm(tr["forge_aligned"][:n] - tr["forge_ref"][:n], axis=1), color="tab:blue", label="FORGE")
    ax[1].set_xlabel("time [s]")
    ax[1].set_ylabel("position error [m]")
    ax[1].legend()
    ax[1].set_title("absolute position error")
    fig.tight_layout()
    p = out_prefix.with_name(out_prefix.name + "_trajectory.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    paths.append(str(p))

    from ..pointcloud import Reconstruction

    rec = Reconstruction.load(run_dir / "full" / "recon.npz")
    dm = np.load(run_dir / "full" / "dynamic_mask.npz")
    removed = dm["removed_points_w_odom"]
    fig, ax = plt.subplots(figsize=(8, 8))
    sel = np.random.default_rng(0).choice(len(rec.points), min(len(rec.points), 300_000), replace=False)
    ax.scatter(rec.points[sel, 0], rec.points[sel, 1], s=0.05, c="0.7", rasterized=True)
    if len(removed):
        ax.scatter(removed[:, 0], removed[:, 1], s=0.4, c="tab:red", rasterized=True, label=f"removed as dynamic ({len(removed)} pts)")
        ax.legend(loc="upper right", markerscale=10)
    ax.set_aspect("equal")
    ax.set_title(f"{title}: static map (grey), removed as dynamic (red)")
    fig.tight_layout()
    p = out_prefix.with_name(out_prefix.name + "_dynamic.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    paths.append(str(p))
    return paths


def evaluate_m2dgr(bag: Path, gt: Path, out_dir: Path, fig_dir: Path | None = None) -> dict:
    from .datasets import M2DGR_GNSS_IN_LIDAR, M2DGR_HANDSFREE_IN_LIDAR, iter_m2dgr_bag, load_m2dgr_gt

    t_ref, p_ref = load_m2dgr_gt(gt)
    cfg = ForgeConfig(
        keyframe_dist_m=1.0, voxel_size_m=0.1, sensor_height_m=1.2,
        lidar_origin_b=tuple(-M2DGR_HANDSFREE_IN_LIDAR), lidar_vfov_deg=(-31.0, 11.0),
        enable_thermal=False, camera_min_interval_s=1.0, max_gaussians=150_000, gsplat_iters=3,
    )

    def make_stream(with_cameras: bool):
        return iter_m2dgr_bag(bag, with_rgb=with_cameras, with_thermal=with_cameras)

    antenna_b = M2DGR_GNSS_IN_LIDAR - M2DGR_HANDSFREE_IN_LIDAR
    rep = evaluate_dataset(Path(bag).stem, make_stream, t_ref, p_ref, antenna_b, out_dir, cfg,
                           ram_cap_bytes=4 * 1024 * 1024, thermal_is_radiometric=False)
    if fig_dir is not None:
        rep["figures"] = make_figures(out_dir, Path(fig_dir) / f"forge_m2dgr_{Path(bag).stem}", f"M2DGR {Path(bag).stem}")
        save_json(rep, out_dir / "report.json")
    return rep


def evaluate_sthereo(seq_dir: Path, out_dir: Path) -> dict:
    from .datasets import iter_sthereo, load_sthereo_reference, sthereo_calibration

    t_ref, p_ref = load_sthereo_reference(seq_dir)
    calib, _ = sthereo_calibration(seq_dir)
    cfg = ForgeConfig(
        keyframe_dist_m=2.0, voxel_size_m=0.15, sensor_height_m=1.9,
        lidar_origin_b=tuple(calib.T_lidar_imu[:3, 3]), lidar_vfov_deg=(-23.0, 23.0),
        camera_min_interval_s=1.0, max_gaussians=150_000, gsplat_iters=3,
    )

    def make_stream(with_cameras: bool):
        return iter_sthereo(seq_dir, with_rgb=with_cameras, with_thermal=with_cameras)

    rep = evaluate_dataset(Path(seq_dir).name, make_stream, t_ref, p_ref, np.zeros(3), out_dir, cfg,
                           ram_cap_bytes=16 * 1024 * 1024, thermal_is_radiometric=True)
    rep["figures"] = make_figures(out_dir, Path(out_dir) / "fig", f"STheReO {Path(seq_dir).name}")
    save_json(rep, out_dir / "report.json")
    return rep

"""Bring a decoder's raw reconstruction into the project's metric ENU frame.

Decoders differ: some output camera-convention axes (y down, z forward), some are
only up-to-scale, few are georeferenced.  This module makes no assumption about the
model; it uses only geometry and whatever metadata/GPS the survey provides:

1. up axis    meta["up_axis"] ("z", "y", "-y", ...) or estimated from the dominant plane
2. scale      meta["metric"] true, else GPS track similarity, else objects of known size tapped in
              the clip's frames (params["scene_refs"], civil/scene_scale.py), else known camera height
3. georef     GPS track (Umeyama similarity on the horizontal plane), else heading +
              start offset from the survey parameters
"""

from __future__ import annotations

import math

import numpy as np

from .pointcloud import Reconstruction, latlon_to_enu, voxel_downsample

AXES = {"x": [1, 0, 0], "-x": [-1, 0, 0], "y": [0, 1, 0], "-y": [0, -1, 0], "z": [0, 0, 1], "-z": [0, 0, -1]}


def ransac_plane(
    xyz: np.ndarray,
    thresh: float,
    iters: int = 300,
    seed: int = 0,
    up_prior: np.ndarray | None = None,
    min_cos: float = 0.0,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Fit n·p + d = 0 to the largest plane. Returns (unit normal, d, inlier mask).

    When `up_prior` is given, only candidate planes with |n · up_prior| >= min_cos are considered,
    so vertical walls cannot beat the ground plane.
    """
    if len(xyz) < 3:
        raise ValueError("need at least 3 points for a plane")
    rng = np.random.default_rng(seed)
    best_n, best_d, best_count = np.array([0.0, 0.0, 1.0]), 0.0, -1
    pts = xyz.astype(np.float64)
    prior = None
    if up_prior is not None:
        prior = np.asarray(up_prior, dtype=np.float64)
        prior = prior / max(float(np.linalg.norm(prior)), 1e-12)
    for _ in range(iters):
        s = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n /= norm
        if prior is not None and abs(float(n @ prior)) < min_cos:
            continue
        d = -n @ s[0]
        count = int(np.count_nonzero(np.abs(pts @ n + d) < thresh))
        if count > best_count:
            best_n, best_d, best_count = n, d, count
    if best_count < 0:
        return best_n, float(best_d), np.zeros(len(pts), dtype=bool)
    inl = np.abs(pts @ best_n + best_d) < thresh
    # least-squares refine on inliers
    if inl.sum() >= 3:
        c = pts[inl].mean(axis=0)
        _, _, vt = np.linalg.svd(pts[inl] - c, full_matrices=False)
        n = vt[-1]
        if n @ best_n < 0:
            n = -n
        best_n, best_d = n, -n @ c
        inl = np.abs(pts @ best_n + best_d) < thresh
    return best_n, float(best_d), inl


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix that maps unit vector a onto unit vector b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -0.999999:
        # 180 degrees: rotate about any axis orthogonal to a
        axis = np.cross(a, [1, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool = True) -> tuple[float, np.ndarray, np.ndarray]:
    """Similarity dst ≈ s R src + t (any dimension). Returns (s, R, t)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    u, d, vt = np.linalg.svd(cov)
    sgn = np.eye(len(d))
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sgn[-1, -1] = -1
    r = u @ sgn @ vt
    var = (xs**2).sum() / len(src)
    s = float(np.trace(np.diag(d) @ sgn) / var) if with_scale and var > 0 else 1.0
    t = mu_d - s * r @ mu_s
    return s, r, t


def _apply(rec: Reconstruction, s: float, r: np.ndarray, t: np.ndarray) -> None:
    rec.points = (s * (rec.points.astype(np.float64) @ r.T) + t).astype(np.float32)
    if rec.poses is not None:
        p = np.array(rec.poses, dtype=np.float64)
        p[:, :3, :3] = r @ p[:, :3, :3]
        p[:, :3, 3] = s * p[:, :3, 3] @ r.T + t
        rec.poses = p


def align(rec: Reconstruction, origin_lat: float, origin_lon: float, params: dict | None = None) -> list[str]:
    """Mutate rec into the project's ENU metric frame. Returns human-readable notes."""
    params = params or {}
    meta = rec.meta
    notes: list[str] = []
    if rec.n < 100:
        raise ValueError("reconstruction has fewer than 100 points")

    # 1. up axis --------------------------------------------------------------
    up_hint = (params.get("up_axis") or meta.get("up_axis") or "auto").lower()
    raw_ext = float(np.ptp(rec.points, axis=0).max()) if rec.n else 1.0
    sample_vox = min(0.2, max(raw_ext / 120.0, 1e-4))
    sample_idx = voxel_downsample(rec.points, sample_vox, max_points=60_000)
    sample = rec.points[sample_idx].astype(np.float64)
    if up_hint in AXES:
        up = np.array(AXES[up_hint], dtype=np.float64)
        notes.append(f"up axis from metadata: {up_hint}")
    else:
        extent = np.ptp(sample, axis=0).max()
        traj = rec.trajectory()
        cam_up = _camera_up(rec)
        if cam_up is not None:
            # Restrict ground plane search to points below the cameras along cam_up (excludes sky/ceiling layers)
            # and accept planes within 60 deg of cam_up (handles phones tilted down at the road, rejects vertical walls).
            g_sample = sample
            if traj is not None and len(traj):
                below = ((sample - np.median(traj, axis=0)) @ cam_up) < 0
                if below.sum() >= 50:
                    g_sample = sample[below]
            g_ext = np.ptp(g_sample, axis=0).max()
            n, d, inl = ransac_plane(g_sample, thresh=max(0.01 * g_ext, 1e-4), up_prior=cam_up, min_cos=0.5)
            if inl.sum() >= max(15, int(0.05 * len(g_sample))) and abs(float(n @ cam_up)) >= 0.5:
                up = n if float(n @ cam_up) > 0 else -n
                notes.append("up axis estimated from the dominant (ground) plane")
            else:
                up = cam_up
                notes.append("up axis from the cameras' orientation (no level ground plane found)")
        else:
            n, d, _ = ransac_plane(sample, thresh=max(0.01 * extent, 0.02))
            if traj is not None and len(traj):
                above = np.median(traj @ n + d)
            else:
                above = np.median(sample @ n + d)
            up = n if above > 0 else -n
            notes.append("up axis estimated from the dominant (ground) plane")
    _apply(rec, 1.0, rotation_between(up, np.array([0.0, 0.0, 1.0])), np.zeros(3))

    # 2+3. scale and georeference --------------------------------------------
    metric = bool(params.get("metric", meta.get("metric", False)))
    traj = rec.trajectory()
    gps_used = False
    if rec.gps is not None and traj is not None and len(rec.gps) >= 3 and len(traj) >= 3:
        gx, gy = latlon_to_enu(rec.gps[:, 1], rec.gps[:, 2], origin_lat, origin_lon)
        if rec.times is not None and len(rec.times) == len(traj):
            gxi = np.interp(rec.times, rec.gps[:, 0], gx)
            gyi = np.interp(rec.times, rec.gps[:, 0], gy)
        else:  # assume both sample the same drive uniformly
            u = np.linspace(0, 1, len(traj))
            ug = np.linspace(0, 1, len(gx))
            gxi, gyi = np.interp(u, ug, gx), np.interp(u, ug, gy)
        dst = np.stack([gxi, gyi], 1)
        if np.ptp(dst, axis=0).max() > 5.0:  # need real motion for a stable fit
            s, r2, t2 = umeyama(traj[:, :2], dst, with_scale=not metric)
            r3 = np.eye(3)
            r3[:2, :2] = r2
            _apply(rec, s, r3, np.array([t2[0], t2[1], 0.0]))
            gps_used = True
            resid = np.linalg.norm(rec.trajectory()[:, :2] - dst, axis=1)
            notes.append(f"georeferenced to GPS track (scale {s:.4f}, median residual {np.median(resid):.2f} m)")
    if gps_used:
        meta["scale_info"] = {"method": "gps"}
    elif metric:
        meta["scale_info"] = {"method": "metric"}
    if not gps_used:
        scene_done = False
        if not metric and params.get("scene_refs") and traj is not None:
            # objects of known size tapped in the clip's frames (civil/scene_scale.py): preferred over the camera height
            from .scene_scale import ScaleError, cameras_from_rec, describe, estimate

            try:
                est = estimate(rec.points, cameras_from_rec(rec), params["scene_refs"], draws=60)
                c = est["combined"]
                _apply(rec, c["scale"], np.eye(3), np.zeros(3))
                ok = [r for r in est["refs"] if "error" not in r and not r.get("outlier")]
                text = describe(params["scene_refs"], [r["index"] for r in ok])
                notes.append(f"scale from {text}: factor {c['scale']:.4f} ±{c['pct']:.0f}%")
                meta["scale_info"] = {"method": "scene", "factor": c["scale"], "pct": c["pct"], "label": text}
                scene_done = True
            except ScaleError as e:
                notes.append(f"scene references could not be used ({e}); camera height used instead")
        cam_h = params.get("camera_height_m") or meta.get("camera_height_m")
        if scene_done or metric:
            pass
        elif cam_h and traj is not None:
            ground = _ground_z(rec)
            h = float(np.median(rec.trajectory()[:, 2]) - ground)
            if h > 1e-6:
                s = float(cam_h) / h
                _apply(rec, s, np.eye(3), np.zeros(3))
                notes.append(f"scale from camera height {cam_h} m (factor {s:.4f})")
                meta["scale_info"] = {"method": "camera_height", "camera_height_m": float(cam_h), "factor": s}
        else:
            notes.append("WARNING: scale unknown (no GPS, no camera height, decoder not metric); measurements are relative")
            meta["scale_info"] = {"method": "unknown"}
        heading = float(params.get("heading_deg", meta.get("heading_deg", 0.0)))
        traj = rec.trajectory()
        if traj is not None and len(traj) >= 2:
            disp = traj[min(len(traj) - 1, 10)] - traj[0]
            cur = math.atan2(disp[1], disp[0])
            want = math.radians(90.0 - heading)  # compass heading -> ENU angle
            a = want - cur
            rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            start = rec.trajectory()[0] @ rz.T
            off = np.array([float(params.get("start_east_m", 0.0)), float(params.get("start_north_m", 0.0)), 0.0])
            _apply(rec, 1.0, rz, off - np.array([start[0], start[1], 0.0]))
            notes.append(f"placed by heading {heading:.0f} deg from the project origin (no GPS)")

    # put ground at z = 0
    gz = _ground_z(rec)
    _apply(rec, 1.0, np.eye(3), np.array([0.0, 0.0, -gz]))
    rec.meta["aligned"] = True
    rec.meta["align_notes"] = notes
    return notes


def _camera_up(rec: Reconstruction) -> np.ndarray | None:
    """World up from the cameras' mean "up" axis, for decoders whose poses follow the OpenCV
    convention (x right, y down, z forward) with a camera held roughly upright, like a dash cam."""
    if rec.meta.get("camera_convention") != "opencv" or rec.poses is None or len(rec.poses) == 0:
        return None
    v = -np.asarray(rec.poses, dtype=np.float64)[:, :3, 1].mean(0)
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0.5 else None  # cameras pointing every which way: no hint


def _ground_z(rec: Reconstruction) -> float:
    """Height of the ground under the trajectory (or of the lowest dense layer)."""
    pts = rec.points
    traj = rec.trajectory()
    if traj is not None and len(traj):
        # points within 4 m horizontally of any of ~50 trajectory samples
        samp = traj[np.linspace(0, len(traj) - 1, min(50, len(traj))).astype(int)]
        idx = voxel_downsample(pts, 0.1, max_points=200_000)
        p = pts[idx]
        near = np.zeros(len(p), bool)
        for c in samp:
            near |= ((p[:, 0] - c[0]) ** 2 + (p[:, 1] - c[1]) ** 2) < 16.0
        z = p[near, 2] if near.sum() > 50 else p[:, 2]
        cam_z = float(np.median(traj[:, 2]))
        z = z[z < cam_z]  # ground is below the camera
        if len(z) < 50:
            z = p[:, 2]
    else:
        z = pts[:, 2]
    hist, edges = np.histogram(z, bins=200)
    # the ground is the densest thin layer in the lower part of the cloud
    lower = edges[:-1] <= np.percentile(z, 60)
    k = int(np.argmax(np.where(lower, hist, -1)))
    return float((edges[k] + edges[k + 1]) / 2)

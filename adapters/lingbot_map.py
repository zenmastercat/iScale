#!/usr/bin/env python3
"""LingBot-Map adapter for civil-scan (numpy only; runs with civil-scan's own Python).

LingBot-Map (Robbyant, github.com/Robbyant/lingbot-map, Apache-2.0) is not part of
this app.  You install it in its own environment (CUDA GPU); this script only calls
it as a separate process and converts its files.

Two modes:

  convert  Turn LingBot-Map's per-frame predictions into what civil-scan reads:
           python adapters/lingbot_map.py convert --pred-dir out/street --out decoded/
           -> decoded/points.ply (back-projected depth, coloured) + decoded/poses.json
              (camera-to-world poses and the per-frame intrinsics)

  run      Run LingBot-Map's batch_demo.py, then convert (used by the external decoder
           slot in config/decoders.json):
           python adapters/lingbot_map.py run --lingbot-python /envs/lingbot/bin/python \
               --lingbot-repo /opt/lingbot-map --model /opt/lingbot-map/lingbot-map.pt \
               --video street.mp4 --out decoded/ [--mode windowed] [--fps 10]

Facts this relies on (from LingBot-Map's code, see docs/LINGBOT_MAP.md):
  * batch_demo.py --save_predictions writes <out>/<scene>/frame_XXXXXX.npz with keys
    extrinsic (world-to-camera 3x4, OpenCV axes), intrinsic (3x3, model-image pixels),
    depth (z-depth, HxW[x1]), depth_conf (>= 1), images (the model input image).
  * Scale is NOT metric (normalised to the first 8 frames).  civil-scan fixes scale and
    position afterwards from a GPS track (gps.csv) or the camera height.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from civil.pointcloud import write_ply  # noqa: E402


def _squeeze_img(a: np.ndarray) -> np.ndarray:
    """Model image to HxWx3 uint8, whatever its layout ([1,]3,H,W or H,W,3, float or int)."""
    a = np.asarray(a)
    while a.ndim > 3:
        a = a[0]
    if a.ndim == 3 and a.shape[0] == 3 and a.shape[-1] != 3:
        a = np.transpose(a, (1, 2, 0))
    if a.dtype.kind == "f":
        a = np.clip(a * (255.0 if a.max() <= 1.0 + 1e-6 else 1.0), 0, 255)
    return a.astype(np.uint8)


def _mat(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    a = np.asarray(a, dtype=np.float64)
    return a.reshape(-1, *shape)[0] if a.size >= shape[0] * shape[1] else a


def _pose_direction(files: list[Path]) -> str:
    """Which way the saved 'extrinsic' points: back-project two nearby frames both ways and keep
    the direction under which their depth maps land on the same surfaces (LingBot commits differ)."""
    if len(files) < 3:
        return "w2c"
    n = len(files)
    gap = max(1, n // 12)

    def cloud(f: Path, inv: bool) -> np.ndarray:
        with np.load(f, allow_pickle=False) as z:
            m = np.eye(4)
            m[:3, :4] = _mat(z["extrinsic"], (3, 4))
            k = _mat(z["intrinsic"], (3, 3))
            d = np.asarray(z["depth"], dtype=np.float64)
            while d.ndim > 2:
                d = d[0] if d.shape[0] == 1 else d[..., 0]
        vv, uu = np.mgrid[0:d.shape[0]:12, 0:d.shape[1]:12]
        dd = d[vv, uu].ravel()
        ok = np.isfinite(dd) & (dd > 0)
        x = ((uu.ravel() + 0.5 - k[0, 2]) / k[0, 0] * dd)[ok]
        y = ((vv.ravel() + 0.5 - k[1, 2]) / k[1, 1] * dd)[ok]
        c2w = np.linalg.inv(m) if inv else m
        return np.c_[x, y, dd[ok]] @ c2w[:3, :3].T + c2w[:3, 3]

    def nn(a_: np.ndarray, b_: np.ndarray) -> float:
        s = b_[:: max(1, len(b_) // 400)]
        return float(np.median(np.sqrt(((s[:, None, :] - a_[None, :: max(1, len(a_) // 1500), :]) ** 2).sum(-1)).min(1)))

    # vote over pairs spread through the clip (the middle of a detection window may be unusual footage)
    votes = {"w2c": 0, "c2w": 0}
    for frac in (0.15, 0.35, 0.65, 0.85):
        i = min(n - 1 - gap, int(frac * n))
        j = i + gap
        s_inv = nn(cloud(files[i], True), cloud(files[j], True))
        s_dir = nn(cloud(files[i], False), cloud(files[j], False))
        votes["w2c" if s_inv < s_dir else "c2w"] += 1
    return "w2c" if votes["w2c"] >= votes["c2w"] else "c2w"


def convert(pred_dir: Path, out: Path, stride: int = 2, conf_drop_pct: float = 30.0,
            far_pct: float = 95.0, fps: float = 10.0, max_points: int = 6_000_000,
            boxes: dict[int, list[list[float]]] | None = None, t0: float = 0.0, pose: str = "auto",
            max_depth: float | None = None) -> dict:
    """boxes: {frame index: [[x0,y0,x1,y1] in model-image pixels]} from a 2D detector.
    Every depth pixel inside a box is back-projected as well and gets label 1 ("pothole"),
    so the detection lands in 3D at the exact spot the model saw it."""
    files = sorted(pred_dir.glob("frame_*.npz"))
    if not files:
        cands = sorted(pred_dir.rglob("frame_*.npz"))
        if not cands:
            raise SystemExit(f"no frame_*.npz found under {pred_dir}")
        files = cands
    out.mkdir(parents=True, exist_ok=True)
    direction = _pose_direction(files) if pose == "auto" else pose
    pts_all, col_all, lab_all, poses, times, intr = [], [], [], [], [], []
    boxes = boxes or {}
    per_frame_budget = max(1000, max_points // len(files))
    rng = np.random.default_rng(0)
    for i, f in enumerate(files):
        with np.load(f, allow_pickle=False) as z:
            w2c = _mat(z["extrinsic"], (3, 4))
            k = _mat(z["intrinsic"], (3, 3))
            depth = np.asarray(z["depth"], dtype=np.float64)
            while depth.ndim > 2:
                depth = depth[0] if depth.shape[0] == 1 else depth[..., 0]
            conf = np.asarray(z["depth_conf"], dtype=np.float64) if "depth_conf" in z else np.ones_like(depth)
            while conf.ndim > 2:
                conf = conf[0] if conf.shape[0] == 1 else conf[..., 0]
            img = _squeeze_img(z["images"]) if "images" in z else None
        # camera-to-world (the saved matrix is world-to-camera in the commits we checked)
        c2w = np.eye(4)
        if direction == "w2c":
            r, t = w2c[:, :3], w2c[:, 3]
            c2w[:3, :3] = r.T
            c2w[:3, 3] = -r.T @ t
        else:
            c2w[:3, :4] = w2c
        poses.append(c2w)
        intr.append(k.tolist())  # model-image pixels; civil/scene_scale.py casts rays through tapped frame pixels
        times.append(t0 + i / fps)
        h, w = depth.shape
        vv, uu = np.mgrid[0:h:stride, 0:w:stride]
        d = depth[vv, uu]
        c = conf[vv, uu]
        ok = np.isfinite(d) & (d > 0)
        if ok.sum() < 10:
            continue
        ok &= c >= np.percentile(c[ok], conf_drop_pct)
        ok &= d <= np.percentile(d[ok], far_pct)
        if max_depth:  # model units; far road is where single-camera depth is least accurate
            ok &= d <= max_depth
        lab = np.zeros(ok.shape, np.int32)
        for (bx0, by0, bx1, by1) in boxes.get(i, []):
            lab[(uu >= bx0) & (uu <= bx1) & (vv >= by0) & (vv <= by1)] = 1
        # keep every valid pixel inside a detection box, even if it misses the confidence cut
        inside = (lab == 1) & np.isfinite(d) & (d > 0)
        ok |= inside
        uu, vv, d, lab = uu[ok], vv[ok], d[ok], lab[ok]
        x = (uu + 0.5 - k[0, 2]) / k[0, 0] * d
        y = (vv + 0.5 - k[1, 2]) / k[1, 1] * d
        pc = np.stack([x, y, d], 1)
        pw = pc @ c2w[:3, :3].T + c2w[:3, 3]
        if len(pw) > per_frame_budget:
            keep = np.flatnonzero(lab == 1)
            rest = np.flatnonzero(lab == 0)
            take = max(0, per_frame_budget - len(keep))
            sel = np.concatenate([keep, rng.choice(rest, min(take, len(rest)), replace=False)])
            pw, uu, vv, lab = pw[sel], uu[sel], vv[sel], lab[sel]
        pts_all.append(pw.astype(np.float32))
        lab_all.append(lab)
        if img is not None and img.shape[:2] == (h, w):
            col_all.append(img[vv, uu, :3])
        else:
            col_all.append(np.full((len(pw), 3), 160, np.uint8))
    xyz = np.concatenate(pts_all)
    rgb = np.concatenate(col_all)
    labels = np.concatenate(lab_all)
    has_lab = bool((labels == 1).any())
    write_ply(out / "points.ply", xyz, rgb, labels if has_lab else None)
    if has_lab:
        (out / "labels.json").write_text(json.dumps({"1": "pothole"}))
    (out / "poses.json").write_text(json.dumps({"poses": [p.tolist() for p in poses], "times": times, "intrinsics": intr,
                                                "convention": "camera-to-world, OpenCV axes, LingBot-Map relative scale; "
                                                              "intrinsics 3x3 per frame in model-image pixels"}))
    info = {"frames": len(files), "points": int(len(xyz)), "metric": False, "pose_direction": direction,
            "detector_points": int((labels == 1).sum())}
    (out / "lingbot_convert.json").write_text(json.dumps(info, indent=2))
    return info


def run(args: argparse.Namespace) -> None:
    repo = Path(args.lingbot_repo)
    script = repo / "demo_render" / "batch_demo.py"
    if not script.is_file():
        raise SystemExit(f"batch_demo.py not found at {script}")
    pred_root = Path(args.out) / "lingbot_raw"
    pred_root.mkdir(parents=True, exist_ok=True)
    cmd = [args.lingbot_python, str(script), "--model_path", args.model, "--output_folder", str(pred_root),
           "--mode", args.mode, "--save_predictions", "--no_render"]
    if args.video:
        cmd += ["--video_path", args.video]
    elif args.image_folder:
        cmd += ["--input_folder", args.image_folder]
    else:
        raise SystemExit("give --video or --image-folder")
    if args.mode == "windowed":
        cmd += ["--window_size", str(args.window_size), "--overlap_keyframes", "8", "--keyframe_interval", "2"]
    cmd += args.extra
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(repo), check=False)
    if r.returncode != 0:
        raise SystemExit(f"LingBot-Map exited with code {r.returncode}")
    info = convert(pred_root, Path(args.out), stride=args.stride, fps=args.fps)
    print(json.dumps(info), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--pred-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--stride", type=int, default=2)
    c.add_argument("--conf-drop-pct", type=float, default=30.0)
    c.add_argument("--fps", type=float, default=10.0, help="frame rate the frames were sampled at (for timestamps)")
    r = sub.add_parser("run")
    r.add_argument("--lingbot-python", required=True)
    r.add_argument("--lingbot-repo", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--video")
    r.add_argument("--image-folder")
    r.add_argument("--out", required=True)
    r.add_argument("--mode", choices=["streaming", "windowed"], default="windowed")
    r.add_argument("--window-size", type=int, default=128)
    r.add_argument("--fps", type=float, default=10.0)
    r.add_argument("--stride", type=int, default=2)
    r.add_argument("extra", nargs=argparse.REMAINDER, help="extra flags passed to batch_demo.py after --")
    a = ap.parse_args()
    if a.cmd == "convert":
        print(json.dumps(convert(Path(a.pred_dir), Path(a.out), a.stride, a.conf_drop_pct, fps=a.fps)))
    else:
        if a.extra and a.extra[0] == "--":
            a.extra = a.extra[1:]
        run(a)


if __name__ == "__main__":
    main()

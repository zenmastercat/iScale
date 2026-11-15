"""Import an already-decoded scan: a PLY point cloud plus optional poses and GPS.

Use this for the output of any reconstruction model you run yourself, or for a
mobile-LiDAR export.  Optional files in the same upload:
  * poses:  poses.json / *_traj.txt (TUM or KITTI layout)
  * gps:    gps.csv with t, lat, lon columns
  * labels: labels.json mapping a per-point "label" PLY property to catalog codes,
            e.g. {"3": "sign_stop", "7": "pothole"}
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..catalog import CATALOG
from ..pointcloud import Reconstruction, read_gps_csv, read_ply, read_poses
from .base import Decoder, DecoderError, classify_inputs


def load_outputs(folder: Path, points_name: str | None = None, poses_name: str | None = None,
                 labels_name: str | None = None, gps_name: str | None = None) -> Reconstruction:
    """Shared by ply_import and external: read a decoder's output folder."""
    kinds = classify_inputs(folder)
    ply = folder / points_name if points_name else (kinds["ply"][0] if kinds["ply"] else None)
    if ply is None or not ply.is_file():
        raise DecoderError(f"no point cloud found in {folder.name} (expected a .ply file)")
    xyz, rgb, lab = read_ply(ply)
    poses = times = gps = None
    pose_file = folder / poses_name if poses_name else (kinds["poses"][0] if kinds["poses"] else None)
    if pose_file is not None and pose_file.is_file():
        poses, times = read_poses(pose_file)
    gps_file = folder / gps_name if gps_name else (kinds["gps"][0] if kinds["gps"] else None)
    if gps_file is not None and gps_file.is_file():
        gps = read_gps_csv(gps_file)
    label_names: dict[int, str] = {}
    lab_file = folder / labels_name if labels_name else folder / "labels.json"
    if lab is not None and lab_file.is_file():
        raw = json.loads(lab_file.read_text())
        label_names = {int(k): v for k, v in raw.items() if v in CATALOG}
    return Reconstruction(points=xyz, colors=rgb, poses=poses, times=times, gps=gps,
                          labels=lab if label_names else None, label_names=label_names)


class PlyImportDecoder(Decoder):
    name = "ply_import"
    label = "Import point cloud (PLY)"
    description = "Upload a decoded .ply (from LingBot-Map or any model/scanner), optionally with poses, gps.csv and labels.json."
    accepts = ("ply", "poses", "gps")

    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        rec = load_outputs(input_dir)
        rec.meta.update({"decoder": self.name, "metric": bool(params.get("metric", False))})
        if params.get("up_axis"):
            rec.meta["up_axis"] = params["up_axis"]
        if rec.n == 0 or not np.isfinite(rec.points).all():
            raise DecoderError("point cloud is empty or has non-finite coordinates")
        return rec

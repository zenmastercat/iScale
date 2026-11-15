import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from civil import catalog
from civil.align import align
from civil.decoders.external import ExternalDecoder
from civil.pointcloud import Reconstruction, read_ply, read_poses, write_ply
from civil.store import check_id, safe_filename

ROOT = Path(__file__).resolve().parent.parent


def test_catalog_has_50_plus_types_and_matches_phrases():
    assert len(catalog.CATALOG) >= 50
    assert catalog.match_type("can you identify all the stop signs") == ["sign_stop"]
    assert catalog.match_type("how many potholes are there") == ["pothole"]
    assert catalog.match_type("show trip hazards") == ["sidewalk_trip_hazard"]
    assert catalog.match_type("hello there") == []


def test_ply_roundtrip(tmp_path):
    xyz = np.random.default_rng(0).normal(size=(500, 3)).astype(np.float32)
    rgb = np.random.default_rng(1).integers(0, 255, (500, 3)).astype(np.uint8)
    write_ply(tmp_path / "a.ply", xyz, rgb)
    x2, c2, lab = read_ply(tmp_path / "a.ply")
    assert np.allclose(x2, xyz) and (c2 == rgb).all() and lab is None


def test_ascii_ply_and_tum_poses(tmp_path):
    (tmp_path / "b.ply").write_text("ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\n"
                                    "property float z\nproperty int label\nend_header\n0 0 0 3\n1 2 3 7\n")
    x, c, lab = read_ply(tmp_path / "b.ply")
    assert x.shape == (2, 3) and list(lab) == [3, 7]
    (tmp_path / "traj.txt").write_text("0 1 2 3 0 0 0 1\n1 2 2 3 0 0 0.7071068 0.7071068\n")
    poses, t = read_poses(tmp_path / "traj.txt")
    assert poses.shape == (2, 4, 4) and np.allclose(poses[1, :3, 3], [2, 2, 3])
    assert np.allclose(poses[1, :3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-6)


def test_ids_and_filenames_are_sanitised():
    with pytest.raises(KeyError):
        check_id("../etc")
    assert safe_filename("../../evil.sh") == "evil.sh"
    assert "/" not in safe_filename("a/b\\c d.ply")


def _fake_lingbot_frames(folder: Path, n: int = 12):
    """Frames of a camera driving +z (OpenCV) over a flat floor 1 unit below, relative scale."""
    folder.mkdir(parents=True)
    h, w = 60, 80
    k = np.array([[60.0, 0, 40], [0, 60.0, 30], [0, 0, 1]])
    for i in range(n):
        c2w = np.eye(4)
        c2w[:3, 3] = [0, 0, 0.3 * i]
        w2c = np.linalg.inv(c2w)[:3, :4]
        vv, uu = np.mgrid[0:h, 0:w]
        ray_y = (vv + 0.5 - 30) / 60.0
        floor = np.where(ray_y > 0.05, 1.0 / np.maximum(ray_y, 1e-3), np.inf)  # floor at y = +1 (OpenCV down)
        wall = np.full_like(floor, 8.0 - 0.3 * i)  # a wall at world z = 8 ahead of the moving camera
        depth = np.minimum(floor, wall)
        np.savez(folder / f"frame_{i:06d}.npz", extrinsic=w2c[None], intrinsic=k[None],
                 depth=depth[None, :, :, None], depth_conf=np.full((1, h, w), 2.0),
                 images=np.full((1, 3, h, w), 0.5, np.float32))
    return c2w


def test_lingbot_convert_inverts_poses_and_backprojects(tmp_path):
    _fake_lingbot_frames(tmp_path / "pred")
    out = tmp_path / "dec"
    r = subprocess.run([sys.executable, str(ROOT / "adapters" / "lingbot_map.py"), "convert",
                        "--pred-dir", str(tmp_path / "pred"), "--out", str(out), "--conf-drop-pct", "0"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    xyz, rgb, _ = read_ply(out / "points.ply")
    poses, _ = read_poses(out / "poses.json")
    assert np.allclose(poses[-1, :3, 3], [0, 0, 0.3 * 11])
    floor = xyz[xyz[:, 2] < 7.9]
    assert np.allclose(np.median(floor[:, 1]), 1.0, atol=0.02)  # floor recovered at +1 (down)
    assert np.allclose(np.median(xyz[xyz[:, 2] > 7.9][:, 2]), 8.0, atol=0.02)  # wall stays put at z = 8
    assert (rgb == 127).all() or (rgb == 128).all()


def test_external_decoder_slot_runs_a_command_and_aligns(tmp_path):
    script = tmp_path / "fake_model.py"
    script.write_text(
        "import sys, json, numpy as np\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from civil.pointcloud import write_ply\n"
        "out = sys.argv[sys.argv.index('--out') + 1]\n"
        "rng = np.random.default_rng(0)\n"
        "g = np.c_[rng.uniform(-5, 5, 20000), np.zeros(20000), rng.uniform(0, 40, 20000)]\n"  # y-down floor at 0
        "write_ply(__import__('pathlib').Path(out) / 'points.ply', g.astype('f4'))\n"
        "poses = []\n"
        "for i in range(40):\n"
        "    p = np.eye(4); p[:3, 3] = [0, -0.5, i]; poses.append(p.tolist())\n"  # camera 0.5 units above floor
        "json.dump({'poses': poses}, open(out + '/poses.json', 'w'))\n")
    cfg = {"enabled": True, "command": [sys.executable, str(script), "--in", "{input}", "--out", "{output}"],
           "meta": {"metric": False, "up_axis": "-y"}}
    dec = ExternalDecoder("fake", cfg, {})
    assert dec.available() == (True, "")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "clip.mp4").write_bytes(b"\x00")
    rec = dec.decode(tmp_path / "in", tmp_path / "work", {})
    notes = align(rec, 13.8, 100.5, {"camera_height_m": 2.0})
    assert any("camera height" in n for n in notes)
    traj = rec.trajectory()
    assert abs(np.median(traj[:, 2]) - 2.0) < 0.05  # scaled to metric camera height
    assert np.ptp(traj[:, :2], axis=0).max() == pytest.approx(39 * 4, rel=0.02)


def test_external_decoder_rejects_bad_config():
    assert ExternalDecoder("x", {"enabled": False}, {}).available()[0] is False
    assert ExternalDecoder("x", {"enabled": True, "command": "rm -rf /"}, {}).available()[0] is False


def test_knowledge_questions_route_to_helper():
    from civil.chat import is_knowledge_question
    for q in ["How thick should each hot-mix lift be when patching a pothole?",
              "Why do potholes form after rain?",
              "What is the recommended tack coat rate?",
              "Civil Helper, list the curing times for cold mix",
              "@civil-helper show the joint spacing for concrete slabs",
              "Helper: list the compaction passes for a 50 mm patch",
              "Foreman, list the curing times for cold mix"]:  # the old name still works
        assert is_knowledge_question(q), q
    for q in ["Where are the stop signs?", "How many high severity potholes are there?",
              "Which 3 segments are worst?", "What will it cost to fix the potholes?",
              "How should we fix the potholes in segment S03?", "What has been verified?"]:
        assert not is_knowledge_question(q), q


def test_windowed_surface_follows_reconstruction_drift():
    """A video reconstruction can bend along the walk (low-high-low). One quadratic per 25 m
    segment turns that bend into fake potholes; a windowed fit follows it and keeps the real dip."""
    import numpy as np

    from civil.analysis.raster import windowed_residual

    st = np.arange(0, 25, 0.1)
    off = np.arange(-3, 3, 0.1)
    uu, vv = np.meshgrid(st, off, indexing="ij")
    drift = 0.25 * np.sin(uu / 25 * 2.5 * np.pi)          # +-25 cm bend, like the Rangoon Road clip
    z = drift.copy()
    pothole = (uu - 12.0) ** 2 + vv ** 2 < 0.4 ** 2         # 0.8 m wide, 6 cm deep
    z[pothole] -= 0.06
    mask = np.ones_like(z, dtype=bool)
    whole = windowed_residual(uu, vv, z, mask, window_m=0)
    local = windowed_residual(uu, vv, z, mask, window_m=8)
    flat = ~pothole & (np.abs(uu - 12) > 1.5)
    assert np.nanmax(np.abs(whole[flat])) > 0.1              # the bend leaks into the residual
    assert np.nanpercentile(np.abs(local[flat]), 95) < 0.02  # windowed fit follows it
    assert abs(np.nanmin(local[pothole]) + 0.06) < 0.015     # and keeps the pothole's depth

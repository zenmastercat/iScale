"""Video pipeline end to end, with a fixed detector and a fake LingBot-Map (no GPU, no network)."""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from civil.api import app
from civil.video import job as video_job
from civil.video.frames import band, model_geometry
from civil.video.perspective import RoadPlane
from civil.video.windows import events, windows

from helpers import client_for

client = client_for("tester")

# fake scene, in LingBot-like relative units (OpenCV axes: x right, y down, z forward)
H, FOCAL, MW, MH = 1.0, 400.0, 518, 392  # camera height, focal (model px), model image size
SPEED = 2.0  # units per second
POT_Z, POT_R, POT_D = 32.0, 0.35, 0.08  # pothole centre ahead (z), radius, depth (units)

FAKE_BATCH_DEMO = r'''
import argparse, os, glob, numpy as np
ap = argparse.ArgumentParser()
ap.add_argument("--input_folder"); ap.add_argument("--output_folder"); ap.add_argument("--model_path")
ap.add_argument("--mode"); ap.add_argument("--save_predictions", action="store_true"); ap.add_argument("--no_render", action="store_true")
a = ap.parse_args()
H, F, MW, MH, SPEED, PZ, PR, PD, T0, FPS = %s
frames = sorted(glob.glob(os.path.join(a.input_folder, "*.jpg")))
out = os.path.join(a.output_folder, os.path.basename(a.input_folder)); os.makedirs(out, exist_ok=True)
K = np.array([[F, 0, MW / 2], [0, F, MH / 2], [0, 0, 1.0]])
vv, uu = np.mgrid[0:MH, 0:MW].astype(float)
dx, dy = (uu + 0.5 - MW / 2) / F, (vv + 0.5 - MH / 2) / F
for i, _ in enumerate(frames):
    cz = SPEED * (T0 + i / FPS)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(dy > 0.02, H / dy, 0.0)            # flat road at y = +H
        x, z = dx * d, cz + d
        inside = (x ** 2 + (z - PZ) ** 2) < PR ** 2
        d2 = (H + PD) / dy                               # lowered floor inside the pothole
        x2, z2 = dx * d2, cz + d2
        hole = inside & (((x2 ** 2 + (z2 - PZ) ** 2) < PR ** 2))
        d = np.where(hole, d2, d)
    d = np.where((d > 0) & (np.abs(dx * d) < 6) & (d < 40), d, 0.0).astype(np.float32)
    w2c = np.eye(4); w2c[2, 3] = -cz
    np.savez(os.path.join(out, f"frame_{i:06d}.npz"), extrinsic=w2c[None, :3, :4], intrinsic=K[None],
             depth=d[None, :, :, None], depth_conf=np.full((1, MH, MW), 2.0, np.float32))
'''


def test_events_and_windows():
    ev = events([3.0, 3.3, 9.0, 30.0, 30.4, 30.8], min_hits=2, hit_gap_s=1.0)
    assert [e["t0"] for e in ev] == [3.0, 30.0]  # the lone hit at 9 s is dropped
    w = windows(ev, duration=45, before_s=10, after_s=10)
    assert [(x["start"], x["end"]) for x in w] == [(0.0, 13.3), (20.0, 40.8)]
    w = windows([{"t0": 12, "t1": 12}, {"t0": 25, "t1": 26}], 60)
    assert len(w) == 1 and (w[0]["start"], w[0]["end"]) == (2, 36)  # overlapping windows merge


def test_long_merged_windows_split_in_gaps_between_potholes():
    """A road with potholes all along merges into one long window; LingBot takes at most 256 frames
    (51 s at 5 fps), so windows are capped at max_s and cut between events (Thai field test, 2026-11-15)."""
    ev = [{"t0": t, "t1": t + 1, "t": t, "hits": 3} for t in (5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115)]
    w = windows(ev, duration=130, before_s=10, after_s=10, max_s=40)
    assert len(w) >= 4 and all(x["end"] - x["start"] <= 40 + 1e-9 for x in w)
    assert w[0]["start"] == 0 and w[-1]["end"] == 126 and [x["index"] for x in w] == list(range(len(w)))
    assert all(a["end"] == b["start"] for a, b in zip(w, w[1:]))           # no gaps, no overlap
    assert sum(len(x["events"]) for x in w) == len(ev)                      # every pothole in exactly one clip
    for x in w:                                                             # and inside its clip
        assert all(x["start"] <= e["t0"] and e["t1"] <= x["end"] for e in x["events"])
    # one very long event (continuous hits) is still cut to max_s pieces
    w = windows([{"t0": 10, "t1": 100, "t": 10, "hits": 200}], duration=130, max_s=40)
    assert all(x["end"] - x["start"] <= 40 + 1e-9 for x in w) and (w[0]["start"], w[-1]["end"]) == (0, 110)
    # short windows are untouched
    assert len(windows([{"t0": 12, "t1": 12}], 60, max_s=40)) == 1


def test_perspective_plane_measures_a_known_rectangle():
    cfg = {"src": [[0.4, 0.5], [0.1, 0.9], [0.9, 0.9], [0.6, 0.5]], "width_m": 3.5, "length_m": 10, "near_m": 4, "px_per_m": 40}
    rp = RoadPlane(cfg, 1000, 1000)
    m = rp.to_metres(np.array([[100.0, 900.0], [900.0, 900.0], [500.0, 500.0]]))
    assert np.allclose(m[0], [-1.75, 4.0], atol=1e-6) and np.allclose(m[1], [1.75, 4.0], atol=1e-6)
    assert m[2][1] == pytest.approx(14.0)
    meas = rp.measure_box((450, 700, 550, 900))  # a box on the road whose bottom edge is the near edge
    assert meas["bev_valid"] and meas["distance_ahead_m"] == pytest.approx(4.0) and 0 < meas["bev_width_m"] < 1.5
    assert rp.measure_box((300, 100, 700, 300))["bev_valid"] is False  # above the horizon: no road position
    assert rp.bev(np.zeros((1000, 1000, 3), np.uint8)).shape[:2] == (400, 220)


def test_portrait_band_and_model_mapping():
    rows = band({"band": "auto", "auto_portrait_center": 0.62}, 540, 960)
    assert rows[1] - rows[0] == 540 and rows[1] <= 960
    g = model_geometry(540, rows)
    assert g["model_w"] == 518 and g["model_h"] == 518 and g["crop_top"] == 0


def _make_video(path: Path, seconds=30, fps=10, w=320, h=240):
    import cv2

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(seconds * fps):
        img = np.full((h, w, 3), 90, np.uint8)
        cv2.putText(img, str(i), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        vw.write(img)
    vw.release()


def test_video_job_end_to_end(tmp_path, monkeypatch):
    clip_fps, t_det = 2.0, 15.0
    win_start = t_det - 10
    repo = tmp_path / "fake_lingbot"
    (repo / "demo_render").mkdir(parents=True)
    (repo / "demo_render" / "batch_demo.py").write_text(
        FAKE_BATCH_DEMO % repr((H, FOCAL, MW, MH, SPEED, POT_Z, POT_R, POT_D, win_start, clip_fps)))
    (repo / "model.pt").write_bytes(b"x")
    # where the pothole appears at t_det, in model pixels -> original 320x240 frame pixels
    cz = SPEED * t_det
    dz = POT_Z - cz
    v_c = MH / 2 + FOCAL * H / dz
    half_u = FOCAL * POT_R / dz
    half_v = FOCAL * H / (dz - POT_R) - FOCAL * H / dz
    geo = model_geometry(320, (0, 240))
    mbox = [MW / 2 - half_u * 1.4, v_c - half_v * 1.6, MW / 2 + half_u * 1.4, v_c + half_v * 1.6]
    obox = [mbox[0] / geo["sx"], (mbox[1] + geo["crop_top"]) / geo["sy"], mbox[2] / geo["sx"], (mbox[3] + geo["crop_top"]) / geo["sy"]]

    cfg = json.loads((Path(video_job.__file__).parents[2] / "config" / "video.json").read_text())
    cfg["detector"] = {"kind": "fixed", "sample_fps": 2, "min_hits": 2, "hit_gap_s": 1.0,
                       "boxes": [{"t": t_det, "box": obox, "conf": 0.88}, {"t": t_det + 0.5, "box": obox, "conf": 0.8}]}
    cfg["frames"] = {"band": "auto", "fps": clip_fps}
    cfg["lingbot"] = {"python": sys.executable, "repo": str(repo), "model": str(repo / "model.pt"), "mode": "streaming",
                      "extra_args": [], "min_free_gpu_gb": 0, "timeout_s": 600}
    cfg["scale"] = {"camera_height_m": 1.5}
    monkeypatch.setattr(video_job, "video_config", lambda: cfg)

    _make_video(tmp_path / "drive.mp4")
    proj = client.post("/api/projects", json={"name": "video", "origin_lat": 13.8, "origin_lon": 100.5}).json()
    assert any(d["name"] == "pothole_video" for d in client.get("/api/meta").json()["decoders"])
    from civil import pipeline, store

    sv = store.create_survey(proj["id"], "Drive", "pothole_video", {})
    import shutil

    shutil.copy(tmp_path / "drive.mp4", store.survey_dir(proj["id"], sv["id"]) / "input" / "drive.mp4")
    pipeline.run_survey(proj["id"], sv["id"])
    st = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}").json()
    assert st["status"] == "done", st.get("error")
    vid = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/video").json()
    assert [(w["start"], w["end"]) for w in vid["windows"]] == [(5.0, 25.5)]
    assert len(vid["detections"]) == 2 and vid["detections"][0]["image"].endswith(".jpg")
    img = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/video/image/{vid['detections'][0]['bev_image']}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    child = vid["children"][0]
    assert child["survey"]["status"] == "done", child["survey"].get("error")
    assert child["detection_frames"] == 2
    an = client.get(f"/api/projects/{proj['id']}/surveys/{child['survey_id']}/analysis").json()
    pots = [f for f in an["findings"] if f["type"] == "pothole"]
    assert len(pots) == 1, [(f["type"], f["source"], f["evidence"]) for f in an["findings"]]
    p = pots[0]
    assert p["source"] == "detector+geometry"
    # scaled by camera height 1.5 (units -> metres): depth 0.08 units = 0.12 m
    assert p["metrics"]["depth_max_m"] == pytest.approx(POT_D * 1.5, abs=0.03)
    assert client.post(f"/api/projects/{proj['id']}/surveys/{sv['id']}/retry").status_code == 400

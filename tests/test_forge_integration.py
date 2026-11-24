"""TDD tests for FORGE SLAM Stage 7: End-to-End Pipeline, Decoder, CLI, and 3D Check Thermal Panel."""

from __future__ import annotations

from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient


def test_forge_slam_end_to_end_survey_and_check3d_thermal_panel(tmp_path):
    from civil import pipeline, store
    from civil.decoders import get_decoder
    from civil.forge.io import create_synthetic_forge_dataset, preflight_check
    from helpers import admin

    ds_dir = tmp_path / "forge_seq"
    create_synthetic_forge_dataset(ds_dir, n_keyframes=10, with_pothole=True, with_loop=True, with_dynamic=True)

    # 1. Pre-flight check must pass and confirm all 4 modalities + radiometric thermal
    pf = preflight_check(ds_dir)
    assert pf["ok"] is True, f"Preflight failed: {pf}"
    assert pf["radiometric_thermal"] is True
    assert pf["streams"]["lidar_scans"] == 10

    # 2. Decode via ForgeSlamDecoder and run through iScale's full survey pipeline
    dec = get_decoder("forge_slam")
    ok, why = dec.available()
    assert ok, f"forge_slam decoder should be available: {why}"

    client = admin()
    proj = client.post("/api/projects", json={"name": "FORGE Thermal Road Test", "origin_lat": 13.7563, "origin_lon": 100.5018}).json()
    sv = store.create_survey(proj["id"], "FORGE Multi-Sensor Run", "forge_slam", {})
    sdir = store.survey_dir(proj["id"], sv["id"])
    # Copy synthetic sequence into survey input dir
    import shutil
    shutil.copytree(ds_dir, sdir / "input", dirs_exist_ok=True)

    pipeline.run_survey(proj["id"], sv["id"])
    sv_done = store.get_survey(proj["id"], sv["id"])
    assert sv_done["status"] == "done", f"Survey failed: {sv_done.get('error')} {sv_done.get('trace')}"
    assert sv_done["scale"]["method"] == "metric"

    an = store.get_analysis(proj["id"], sv["id"])
    potholes = [f for f in an["findings"] if f["type"] in ("pothole", "depression")]
    assert len(potholes) >= 1, f"Expected pothole finding from FORGE SLAM reconstruction, got {an['findings']}"

    # 3. Verify 3D Check endpoint returns has_thermal=True, thermal_stats, and a valid PNG for panel=thermal
    fid = potholes[0]["id"]
    r = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/findings/{fid}/check")
    assert r.status_code == 200
    c = r.json()
    assert c["has_thermal"] is True
    assert "thermal" in c["images"]
    for k in ("min_c", "max_c", "mean_c", "road_ambient_c", "delta_c"):
        assert k in c["thermal_stats"]

    r_png = client.get(c["images"]["thermal"])
    assert r_png.status_code == 200
    assert r_png.headers["content-type"] == "image/png"
    assert r_png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_streaming_pipeline_selects_keyframes_and_spills_tiles_without_losing_points(tmp_path):
    from civil.forge.io import create_synthetic_forge_dataset
    from civil.forge.pipeline import run_forge_slam
    from civil.forge.types import ForgeConfig

    ds = create_synthetic_forge_dataset(tmp_path / "seq", n_keyframes=10, with_pothole=True, with_loop=False, with_dynamic=False)
    cfg = dict(keyframe_dist_m=2.0, enable_gsplat=False)
    big = run_forge_slam(ds, tmp_path / "big", ForgeConfig(**cfg))
    small = run_forge_slam(ds, tmp_path / "small", ForgeConfig(max_ram_bytes=40_000, **cfg))

    d = small.diagnostics
    assert d["scans"] == 10 and d["keyframes"] < d["scans"]
    assert d["memory"]["ssd_evictions_total"] > 0
    assert d["memory"]["peak_ram_bytes"] <= 40_000
    assert d["static_points"] == big.diagnostics["static_points"], "spilling to SSD must not change the map"


def test_preflight_rejects_inputs_the_loader_would_misread(tmp_path):
    import json
    from civil.forge.io import create_synthetic_forge_dataset, preflight_check

    ds = create_synthetic_forge_dataset(tmp_path / "seq", n_keyframes=6, with_pothole=False, with_loop=False, with_dynamic=False)
    assert preflight_check(ds)["ok"]

    cal = json.loads((ds / "calibration.json").read_text())
    no_k = {k: v for k, v in cal.items() if k not in ("K_rgb", "T_lidar_rgb")}
    (ds / "calibration.json").write_text(json.dumps(no_k))
    issues = " ".join(preflight_check(ds)["issues"])
    assert "K_rgb" in issues and "T_lidar_rgb" in issues

    no_t = {k: v for k, v in cal.items() if k != "scan_timestamps"}
    (ds / "calibration.json").write_text(json.dumps(no_t))
    assert "scan_timestamps" in " ".join(preflight_check(ds)["issues"])

    bag_only = tmp_path / "bag_only"
    bag_only.mkdir()
    (bag_only / "drive.bag").write_bytes(b"#ROSBAG V2.0\n")
    pf = preflight_check(bag_only)
    assert not pf["ok"] and "bag" in " ".join(pf["issues"]).lower()

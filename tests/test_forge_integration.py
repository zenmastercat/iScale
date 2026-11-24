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

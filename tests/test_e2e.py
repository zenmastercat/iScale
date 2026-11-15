"""End to end through the HTTP API on the synthetic demo street."""

import time

import pytest
from fastapi.testclient import TestClient

from civil.api import app

from helpers import client_for

client = client_for("tester")


@pytest.fixture(scope="module")
def demo():
    proj = client.post("/api/demo").json()
    pid = proj["id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        svs = client.get(f"/api/projects/{pid}").json()["survey_list"]
        if all(s["status"] in ("done", "error") for s in svs):
            break
        time.sleep(1)
    assert all(s["status"] == "done" for s in svs), [s.get("error") for s in svs]
    before, after = svs[0]["id"], svs[1]["id"]
    return pid, before, after


def test_analysis_finds_planted_defects_and_assets(demo):
    pid, before, _ = demo
    an = client.get(f"/api/projects/{pid}/surveys/{before}/analysis").json()
    types = [f["type"] for f in an["findings"]]
    assert types.count("pothole") == 5
    assert types.count("manhole_sunken") == 1
    assert types.count("sidewalk_trip_hazard") == 1
    assert types.count("sign_stop") == 2
    assert types.count("streetlight") == 7 and types.count("utility_pole") == 5 and types.count("tree") == 8
    assert all(s["condition"] is not None for s in an["segments"])
    assert all(f["evidence"] for f in an["findings"])


def test_points_endpoint(demo):
    pid, before, _ = demo
    r = client.get(f"/api/projects/{pid}/surveys/{before}/points.bin?max_points=50000")
    n = int(r.headers["X-Point-Count"])
    assert 10000 < n <= 50000 and len(r.content) == n * 15


def test_chat_stop_signs_and_costs(demo):
    pid, _, _ = demo
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "Can you identify all the stop signs"}).json()
    assert len(r["highlight"]) == 2 and "stop sign" in r["reply"].lower()
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "what will it cost to fix the potholes"}).json()
    assert r["plan"]["items"] and all(i["type"] == "pothole" for i in r["plan"]["items"])
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "worst 2 segments"}).json()
    assert len(r["segments"]) == 2
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "plan repairs with a budget of 500"}).json()
    assert r["plan"]["total"] <= 500


def test_plan_workorder_verify_cycle(demo):
    pid, before, after = demo
    plan = client.get(f"/api/projects/{pid}/surveys/{before}/plan").json()
    ids = [i["finding_id"] for i in plan["items"]]
    assert plan["total"] > 0 and ids
    wo = client.post(f"/api/projects/{pid}/workorders", json={"survey_id": before, "finding_ids": ids}).json()
    assert wo["id"] == "WO-0001" and wo["total"] > 0
    client.patch(f"/api/projects/{pid}/workorders/{wo['id']}", json={"status": "completed"})
    res = client.post(f"/api/projects/{pid}/verify", json={"before": before, "after": after}).json()
    by_type = {}
    for r in res["results"]:
        by_type.setdefault(r["type"], []).append(r["status"])
    # demo: 3 of 5 potholes, the sunken manhole and the trip hazard were repaired
    assert sorted(by_type["pothole"]) == ["not_fixed", "not_fixed", "verified", "verified", "verified"]
    assert by_type["manhole_sunken"] == ["verified"]
    assert by_type["sidewalk_trip_hazard"] == ["verified"]
    wos = client.get(f"/api/projects/{pid}/workorders").json()
    assert wos[0]["status"] == "partially_verified"
    an = client.get(f"/api/projects/{pid}/surveys/{before}/analysis").json()
    assert any(f["status"] == "verified" for f in an["findings"])


def test_manual_tag_and_exports(demo):
    pid, before, _ = demo
    f = client.post(f"/api/projects/{pid}/surveys/{before}/findings",
                    json={"type": "crosswalk_faded", "x": 30, "y": 0, "severity": "medium", "size_m": 3}).json()
    assert f["id"].startswith("M-") and f["segment_id"]
    assert client.post(f"/api/projects/{pid}/surveys/{before}/findings", json={"type": "nope", "x": 0, "y": 0}).status_code == 400
    g = client.get(f"/api/projects/{pid}/surveys/{before}/export.geojson").json()
    assert g["type"] == "FeatureCollection" and len(g["features"]) > 40
    c = client.get(f"/api/projects/{pid}/surveys/{before}/export.csv").text
    assert c.splitlines()[0].startswith("id,type")


def test_bad_ids_are_404():
    assert client.get("/api/projects/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/projects/zzzzzzzz").status_code == 404


def test_relative_scale_import_is_recovered_from_gps(tmp_path):
    """Simulates a non-metric decoder (like LingBot-Map): scaled, camera-axis output + GPS."""
    import json as _json

    import numpy as np

    from civil.decoders.demo import DemoDecoder
    from civil.pointcloud import write_ply

    rec = DemoDecoder().decode(tmp_path, tmp_path, {})
    s = 0.37  # arbitrary relative scale
    write_ply(tmp_path / "points.ply", (rec.points * s).astype("f4"), rec.colors)
    poses = rec.poses.copy()
    poses[:, :3, 3] *= s
    (tmp_path / "poses.json").write_text(_json.dumps({"poses": poses.tolist(), "times": rec.times.tolist()}))
    lines = ["t,lat,lon"] + [f"{t},{la},{lo}" for t, la, lo in rec.gps]
    (tmp_path / "gps.csv").write_text("\n".join(lines))

    proj = client.post("/api/projects", json={"name": "import test", "origin_lat": 13.8196, "origin_lon": 100.5137}).json()
    files = [("files", (n, open(tmp_path / n, "rb"))) for n in ("points.ply", "poses.json", "gps.csv")]
    sv = client.post(f"/api/projects/{proj['id']}/surveys", data={"name": "rel", "decoder": "ply_import",
                     "params": _json.dumps({"up_axis": "auto"})}, files=files).json()
    deadline = time.time() + 300
    while time.time() < deadline:
        st = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}").json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(1)
    assert st["status"] == "done", st.get("error")
    assert any("GPS" in n for n in st["notes"])
    an = client.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/analysis").json()
    types = [f["type"] for f in an["findings"]]
    assert types.count("pothole") == 5 and types.count("sign_stop") == 2
    assert abs(sum(s["length_m"] for s in an["segments"]) - 241) < 5  # metric length restored


def test_cross_site_and_rebinding_requests_are_refused():
    bare = TestClient(app)
    assert bare.post("/api/demo").status_code == 403  # no X-Civil-Scan header
    assert bare.get("/api/projects").status_code == 401  # not signed in
    evil = TestClient(app, base_url="http://attacker.example", headers={"X-Civil-Scan": "1"})
    assert evil.get("/api/projects").status_code == 400  # unknown Host (DNS rebinding)


def test_decoder_processes_do_not_get_the_roboflow_key(tmp_path, monkeypatch):
    import sys as _sys

    from civil.decoders.external import ExternalDecoder

    monkeypatch.setenv("ROBOFLOW_API_KEY", "secret-test-value")
    script = tmp_path / "dump.py"
    script.write_text("import os,sys; open(sys.argv[1] + '/env.txt','w').write(os.environ.get('ROBOFLOW_API_KEY','<none>'))\n")
    dec = ExternalDecoder("x", {"enabled": True, "command": [_sys.executable, str(script), "{output}"]}, {})
    (tmp_path / "in").mkdir()
    try:
        dec.decode(tmp_path / "in", tmp_path / "work", {})
    except Exception:
        pass  # no points.ply: expected; we only check what the process saw
    assert (tmp_path / "work" / "decoder_out" / "env.txt").read_text() == "<none>"

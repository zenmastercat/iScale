"""Sukhumvit sample run import: project, findings, photo endpoint, job card, analysis."""

import json

from civil.mock_import import MOCK_DIR

from helpers import client_for

client = client_for("sukh")


def _import():
    proj = client.post("/api/demo/sukhumvit").json()
    sid = proj["baseline"]
    return proj["id"], sid


def test_import_creates_project_with_17_findings_at_file_coordinates():
    pid, sid = _import()
    pots = json.loads((MOCK_DIR / "potholes_route_summary.json").read_text())["potholes"]
    an = client.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()
    assert len(an["findings"]) == 17 == len(pots)
    for f, p in zip(an["findings"], pots):
        assert abs(f["lat"] - p["latitude"]) < 1e-6 and abs(f["lon"] - p["longitude"]) < 1e-6
        assert f["type"] == "pothole" and f["source"] == "detector" and f["photo"] is True
        assert f["segment_id"] and f["severity"] in ("medium", "high")
        assert f["needs_review"] == (not p["alerted"])
    assert sum(f["needs_review"] for f in an["findings"]) == 4
    assert 480 < sum(s["length_m"] for s in an["segments"]) < 520
    assert all(s["condition"] is not None for s in an["segments"])
    sv = client.get(f"/api/projects/{pid}").json()
    assert sv["baseline"] == sid and sv["survey_list"][0]["status"] == "done"
    assert client.get(f"/api/projects/{pid}/surveys/{sid}/plan").status_code == 200
    assert client.get(f"/api/priority?project={pid}&survey={sid}").status_code == 200


def test_photo_endpoint_serves_jpeg_and_rejects_bad_names():
    pid, sid = _import()
    fid = client.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()["findings"][0]["id"]
    r = client.get(f"/api/projects/{pid}/surveys/{sid}/findings/{fid}/photo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    for bad in ("F000-9999", "..%2f..%2fproject", "x.jpg", "F000-0001.jpg"):
        assert client.get(f"/api/projects/{pid}/surveys/{sid}/findings/{bad}/photo").status_code == 404


def test_job_card_shows_the_detector_crop():
    pid, sid = _import()
    f = client.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()["findings"][0]
    card = client.get(f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/card").json()
    ph = card["location"]["photo"]
    assert ph["url"] == f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/photo" and ph["boxes"] == []
    assert ph["note"].startswith("Detector crop, frames 6..186, confidence 0.90")

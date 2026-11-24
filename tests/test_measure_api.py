"""Reference-object measurement through the API: preview, save on a finding or a pin, undo, photos, access."""

import io
import math
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from civil import auth, jobcard, measure_api
from civil.api import app

from helpers import HDR, admin, client_for, device_key, login, spki
from test_measure import HOLE, W, H, camera, rect, truth

CAM = camera(pitch_deg=60)
A4_PX = CAM(rect(0.25, 2.55, 0.210, 0.297, 10)).tolist()


def body(outline_m=HOLE, **extra):
    return {"image_w": W, "image_h": H, "ref_type": "a4", "ref_points": A4_PX,
            "outline": CAM(np.asarray(outline_m)).tolist(), **extra}


@pytest.fixture(autouse=True)
def no_geocoding(monkeypatch):
    monkeypatch.setattr(jobcard, "address", lambda *a, **k: {"line1": "Test Road", "line2": "Bangkok", "road": "Test Road"})


@pytest.fixture(scope="module")
def demo():
    c = admin()
    proj = c.post("/api/demo").json()
    deadline = time.time() + 300
    while time.time() < deadline:
        svs = c.get(f"/api/projects/{proj['id']}").json()["survey_list"]
        if all(s["status"] in ("done", "error") for s in svs):
            break
        time.sleep(1)
    sid = svs[0]["id"]
    an = c.get(f"/api/projects/{proj['id']}/surveys/{sid}/analysis").json()
    pot = next(f for f in an["findings"] if f["type"] == "pothole" and f["metrics"].get("depth_max_m"))
    return proj["id"], sid, pot


def test_refs_and_preview_store_nothing():
    c = client_for("meas.eng")
    refs = c.get("/api/measure/refs").json()
    assert {r["id"] for r in refs["refs"]} >= {"a4", "a3", "id1", "custom", "ruler"} and refs["tol_px"] == 3
    r = c.post("/api/measure/preview", json=body(depth_cm=6))
    assert r.status_code == 200, r.text
    j = r.json()
    area = truth(HOLE)[0]
    assert j["metrics"]["area_m2"] == pytest.approx(area, rel=0.02)
    assert j["metrics"]["depth_max_m"] == 0.06 and j["depth"]["source"] == "typed"
    lo, hi = j["result"]["ranges"]["area_m2"]
    assert lo <= j["metrics"]["area_m2"] <= hi and j["depth"]["volume_range"][0] < j["metrics"]["volume_m3"]
    assert j["bill"]["available"] and j["bill"]["subtotal"] > 0
    # the cut is 30 cm past the measured width x length on every side (DOH)
    assert j["bill"]["cut_w_m"] == pytest.approx(j["metrics"]["width_m"] + 0.6, abs=0.011)
    # no depth: the size is there, the cost is not, and it says why; no depth is made up
    j = c.post("/api/measure/preview", json=body()).json()
    assert "depth_max_m" not in j["metrics"] and not j["bill"]["available"] and "depth" in j["bill"]["reason"]
    # a bad shape is a clear 400
    r = c.post("/api/measure/preview", json={**body(), "ref_points": [[0, 0], [10, 10], [20, 20], [30, 0]]})
    assert r.status_code == 400 and "line" in r.json()["detail"]
    # every write needs the app header (CSRF guard), like the rest of the API
    bare = TestClient(app)
    assert bare.post("/api/measure/preview", json=body()).status_code == 403


def test_save_on_a_finding_rescale_3d_depth_and_undo(demo):
    pid, sid, pot = demo
    c = client_for("meas.eng")
    a3, d3 = pot["metrics"]["area_m2"], pot["metrics"]["depth_max_m"]
    side = math.sqrt(a3) * 1.25                      # the photo says the hole is 1.25 x bigger than the 3D did
    hole = np.array([[0.6, 2.4], [0.6 + side, 2.4], [0.6 + side, 2.4 + side], [0.6, 2.4 + side]])
    target = {"kind": "finding", "project": pid, "survey": sid, "id": pot["id"]}
    pv = c.post("/api/measure/preview", json=body(hole, rescale_3d=True, target=target)).json()
    assert pv["rescale_available"] and pv["depth"]["source"] == "3d_rescaled"
    assert pv["depth"]["k"] == pytest.approx(1.25, rel=0.02)
    assert pv["metrics"]["depth_max_m"] == pytest.approx(d3 * 1.25, rel=0.02)
    # far too small for the 3D outline: k < 0.2 is refused and the cost stays unavailable
    tiny = np.array([[0.6, 2.4], [0.62, 2.4], [0.62, 2.42], [0.6, 2.42]]) if a3 > 0.01 else None
    if tiny is not None:
        j = c.post("/api/measure/preview", json=body(tiny, rescale_3d=True, target=target)).json()
        assert j["depth"]["source"] is None and "0.2" in j["depth"]["error"] and not j["bill"]["available"]

    url = f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/measurement"
    r = c.post(url, json=body(hole, rescale_3d=True, target=target, image={"kind": "frame", "frame": 12}))
    assert r.status_code == 200, r.text
    f = r.json()["finding"]
    assert f["metrics"]["area_m2"] == pytest.approx(side * side, rel=0.02)
    assert {"width_m", "length_m", "perimeter_m", "depth_max_m", "volume_m3"} <= set(f["metrics"])
    assert f["metrics_prev"] == pot["metrics"] and f["metrics_3d"] == pot["metrics"]
    rec = f["measurement"]
    assert rec["source"] == "reference" and rec["ref"]["type"] == "a4" and rec["image"]["frame"] == 12
    assert len(rec["ref_points"]) == 4 and len(rec["outline"]) == 4 and rec["by"] and rec["at"]
    assert rec["depth"]["source"] == "3d_rescaled" and rec["ranges"]["area_m2"]
    assert f["measured"]["ref"] == "A4 sheet" and f["measured"]["by"] == "meas.eng"
    # the rest of the app reads the new metrics: cost chip, job card, plan, export, 3D check basis
    an = c.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()
    g = next(x for x in an["findings"] if x["id"] == pot["id"])
    assert g["cost"]["materials_cost"] == r.json()["bill"]["subtotal"] and g["measured"]["pct"] is not None
    card = c.get(f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/card").json()
    assert card["cost"]["subtotal"] == g["cost"]["materials_cost"] and card["measured"]["ref"] == "A4 sheet"
    assert any(t["key"] == "dims" for t in card["location"]["tiles"]) and card["measure"]["can_undo"]
    assert card["measure"]["three_d"]["area_m2"] == a3  # still offered: rescaling uses the 3D numbers, not the new ones
    plan = c.get(f"/api/projects/{pid}/surveys/{sid}/plan").json()
    item = next(i for i in plan["items"] if i["finding_id"] == pot["id"])
    assert item["quantity"] == pytest.approx(f["metrics"]["area_m2"] * 1.3, rel=0.01)
    csv = c.get(f"/api/projects/{pid}/surveys/{sid}/export.csv").text
    assert "A4 sheet ±" in next(ln for ln in csv.splitlines() if ln.startswith(pot["id"] + ","))

    # undo: back to the 3D numbers, and only one step
    u = c.post(url + "/undo")
    assert u.status_code == 200 and u.json()["finding"]["metrics"] == pot["metrics"]
    assert "measurement" not in u.json()["finding"] and "metrics_prev" not in u.json()["finding"]
    assert c.post(url + "/undo").status_code == 409


def test_other_companies_cannot_read_or_write_a_finding(demo, monkeypatch):
    pid, sid, pot = demo
    monkeypatch.setattr(auth, "_register_log", {})
    out = TestClient(app, headers=HDR)
    key = device_key()
    r = out.post("/api/auth/register", json={"kind": "individual", "username": "meas.outsider", "display_name": "Out",
                                             "public_key": spki(key)})
    assert r.status_code == 200, r.text
    assert login(out, "meas.outsider", key).status_code == 200
    target = {"kind": "finding", "project": pid, "survey": sid, "id": pot["id"]}
    assert out.post("/api/measure/preview", json=body(target=target)).status_code == 404
    assert out.post(f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/measurement", json=body()).status_code == 404
    assert out.get(f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/photo").status_code == 404


def _jpeg(w=640, h=480) -> bytes:
    img = np.full((h, w, 3), 120, np.uint8)
    cv2.rectangle(img, (100, 100), (300, 250), (255, 255, 255), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_pin_photo_and_measurement(monkeypatch):
    c = client_for("meas.eng")
    p = c.post("/api/pins", json={"lat": 13.70, "lon": 100.50, "severity": "medium"}).json()
    assert p["photo"] is None and c.get(f"/api/pins/{p['id']}/photo").status_code == 404
    up = c.post(f"/api/pins/{p['id']}/photo", files={"file": ("hole.jpg", _jpeg(), "image/jpeg")})
    assert up.status_code == 200, up.text
    assert (up.json()["w"], up.json()["h"]) == (640, 480)
    got = c.get(f"/api/pins/{p['id']}/photo")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert c.post(f"/api/pins/{p['id']}/photo", files={"file": ("x.jpg", b"not an image", "image/jpeg")}).status_code == 400
    monkeypatch.setattr(measure_api, "MAX_PHOTO_BYTES", 1000)
    assert c.post(f"/api/pins/{p['id']}/photo", files={"file": ("big.jpg", _jpeg(), "image/jpeg")}).status_code == 413
    assert c.post("/api/pins/zzzzzz0000/photo", files={"file": ("h.jpg", _jpeg(), "image/jpeg")}).status_code == 404

    url = f"/api/pins/{p['id']}/measurement"
    r = c.post(url, json=body(depth_cm=5, image={"kind": "photo"}))
    assert r.status_code == 200, r.text
    pin = r.json()["pin"]
    assert pin["metrics"]["area_m2"] == pytest.approx(truth(HOLE)[0], rel=0.02) and pin["metrics"]["depth_max_m"] == 0.05
    assert pin["size"]["depth_cm"] == 5 and pin["measured"]["ref"] == "A4 sheet" and pin["photo"]["url"]
    listed = next(x for x in c.get("/api/pins").json()["pins"] if x["id"] == p["id"])
    assert listed["cost"]["materials_cost"] == r.json()["bill"]["subtotal"]
    card = c.get(f"/api/pins/{p['id']}/card").json()
    assert card["measured"]["ref"] == "A4 sheet" and card["location"]["photo"]["kind"] == "photo"
    # a second measurement, then undo returns to the first; a typed size replaces the measurement
    c.post(url, json=body(depth_cm=9, image={"kind": "photo"}))
    assert c.post(url + "/undo").json()["pin"]["metrics"]["depth_max_m"] == 0.05
    assert c.post(url + "/undo").status_code == 409
    typed = c.patch(f"/api/pins/{p['id']}", json={"size": {"width_cm": 40, "length_cm": 50, "depth_cm": 4}}).json()
    assert typed["measured"] is None and typed["metrics"]["area_m2"] == 0.2 and typed["metrics"]["width_m"] == 0.4


def test_finding_photo_upload(demo):
    pid, sid, pot = demo
    c = client_for("meas.eng")
    r = c.post(f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/photo", files={"file": ("h.jpg", _jpeg(800, 600), "image/jpeg")})
    assert r.status_code == 200, r.text
    card = c.get(f"/api/projects/{pid}/surveys/{sid}/findings/{pot['id']}/card").json()
    assert card["location"]["photo"]["kind"] == "photo" and "/photo?v=" in card["location"]["photo"]["url"]
    assert c.get(card["location"]["photo"]["url"]).status_code == 200
    assert c.post(f"/api/projects/{pid}/surveys/{sid}/findings/nope/photo",
                  files={"file": ("h.jpg", _jpeg(), "image/jpeg")}).status_code == 404


def test_detector_boxes_land_on_the_cropped_frame():
    # a portrait video: the clip frames are the band of rows y0..y1, so a box maps into the band's own pixels
    from civil.video.frames import box_to_model, model_geometry

    geo = model_geometry(1080, (600, 1680))
    box = [300.0, 900.0, 500.0, 1000.0]  # full-frame pixels
    back = jobcard._box_to_frame(box_to_model(box, geo), geo)
    assert back == pytest.approx([300.0, 300.0, 500.0, 400.0], abs=0.6)

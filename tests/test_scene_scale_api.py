"""Fixing a 3D clip's scale with scene objects, through the API: preview, apply (rescale + re-analysis), undo.

The clip is tests/scene_fixture.py: LingBot-style predictions of a road whose camera is really 1.9 m high,
aligned with the app's 1.4 m guess, so every length is 1.9 / 1.4 = 1.357 times too short."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from civil import auth, jobcard, store
from civil.api import app

import scene_fixture as F
from helpers import HDR, admin, client_for, device_key, login, spki
from test_measure import HOLE, W, H, camera, rect

TRUE_K = F.CAM_H / F.GUESS_H
CAM = camera(pitch_deg=60)
A4_PX = CAM(rect(0.25, 2.55, 0.210, 0.297, 10)).tolist()


@pytest.fixture(autouse=True)
def no_geocoding(monkeypatch):
    monkeypatch.setattr(jobcard, "address", lambda *a, **k: {"line1": "Test Road", "line2": "Bangkok", "road": "Test Road"})


@pytest.fixture(scope="module")
def clip():
    a = admin()
    proj = a.post("/api/projects", json={"name": "scene scale", "origin_lat": 13.8196, "origin_lon": 100.5137}).json()
    jid, cid = F.add_video_job(proj["id"])
    return proj["id"], jid, cid


def edge_ref(frame, y_m, known=F.EDGE_GAP_M, **extra):
    a, b = F.edge_taps(frame, y_m)
    return {"ref_id": "custom", "known_m": known, "points": [{"frame": frame, "x": a[0], "y": a[1]},
                                                           {"frame": frame, "x": b[0], "y": b[1]}], **extra}


def pothole(an):
    return next(f for f in an["findings"] if f["type"] == "pothole" and f["metrics"].get("depth_max_m"))


def test_catalog_has_the_custom_distance_and_nothing_invented():
    c = client_for("scale.eng")
    j = c.get("/api/scene_scale/refs").json()
    ids = [o["id"] for o in j["objects"]]
    assert ids[-1] == "custom" and j["tol_px"] == 3
    for o in j["objects"]:
        if not o["custom"]:   # every standard size comes with its sources, or is marked provisional
            assert o["value_m"] > 0 and (o["source_urls"] or o["provisional"]), o["id"]
    assert TestClient(app).get("/api/scene_scale/refs").status_code == 401   # signed-in users only


def test_the_clip_says_how_it_is_scaled(clip):
    pid, jid, cid = clip
    c = client_for("scale.eng")
    s = c.get(f"/api/projects/{pid}/surveys/{cid}/scale").json()
    assert s["method"] == "camera_height" and s["text"] == "camera height guess"
    assert s["available"] and s["frames"] == F.N_FRAMES and not s["can_undo"]
    v = c.get(f"/api/projects/{pid}/surveys/{jid}/video").json()
    assert v["children"][0]["scale"]["text"] == "camera height guess"
    # a survey without frames (no video) cannot use scene objects, and says why
    other = store.create_survey(pid, "no frames", "ply_import", {})
    store.update_survey(pid, other["id"], status="done")
    s2 = c.get(f"/api/projects/{pid}/surveys/{other['id']}/scale").json()
    assert not s2["available"] and "video" in s2["why"]


def test_preview_finds_the_scale_and_flags_a_wrong_reference(clip):
    pid, _, cid = clip
    c = client_for("scale.eng")
    url = f"/api/projects/{pid}/surveys/{cid}/scale/preview"
    r = c.post(url, json={"refs": [edge_ref(0, 8.0), edge_ref(6, 12.0), edge_ref(12, 15.0, known=10.0)]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert [x["outlier"] for x in j["refs"]] == [False, False, True]
    assert j["refs"][0]["scale"] == pytest.approx(TRUE_K, rel=0.01)
    assert j["combined"]["scale"] == pytest.approx(TRUE_K, rel=0.01) and j["combined"]["used"] == 2
    assert 0 < j["combined"]["pct"] < 5 and j["combined"]["range"][0] < TRUE_K < j["combined"]["range"][1]
    assert len(j["refs"][0]["points_3d"]) == 2 and min(j["refs"][0]["support"]) >= 8
    assert j["clip_length_after_m"] == pytest.approx(j["clip_length_m"] * j["combined"]["scale"], rel=1e-3)
    # a tap in the sky is a clear error for that reference only
    sky = edge_ref(0, 8.0)
    sky["points"][1]["y"] = 5.0
    j = c.post(url, json={"refs": [edge_ref(0, 8.0), sky]}).json()
    assert "error" not in j["refs"][0] and "does not hit the 3D" in j["refs"][1]["error"]
    # bad input
    assert c.post(url, json={"refs": [{**edge_ref(0, 8.0), "ref_id": "nope"}]}).status_code == 400
    assert c.post(url, json={"refs": [{**edge_ref(0, 8.0), "known_m": None}]}).status_code == 400
    assert c.post(url, json={"refs": [{**edge_ref(0, 8.0), "points": [{"frame": 999, "x": 1, "y": 1}] * 2}]}).status_code == 400
    assert TestClient(app).post(url, json={"refs": [edge_ref(0, 8.0)]}).status_code == 403   # no app header


def test_apply_rescales_reanalyses_keeps_measurements_and_undo_puts_it_back(clip):
    pid, _, cid = clip
    c = client_for("scale.eng")
    base = f"/api/projects/{pid}/surveys/{cid}"
    an0 = c.get(f"{base}/analysis").json()
    pot0 = pothole(an0)
    d0, a0 = pot0["metrics"]["depth_max_m"], pot0["metrics"]["area_m2"]
    sv0 = c.get(base).json()
    # someone measured the pothole on a photo first (size from the photo, depth typed): it must survive
    meas = {"image_w": W, "image_h": H, "ref_type": "a4", "ref_points": A4_PX, "outline": CAM(np.asarray(HOLE)).tolist(),
            "depth_cm": 6}
    r = c.post(f"{base}/findings/{pot0['id']}/measurement", json=meas)
    assert r.status_code == 200, r.text
    measured = r.json()["finding"]["metrics"]
    c.post(f"{base}/findings/{pot0['id']}/review", json={"verdict": "correct"})

    r = c.post(f"{base}/scale/apply", json={"refs": [edge_ref(0, 8.0), edge_ref(6, 12.0), edge_ref(12, 15.0, known=10.0)]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["factor"] == pytest.approx(TRUE_K, rel=0.01)
    assert j["scale"]["method"] == "scene" and j["scale"]["text"].startswith("2 scene references ±") and j["scale"]["can_undo"]
    sv = c.get(base).json()
    assert "scale from 2 scene references (" in sv["notes"][-1] and "factor 1.3" in sv["notes"][-1]
    assert sv["params"]["scene_refs"] and len(sv["params"]["scene_refs"]) == 3
    assert sv["stats"]["length_m"] > sv0["stats"]["length_m"] * 1.3

    an = c.get(f"{base}/analysis").json()
    pot = next(f for f in an["findings"] if f["id"] == pot0["id"])     # same pothole, same id
    # the user's measurement stays; the 3D numbers behind it are the new, metric ones
    assert pot["metrics"] == measured and pot["measurement"]["ref"]["type"] == "a4"
    assert pot["metrics_3d"]["depth_max_m"] == pytest.approx(d0 * TRUE_K, rel=0.12)
    assert pot["metrics_3d"]["area_m2"] == pytest.approx(a0 * TRUE_K**2, rel=0.25)
    assert pot["metrics_prev"] == pot["metrics_3d"]          # undoing the measurement now gives the metric 3D
    assert pot["review"]["verdict"] == "correct" and pot["history"][-1]["event"].startswith("rescaled ×1.3")
    assert pot["cost"] is not None
    # the pothole's true depth is 8 cm: the scene scale brings the 3D depth close to it
    assert abs(pot["metrics_3d"]["depth_max_m"] - F.POTHOLE[3]) < abs(d0 - F.POTHOLE[3])
    # the job card and the 3D check read the new numbers
    chk = c.get(f"{base}/findings/{pot['id']}/check").json()
    assert chk["measured_depth_m"] == pot["metrics_3d"]["depth_max_m"]
    # the references now read their real size
    pv = c.post(f"{base}/scale/preview", json={"refs": [edge_ref(0, 8.0)]}).json()
    assert pv["combined"]["scale"] == pytest.approx(1.0, rel=0.01)

    u = c.post(f"{base}/scale/undo")
    assert u.status_code == 200, u.text
    assert u.json()["scale"]["method"] == "camera_height" and not u.json()["scale"]["can_undo"]
    sv = c.get(base).json()
    assert sv["notes"] == sv0["notes"] and "scene_refs" not in sv["params"]
    an = c.get(f"{base}/analysis").json()
    pot = next(f for f in an["findings"] if f["id"] == pot0["id"])
    assert pot["metrics"] == measured
    assert pot["metrics_3d"]["depth_max_m"] == pytest.approx(d0, rel=0.03)
    assert c.post(f"{base}/scale/undo").status_code == 409


def test_rebuilding_the_clip_uses_the_scene_references_before_the_camera_height(clip):
    from civil.align import align
    from civil.decoders.lingbot_clip import LingbotClipDecoder
    from civil import scene_scale as ss

    pid, _, cid = clip
    d = store.survey_dir(pid, cid)
    sv = store.get_survey(pid, cid)
    rec = LingbotClipDecoder().convert(d / "work" / "lingbot_raw", d / "input", d / "work", sv["params"])
    refs = [{"label": "edge lines", "known_m": F.EDGE_GAP_M, "rel_error": 0.01,
             "points": [{"frame": 3, "xy": p} for p in F.edge_taps(3, 10.0)]}]
    notes = align(rec, 13.8196, 100.5137, {**sv["params"], "scene_refs": refs})
    assert any(n.startswith("scale from 1 scene reference (edge lines ×1)") for n in notes)
    assert not any("camera height" in n for n in notes) and rec.meta["scale_info"]["method"] == "scene"
    r = ss.measure_ref(rec.points, ss.cameras_from_rec(rec), {**refs[0], "points": [{"frame": 8, "xy": p} for p in F.edge_taps(8, 14.0)]})
    assert r["d3"] == pytest.approx(F.EDGE_GAP_M, rel=0.01)


def test_writes_need_a_signed_in_member_of_the_company(clip, monkeypatch):
    pid, _, cid = clip
    monkeypatch.setattr(auth, "_register_log", {})
    out = TestClient(app, headers=HDR)
    key = device_key()
    r = out.post("/api/auth/register", json={"kind": "individual", "username": "scale.outsider", "display_name": "Out",
                                             "public_key": spki(key)})
    assert r.status_code == 200, r.text
    assert login(out, "scale.outsider", key).status_code == 200
    base = f"/api/projects/{pid}/surveys/{cid}/scale"
    assert out.get(base).status_code == 404
    assert out.post(base + "/apply", json={"refs": [edge_ref(0, 8.0)]}).status_code == 404
    assert out.post(base + "/undo").status_code == 404
    assert TestClient(app, headers=HDR).post(base + "/apply", json={"refs": [edge_ref(0, 8.0)]}).status_code == 401
    assert math.isfinite(TRUE_K)


def test_apply_updates_size_cost_card_and_export_and_marks_where_the_scale_came_from():
    """A pothole nobody measured by hand: its size comes from the 3D, so the rescale changes its depth, area,
    the DOH bill of materials and the cost, and every place that shows them says how the clip was scaled."""
    from civil import store as st

    pid = st.list_projects(admin().get("/api/auth/state").json()["user"]["company_id"])[0]["id"]
    cid = F.make_clip(pid, "Cost clip")
    c = client_for("scale.eng")
    base = f"/api/projects/{pid}/surveys/{cid}"
    an0 = c.get(f"{base}/analysis").json()
    p0 = pothole(an0)
    assert an0["scale"]["method"] == "camera_height"
    assert p0["scaled_by"] == "Scale: camera height guess, not measured"
    card0 = c.get(f"{base}/findings/{p0['id']}/card").json()
    assert card0["scaled_by"] == p0["scaled_by"]

    r = c.post(f"{base}/scale/apply", json={"refs": [edge_ref(0, 8.0), edge_ref(6, 12.0)]})
    assert r.status_code == 200, r.text
    k = r.json()["factor"]
    assert k == pytest.approx(TRUE_K, rel=0.01)
    an = c.get(f"{base}/analysis").json()
    p = next(f for f in an["findings"] if f["id"] == p0["id"])
    # re-analysed, not just multiplied: the depth follows k, the area k² (within what the re-run detection gives)
    assert p["metrics"]["depth_max_m"] == pytest.approx(p0["metrics"]["depth_max_m"] * k, rel=0.12)
    assert p["metrics"]["area_m2"] == pytest.approx(p0["metrics"]["area_m2"] * k ** 2, rel=0.25)
    assert abs(p["metrics"]["depth_max_m"] - F.POTHOLE[3]) < abs(p0["metrics"]["depth_max_m"] - F.POTHOLE[3])
    # the DOH cost engine prices the new size
    assert p0["cost"] and p["cost"] and p["cost"]["materials_cost"] > p0["cost"]["materials_cost"]
    assert p["scaled_by"].startswith("Scaled by: 7 m (custom) ×2, ±") and p["scaled_by"].endswith("%")
    assert an["scale"]["method"] == "scene" and an["scale"]["factor"] == pytest.approx(k)
    card = c.get(f"{base}/findings/{p['id']}/card").json()
    assert card["scaled_by"] == p["scaled_by"]
    assert card["cost"]["available"] and card["cost"]["subtotal"] == pytest.approx(p["cost"]["materials_cost"])
    csv_text = c.get(f"{base}/export.csv").text
    assert "3D; Scaled by: 7 m (custom) ×2" in csv_text
    # the clip's scale summary carries the same mark
    sc = c.get(f"{base}/scale").json()
    assert sc["mark"] == p["scaled_by"] and sc["can_undo"] and sc["steps"] == 1
    assert c.post(f"{base}/scale/undo").status_code == 200
    p2 = next(f for f in c.get(f"{base}/analysis").json()["findings"] if f["id"] == p0["id"])
    assert p2["cost"]["materials_cost"] == pytest.approx(p0["cost"]["materials_cost"], rel=0.1)
    assert p2["scaled_by"] == "Scale: camera height guess, not measured"


def test_a_scale_measured_on_an_older_clip_is_refused():
    """Two people apply at once: the second factor was measured on the clip before the first rescale."""
    from fastapi import HTTPException

    from civil import scene_scale_api as api_mod
    from civil import store as st

    pid = st.list_projects(admin().get("/api/auth/state").json()["user"]["company_id"])[0]["id"]
    cid = F.make_clip(pid, "Race clip")
    with pytest.raises(HTTPException) as e:
        api_mod.rescale_survey(pid, cid, 1.3, scale={"method": "scene", "history": [{"k": 1.3, "pivot": None}] * 2},
                               notes=[], params_refs=None, event="test", uid=None, expect_steps=1)
    assert e.value.status_code == 409
    assert st.get_survey(pid, cid)["scale"]["method"] == "camera_height"     # nothing changed


def test_preview_and_scale_need_the_company_and_a_finished_clip(clip, monkeypatch):
    pid, jid, cid = clip
    monkeypatch.setattr(auth, "_register_log", {})
    out = TestClient(app, headers=HDR)
    key = device_key()
    assert out.post("/api/auth/register", json={"kind": "individual", "username": "scale.outsider2", "display_name": "Out",
                                                "public_key": spki(key)}).status_code == 200
    assert login(out, "scale.outsider2", key).status_code == 200
    base = f"/api/projects/{pid}/surveys/{cid}"
    assert out.post(base + "/scale/preview", json={"refs": [edge_ref(0, 8.0)]}).status_code == 404
    assert out.get(base + "/frames/0").status_code == 404          # the frames the taps are made on, too
    anon = TestClient(app, headers=HDR)
    assert anon.post(base + "/scale/preview", json={"refs": [edge_ref(0, 8.0)]}).status_code == 401
    assert anon.post(base + "/scale/undo").status_code == 401
    # a clip still being built cannot be scaled
    c = client_for("scale.eng")
    st = store.update_survey(pid, cid, status="running")
    try:
        assert c.post(base + "/scale/preview", json={"refs": [edge_ref(0, 8.0)]}).status_code == 409
        assert c.post(base + "/scale/apply", json={"refs": [edge_ref(0, 8.0)]}).status_code == 409
        assert not c.get(base + "/scale").json()["available"]
    finally:
        store.update_survey(pid, cid, status="done")
    assert st["status"] == "running"
    # the video job (no 3D model) cannot be scaled either
    assert c.post(f"/api/projects/{pid}/surveys/{jid}/scale/preview", json={"refs": [edge_ref(0, 8.0)]}).status_code in (404, 409)

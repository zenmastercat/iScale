"""Materials-only repair cost, pothole job card, and the admin price settings."""

import math

import numpy as np
import pytest

from civil import jobcard, materials, store

from helpers import admin, client_for


@pytest.fixture(autouse=True)
def no_geocoding(monkeypatch):
    monkeypatch.setattr(jobcard, "address", lambda *a, **k: {"line1": "Test Road", "line2": "Bang Sue, Bangkok", "road": "Test Road"})


def test_method_follows_depth():
    assert materials.bill({"area_m2": 0.5, "depth_max_m": 0.04})["method"] == "small_patch"
    assert materials.bill({"area_m2": 0.5, "depth_max_m": 0.08})["method"] == "layered_patch"
    deep = materials.bill({"area_m2": 0.5, "depth_max_m": 0.15})
    assert deep["method"] == "full_depth"
    assert deep["asphalt_depth_m"] == 0.10 and abs(deep["base_depth_m"] - 0.05) < 1e-9 and deep["layers"] == 2
    assert [ln["key"] for ln in deep["lines"]] == ["cold_mix", "tack_coat", "base", "prime_coat"]
    assert deep["prime_l"] > 0


def test_quantities_and_cost_are_materials_only():
    cfg = materials.defaults()
    b = materials.bill({"area_m2": 1.0, "depth_max_m": 0.08}, cfg)
    cm = cfg["materials"]["cold_mix"]
    cut = (1.0 + 2 * cfg["cut_edge_m"]) ** 2  # 1 m x 1 m damage, cut 30 cm past it on every side (DOH)
    kg = cut * 0.08 * cm["density_kg_m3"] * (1 + cm["compaction_allowance"])
    assert b["bags"] == math.ceil(kg / cm["bag_kg"])
    assert b["layers"] == 2
    assert b["subtotal"] == pytest.approx(sum(ln["amount"] for ln in b["lines"]))
    assert b["cut_area_m2"] == pytest.approx(cut, abs=0.01)
    assert "factor_f" not in b  # not valid on a materials-only figure
    assert "Labour" in b["excludes"]
    steps = materials.steps(b)
    assert any(f"{b['bags']} bags" in s for s in steps) and any("2 layers" in s for s in steps)


def test_missing_price_is_left_out_of_the_total_and_named():
    cfg = materials.defaults()
    cfg["materials"]["base"]["price"] = 0
    b = materials.bill({"area_m2": 1.0, "depth_max_m": 0.2}, cfg)
    assert "Crushed rock base" in b["missing_prices"]
    assert b["subtotal"] == pytest.approx(sum(ln["amount"] or 0 for ln in b["lines"] if ln["key"] != "base"))


def test_no_size_means_no_estimate():
    assert materials.bill({})["available"] is False
    assert materials.bill({"area_m2": 0.3})["available"] is False


def test_repair_window_follows_road_class():
    assert jobcard.timing({"highway": "primary"})["window"] == "22:00-05:00"
    assert jobcard.timing({"highway": "residential"})["road_class"] == "local"
    t = jobcard.timing(None)
    assert t["road_class"] == "unknown" and "not known" in t["basis"]
    assert jobcard.timing({"highway": "primary", "ratio": 1.8})["now"]["level"] == "heavy"


def test_pin_size_gives_a_cost_and_a_full_card():
    a = client_for("mali")
    p = a.post("/api/pins", json={"lat": 13.75, "lon": 100.52, "severity": "high",
                                  "size": {"width_cm": 80, "length_cm": 60, "depth_cm": 7}}).json()
    listed = next(x for x in a.get("/api/pins").json()["pins"] if x["id"] == p["id"])
    assert listed["metrics"]["area_m2"] == pytest.approx(0.48)
    assert listed["cost"]["materials_cost"] > 0 and listed["cost"]["method"] == "layered_patch"
    card = a.get(f"/api/pins/{p['id']}/card").json()
    assert card["cost"]["available"] and card["cost"]["subtotal"] == listed["cost"]["materials_cost"]
    assert card["location"]["address"]["line1"] == "Test Road"
    assert card["location"]["nav_url"].startswith("https://www.google.com/maps/dir/?api=1&destination=13.750000,100.520000")
    assert card["plan"]["urgency_code"] == "immediate" and len(card["plan"]["steps"]) >= 6
    assert card["timing"]["window"]


def test_pin_without_size_can_get_one_later():
    a = client_for("mali")
    p = a.post("/api/pins", json={"lat": 13.76, "lon": 100.53, "severity": "medium"}).json()
    assert a.get(f"/api/pins/{p['id']}/card").json()["cost"]["available"] is False
    r = a.patch(f"/api/pins/{p['id']}", json={"size": {"width_cm": 40, "length_cm": 40, "depth_cm": 4}})
    assert r.status_code == 200
    assert a.get(f"/api/pins/{p['id']}/card").json()["cost"]["method"] == "small_patch"
    assert a.patch(f"/api/pins/{p['id']}", json={"size": {"width_cm": 40, "length_cm": 40, "depth_cm": 900}}).status_code == 422


def test_only_admins_change_prices_and_prices_change_the_cost():
    eng, adm = client_for("mali"), admin()
    assert eng.get("/api/settings/materials").json()["editable"] is False
    assert eng.put("/api/settings/materials", json={"materials": {"cold_mix": {"price": 1}}}).status_code == 403
    p = eng.post("/api/pins", json={"lat": 13.77, "lon": 100.54, "severity": "low",
                                    "size": {"width_cm": 50, "length_cm": 50, "depth_cm": 4}}).json()
    before = eng.get(f"/api/pins/{p['id']}/card").json()["cost"]
    try:
        r = adm.put("/api/settings/materials", json={"materials": {"cold_mix": {"price": before["lines"][0]["unit_price"] * 2}}})
        assert r.status_code == 200, r.text
        after = eng.get(f"/api/pins/{p['id']}/card").json()["cost"]
        assert after["lines"][0]["amount"] == pytest.approx(before["lines"][0]["amount"] * 2)
        assert after["lines"][0]["source"] == "set by your admin"
        assert adm.put("/api/settings/materials", json={"materials": {"cold_mix": {"bag_kg": 0}}}).status_code == 400
        assert adm.put("/api/settings/materials", json={"materials": {"gold": {"price": 1}}}).status_code == 400
    finally:
        adm.put("/api/settings/materials", json={"materials": {}})


def test_best_frame_is_the_one_looking_at_the_pothole(tmp_path, monkeypatch):
    sdir = tmp_path / "s"
    (sdir / "input" / "frames").mkdir(parents=True)
    n = 30
    poses = np.tile(np.eye(4), (n, 1, 1))
    for i in range(n):  # walking north along x=0, camera looking north (+y), 1 m apart
        poses[i, :3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]  # columns: right=x, down=-z, forward=+y
        poses[i, :3, 3] = [0, i, 1.4]
        (sdir / "input" / "frames" / f"{i:06d}.jpg").write_bytes(b"x")
    np.savez(tmp_path / "recon.npz", poses=poses)
    (sdir / "input" / "boxes.json").write_text('{"boxes": {"15": [[10, 20, 110, 90]]}}')
    monkeypatch.setattr(store, "survey_dir", lambda pid, sid: sdir)
    monkeypatch.setattr(store, "recon_path", lambda pid, sid: tmp_path / "recon.npz")
    jobcard._poses.cache_clear()
    ph = jobcard.best_frame("p", "s", {"x": 0.3, "y": 20.0, "z": 0.0})
    assert ph["frame"] in (15, 16) and ph["url"].endswith(f"/frames/{ph['frame']}")
    assert jobcard.best_frame("p", "s", {"x": 40.0, "y": 0.0, "z": 0.0}) is None  # never in view


def test_survey_findings_carry_a_cost_and_open_a_card():
    import time

    c = client_for("tester")
    proj = c.post("/api/demo").json()
    deadline = time.time() + 300
    while time.time() < deadline:
        svs = c.get(f"/api/projects/{proj['id']}").json()["survey_list"]
        if all(s["status"] in ("done", "error") for s in svs):
            break
        time.sleep(1)
    sid = svs[0]["id"]
    an = c.get(f"/api/projects/{proj['id']}/surveys/{sid}/analysis").json()
    pots = [f for f in an["findings"] if f["type"] == "pothole"]
    assert pots and all(f["cost"] and f["cost"]["materials_cost"] > 0 for f in pots)
    assert all(f["cost"] is None for f in an["findings"] if f["type"] not in jobcard.COSTED)
    card = c.get(f"/api/projects/{proj['id']}/surveys/{sid}/findings/{pots[0]['id']}/card").json()
    assert card["cost"]["subtotal"] == pots[0]["cost"]["materials_cost"]
    assert card["kind"] == "finding" and card["location"]["tiles"]
    ranked = c.get(f"/api/priority?project={proj['id']}&survey={sid}").json()["items"]
    assert any(i.get("materials") for i in ranked if i["kind"] == "finding")
    other = client_for("admin")  # same company: allowed; the route sits under the project guard
    assert other.get(f"/api/projects/{proj['id']}/surveys/{sid}/findings/nope/card").status_code == 404

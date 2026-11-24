"""The detector and LingBot-Map together, and the 3D check that lets people verify a finding.

A demo street is imported as a decoded scan whose points around one planted pothole carry the
detector's "pothole" label, as adapters/lingbot_map.py writes them from the detector's boxes.
"""

import json
import time

import numpy as np
import pytest

from civil import check3d
from civil.decoders.demo import _TO_DECODER, DemoDecoder, build_scene
from civil.pointcloud import Reconstruction, write_ply

from helpers import admin


@pytest.fixture(scope="module")
def labelled_survey(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("labelled")
    rec = DemoDecoder().decode(tmp, tmp, {})
    _, _, truth = build_scene(repaired=False, seed=7, density=1.0)
    pot = next(t for t in truth if t[0] == "pothole")
    enu = rec.points.astype(np.float64) @ _TO_DECODER   # back from the decoder frame (orthonormal)
    near = np.hypot(enu[:, 0] - pot[1], enu[:, 1] - pot[2]) < 0.45
    labels = np.where(near, 1, -1).astype(np.int32)
    write_ply(tmp / "points.ply", rec.points.astype("f4"), rec.colors, labels)
    (tmp / "labels.json").write_text(json.dumps({"1": "pothole"}))
    (tmp / "poses.json").write_text(json.dumps({"poses": rec.poses.tolist(), "times": rec.times.tolist()}))
    (tmp / "gps.csv").write_text("\n".join(["t,lat,lon"] + [f"{t},{la},{lo}" for t, la, lo in rec.gps]))
    a = admin()
    proj = a.post("/api/projects", json={"name": "check3d", "origin_lat": 13.8196, "origin_lon": 100.5137}).json()
    files = [("files", (n, open(tmp / n, "rb"))) for n in ("points.ply", "labels.json", "poses.json", "gps.csv")]
    sv = a.post(f"/api/projects/{proj['id']}/surveys", data={"name": "labelled", "decoder": "ply_import",
                "params": json.dumps({"up_axis": "auto", "metric": True})}, files=files).json()
    deadline = time.time() + 300
    while time.time() < deadline:
        st = a.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}").json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(1)
    assert st["status"] == "done", st.get("error")
    an = a.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/analysis").json()
    return a, proj["id"], sv["id"], an, int(near.sum())


def test_detector_points_and_a_measured_dip_become_one_confirmed_pothole(labelled_survey):
    _, _, _, an, _ = labelled_survey
    both = [f for f in an["findings"] if f.get("source") == "detector+geometry"]
    assert len(both) == 1 and both[0]["type"] == "pothole" and both[0]["metrics"].get("depth_max_m")


def test_the_3d_check_shows_the_evidence(labelled_survey):
    a, pid, sid, an, n_marked = labelled_survey
    f = next(f for f in an["findings"] if f.get("source") == "detector+geometry")
    c = a.get(f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/check").json()
    assert c["verdict"]["code"] == "both"
    assert c["detector_points_inside"] > 0 and c["detector_points"] <= n_marked
    # the independent re-measurement agrees with the survey's depth within 3 cm on clean synthetic data
    assert abs(c["lowest_below_plane_m"] - c["measured_depth_m"]) < 0.03
    for panel, url in c["images"].items():
        r = a.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG", panel
    assert a.get(f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}/check.png?panel=nope").status_code == 400
    assert a.get(f"/api/projects/{pid}/surveys/{sid}/findings/NOPE-1/check").status_code == 404


def test_a_geometry_only_finding_says_so(labelled_survey):
    a, pid, sid, an, _ = labelled_survey
    g = next(f for f in an["findings"] if f.get("source") == "geometry" and f["type"] in ("pothole", "depression", "sunken_manhole"))
    c = a.get(f"/api/projects/{pid}/surveys/{sid}/findings/{g['id']}/check").json()
    assert c["verdict"]["code"] == "geometry_only" and c["detector_points"] == 0


def test_engineers_mark_the_check_and_it_is_kept(labelled_survey):
    a, pid, sid, an, _ = labelled_survey
    f = next(f for f in an["findings"] if f.get("source") == "detector+geometry")
    base = f"/api/projects/{pid}/surveys/{sid}/findings/{f['id']}"
    assert a.post(f"{base}/review", json={"verdict": "maybe"}).status_code == 400
    r = a.post(f"{base}/review", json={"verdict": "wrong", "note": "a shadow"}).json()
    assert r["review"]["verdict"] == "wrong" and r["review"]["by"] == "admin" and r["review"]["note"] == "a shadow"
    again = a.get(f"{base}/check").json()["review"]
    assert again["verdict"] == "wrong"
    hist = next(x for x in a.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()["findings"] if x["id"] == f["id"])["history"]
    assert hist[-1]["event"] == "3D check: wrong"


def test_the_3d_view_gets_the_detector_labels(labelled_survey):
    a, pid, sid, _, n_marked = labelled_survey
    r = a.get(f"/api/projects/{pid}/surveys/{sid}/points.bin?max_points=20000")
    n = int(r.headers["X-Point-Count"])
    assert r.headers["X-Labels"] == "detector" and len(r.content) == n * 16
    lab = np.frombuffer(r.content[n * 15:], np.uint8)
    # every marked point is kept, even though the cloud was thinned to ~20k points
    assert int(lab.sum()) == int(r.headers["X-Detector-Points"]) == n_marked


def test_pothole_mask_ignores_unlabelled_points():
    rec = Reconstruction(points=np.zeros((4, 3)), labels=np.array([-1, 0, 1, 1]), label_names={1: "pothole", 0: "sign_stop"})
    assert check3d.pothole_mask(rec).tolist() == [False, False, True, True]
    assert check3d.pothole_mask(Reconstruction(points=np.zeros((2, 3)))) is None


def test_the_point_cloud_downloads_as_a_ply_with_the_detector_marks(labelled_survey, tmp_path):
    from civil import store
    from civil.check3d import pothole_mask
    from civil.pointcloud import read_ply

    a, pid, sid, _, _ = labelled_survey
    r = a.get(f"/api/projects/{pid}/surveys/{sid}/export.ply")
    assert r.status_code == 200 and r.content.startswith(b"ply\n")
    assert f'filename="iscale-3d-{sid}.ply"' in r.headers["content-disposition"]
    head = r.content[: r.content.index(b"end_header")].decode()
    assert "property uchar detector" in head and "comment origin_lat" in head
    (tmp_path / "c.ply").write_bytes(r.content)
    xyz, rgb, _ = read_ply(tmp_path / "c.ply")
    rec = Reconstruction.load(store.recon_path(pid, sid))
    assert len(xyz) == rec.n and rgb is not None             # every point, not the thinned view
    assert np.allclose(xyz, rec.points, atol=1e-4)
    n_hdr = len(r.content[: r.content.index(b"end_header\n") + 11])
    rows = np.frombuffer(r.content[n_hdr:], dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                                   ("red", "u1"), ("green", "u1"), ("blue", "u1"),
                                                   ("detector", "u1")])
    assert (rows["detector"].astype(bool) == pothole_mask(rec)).all() and rows["detector"].sum() > 0


def test_thermal_panel_ignores_unobserved_nan_points():
    """Points no thermal frame saw carry NaN; stats and the panel must use only observed points."""
    import numpy as np
    from civil.check3d import _evidence as evaluate, render

    rng = np.random.default_rng(0)
    xy = rng.uniform(-1.5, 1.5, (4000, 2))
    r = np.hypot(xy[:, 0], xy[:, 1])
    z = np.where(r < 0.4, -0.05, 0.0)
    pts = np.column_stack([xy, z]).astype(np.float32)
    temps = np.where(r < 0.4, 35.0, 30.0).astype(np.float32)
    temps[xy[:, 0] > 1.0] = np.nan  # strip never seen by the thermal camera

    from civil.pointcloud import Reconstruction
    rec = Reconstruction(points=pts, temperatures_c=temps, meta={"metric": True})
    f = {"x": 0.0, "y": 0.0, "z": 0.0, "metrics": {"diameter_m": 0.8, "depth_max_m": 0.05}}
    ev = evaluate(rec, f)
    st = ev["thermal_stats"]
    assert all(np.isfinite(v) for v in st.values()), st
    assert st["max_c"] == 35.0 and st["min_c"] == 30.0
    assert render(f, ev, "thermal")[:8] == b"\x89PNG\r\n\x1a\n"

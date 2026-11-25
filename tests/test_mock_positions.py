"""Sukhumvit sample: potholes sit on the road, not at the phone's drifting GPS fix."""

import json

import numpy as np

from civil import mock_import as m
from civil.analysis import PATH_STEP
from civil.analysis.segments import resample_path, station_offset
from civil.pointcloud import latlon_to_enu


def _path():
    summary, route = m._load()
    pots = summary["potholes"]
    lat0, lon0 = pots[0]["latitude"], pots[0]["longitude"]
    x, y = latlon_to_enu(np.array([c[1] for c in route]), np.array([c[0] for c in route]), lat0, lon0)
    return pots, resample_path(np.stack([x, y], 1), PATH_STEP), lat0, lon0


def test_every_pothole_is_on_the_carriageway():
    pots, path, lat0, lon0 = _path()
    for p in pots:
        x, y = m.on_road(p, path, lat0, lon0)
        _, _, off = station_offset(np.array([[x, y]]), path, PATH_STEP)
        assert abs(off[0]) <= m.MAX_LATERAL_M + 0.05, p["id"]


def test_pothole_is_ahead_of_where_the_phone_saw_it():
    pots, path, lat0, lon0 = _path()
    for p in pots:
        px, py = latlon_to_enu(np.array([p["latitude"]]), np.array([p["longitude"]]), lat0, lon0)
        _, phone_st, phone_off = station_offset(np.array([[px[0], py[0]]]), path, PATH_STEP)
        x, y = m.on_road(p, path, lat0, lon0)
        _, st, _ = station_offset(np.array([[x, y]]), path, PATH_STEP)
        assert abs(phone_off[0]) > 15  # the raw fixes really are off the road (why this exists)
        assert st[0] >= phone_st[0] - 0.5, p["id"]



def test_detection_image_is_served_next_to_the_clean_crop():
    from helpers import client_for

    c = client_for("sukh-det")
    proj = c.post("/api/demo/sukhumvit").json()
    pid, sid = proj["id"], proj["baseline"]
    f = c.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()["findings"][0]
    assert f["photo"] is True and f["detection_photo"] is True
    base = f"/api/projects/{pid}/surveys/{sid}/findings"
    crop, det = c.get(f"{base}/{f['id']}/photo"), c.get(f"{base}/{f['id']}/detection")
    assert crop.status_code == det.status_code == 200 and det.headers["content-type"] == "image/jpeg"
    assert crop.content != det.content and det.content[:2] == b"\xff\xd8"
    assert c.get(f"{base}/..%2Fx/detection").status_code == 404
    assert c.get(f"{base}/F000-9999/detection").status_code == 404


def test_sukhumvit_is_a_main_road_with_a_night_repair_window():
    from helpers import client_for

    c = client_for("sukh-road")
    proj = c.post("/api/demo/sukhumvit").json()
    pid, sid = proj["id"], proj["baseline"]
    an = c.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()
    assert all(s["traffic"]["highway"] == "primary" for s in an["segments"])
    card = c.get(f"/api/projects/{pid}/surveys/{sid}/findings/{an['findings'][0]['id']}/card").json()
    assert "22:00" in json.dumps(card["timing"])

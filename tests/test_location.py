"""Opt-in location: the agreement, the switch, GPS pins, recorded drive tracks."""

import json
from fractions import Fraction

import numpy as np
import pytest

from civil import location, pipeline, store

from helpers import admin, client_for


@pytest.fixture(autouse=True)
def no_processing(monkeypatch):
    monkeypatch.setattr(pipeline, "submit", lambda pid, sid: None)


def version(c):
    return c.get("/api/location").json()["version"]


def consent(c, decision, v=None):
    return c.post("/api/location/consent", json={"decision": decision, "version": v or version(c)})


def device_pin(c, lat=13.75, lon=100.5, acc=4.2):
    return c.post("/api/pins", json={"lat": lat, "lon": lon, "type": "pothole", "source": "device", "accuracy_m": acc})


def test_new_person_is_asked_and_location_is_off():
    c = client_for("loc.new")
    s = c.get("/api/location").json()
    assert s["ask"] is True and s["enabled"] is False and s["decision"] is None
    assert "Using your location in iScale" in s["text"] and "Test Works Dept" in s["text"]  # the controller is filled in
    assert "การใช้ตำแหน่งของคุณ" in s["text_th"] and "Test Works Dept" in s["text_th"]
    assert "{" not in s["text"] + s["text_th"]  # every placeholder is filled


def test_decline_is_remembered_and_blocks_gps_pins_but_not_map_pins():
    c = client_for("loc.decliner")
    s = consent(c, "declined").json()
    assert s["ask"] is False and s["enabled"] is False
    assert device_pin(c).status_code == 403
    r = c.post("/api/pins", json={"lat": 13.7501, "lon": 100.5001, "type": "pothole"})
    assert r.status_code == 200 and r.json()["source"] == "map" and r.json()["accuracy_m"] is None


def test_accept_turns_it_on_and_gps_pins_keep_their_accuracy():
    c = client_for("loc.acceptor")
    assert consent(c, "accepted", v="1999-01-01").status_code == 409  # an older text can't be accepted
    assert consent(c, "accepted").json()["enabled"] is True
    r = device_pin(c, lat=13.7602, lon=100.5102, acc=3.456)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "device" and r.json()["accuracy_m"] == 3.5


def test_withdraw_stops_it_and_every_answer_is_logged():
    c = client_for("loc.withdrawer")
    consent(c, "accepted")
    s = consent(c, "withdrawn").json()
    assert s["enabled"] is False and s["ask"] is False  # not nagged again after turning it off
    assert device_pin(c, lat=13.77, lon=100.52).status_code == 403
    assert [h["decision"] for h in c.get("/api/location/history").json()] == ["withdrawn", "accepted"]


def test_a_new_agreement_version_asks_again(tmp_path, monkeypatch):
    c = client_for("loc.reask")
    consent(c, "accepted")
    newer = tmp_path / "agreement.md"
    newer.write_text(location.AGREEMENT_FILE.read_text().replace("version: ", "version: 9", 1))
    monkeypatch.setattr(location, "AGREEMENT_FILE", newer)
    s = c.get("/api/location").json()
    assert s["enabled"] is False and s["ask"] is True
    # the Thai file still has the old version: it is not shown as the current text
    assert "Using your location in iScale" in s["text_th"]


def test_privacy_contact_only_by_the_host_admin():
    a = admin()
    assert client_for("loc.eng").put("/api/location/contact", json={"contact": "x"}).status_code == 403
    s = a.put("/api/location/contact", json={"contact": "privacy@test.example", "address": "1 Test Rd, Bangkok 10110"}).json()
    assert "privacy@test.example" in s["text"] and "1 Test Rd, Bangkok 10110" in s["text_th"]


def _upload(c, pid, track=None, extra_csv=False):
    files = [("files", ("drive.webm", b"not really a video", "video/webm"))]
    if extra_csv:
        files.append(("files", ("gps.csv", b"t,lat,lon\n0,1,1\n", "text/csv")))
    data = {"name": "Drive", "decoder": "demo", "params": "{}", "recorded": "true"}
    if track is not None:
        data["device_track"] = json.dumps(track)
    return c.post(f"/api/projects/{pid}/surveys", data=data, files=files)


TRACK = [[0, 13.7, 100.5, 4], [1.0, 13.70001, 100.5, 5], ["bad"], [2.0, 91, 100.5, 3], [1.5, 13.8, 100.6, 65],
         [2.0, 13.70002, 100.5, 4]]


def test_recorded_drive_track_needs_consent_and_becomes_gps_csv():
    a = admin()
    pid = a.post("/api/projects", json={"name": "Loc drive", "origin_lat": 13.7, "origin_lon": 100.5}).json()["id"]
    consent(a, "withdrawn")
    assert _upload(a, pid, TRACK).status_code == 403
    consent(a, "accepted")
    r = _upload(a, pid, TRACK, extra_csv=True)
    assert r.status_code == 200, r.text
    sv = r.json()
    assert sv["params"]["recorded"] is True and sv["params"]["device_gps_by"]
    inp = store.survey_dir(pid, sv["id"]) / "input"
    assert sorted(p.name for p in inp.iterdir()) == ["drive.webm", "gps.csv"]  # the uploaded csv was dropped
    from civil.pointcloud import read_gps_csv

    g = read_gps_csv(inp / "gps.csv")
    assert g.shape == (3, 3) and g[:, 0].tolist() == [0.0, 1.0, 2.0]  # bad rows, latitude 91 and the ±65 m fix are gone
    assert a.get("/api/location").json()["my_tracks"] == 1
    # a colleague can't delete someone else's track
    assert client_for("loc.colleague").post("/api/location/forget-tracks").json()["deleted"] == 0
    assert a.post("/api/location/forget-tracks").json()["deleted"] == 1
    assert not (inp / "gps.csv").exists()


def test_turning_location_off_deletes_my_drive_tracks():
    a = admin()
    pid = a.post("/api/projects", json={"name": "Loc withdraw", "origin_lat": 13.7, "origin_lon": 100.5}).json()["id"]
    consent(a, "accepted")
    sv = _upload(a, pid, TRACK).json()
    track = store.survey_dir(pid, sv["id"]) / "input" / "gps.csv"
    assert track.exists()
    r = consent(a, "withdrawn").json()
    assert r["tracks_deleted"] == 1 and not track.exists() and r["enabled"] is False


def test_recording_without_location_still_uploads():
    a = admin()
    pid = a.post("/api/projects", json={"name": "Loc no gps", "origin_lat": 13.7, "origin_lon": 100.5}).json()["id"]
    r = _upload(a, pid)
    assert r.status_code == 200 and "device_gps_by" not in r.json()["params"]


def test_browser_recording_becomes_constant_frame_rate(tmp_path):
    """A variable-frame-rate WebM (as phones record) -> 30 fps MP4 where frame k shows time k/30."""
    av = pytest.importorskip("av")
    import cv2

    from civil.video.normalize import normalize_recording

    src = tmp_path / "rec.webm"
    times = [0.0, 0.05, 0.2, 0.25, 0.6, 0.62, 1.0, 1.5, 1.52, 2.0]  # irregular, like a phone under load
    with av.open(str(src), "w") as out:
        st = out.add_stream("libvpx", rate=1000)
        st.width, st.height, st.pix_fmt = 64, 48, "yuv420p"
        st.codec_context.time_base = Fraction(1, 1000)
        for i, t in enumerate(times):
            img = np.full((48, 64, 3), i * 25, np.uint8)
            f = av.VideoFrame.from_ndarray(img, format="rgb24")
            f.pts, f.time_base = int(t * 1000), Fraction(1, 1000)
            for p in st.encode(f):
                out.mux(p)
        for p in st.encode():
            out.mux(p)
    dst = tmp_path / "out.mp4"
    info = normalize_recording(src, dst)
    cap = cv2.VideoCapture(str(dst))
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 30) < 0.01
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert n == info["frames"] and 60 <= n <= 62
    frames = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        frames.append(int(im.mean()))
    # at 0.7 s (frame 21) the picture is the one recorded at 0.62 s (index 5, level 125)
    assert abs(frames[21] - 125) < 8
    # at 1.6 s (frame 48) it is the one from 1.52 s (index 8, level 200)
    assert abs(frames[48] - 200) < 8


def test_upright_applies_the_phone_rotation_flag():
    from civil.video.normalize import _upright

    img = np.arange(6, dtype=np.uint8).reshape(2, 3, 1).repeat(3, axis=2)  # 2 rows x 3 columns
    assert _upright(img, 0) is img
    r = _upright(img, -90)  # upright portrait stored as landscape: turn a quarter clockwise
    assert r.shape == (3, 2, 3) and r[0, 0, 0] == 3 and r[0, 1, 0] == 0
    assert _upright(img, 180).shape == (2, 3, 3) and _upright(img, 180)[0, 0, 0] == 5


def test_audio_only_recording_gets_a_clear_error(tmp_path):
    av = pytest.importorskip("av")
    from civil.video.normalize import normalize_recording

    src = tmp_path / "a.webm"
    with av.open(str(src), "w") as out:
        st = out.add_stream("libopus", rate=48000)
        for i in range(10):
            fr = av.AudioFrame.from_ndarray(np.zeros((1, 960), np.float32), format="flt", layout="mono")
            fr.sample_rate, fr.pts = 48000, i * 960
            for p in st.encode(fr):
                out.mux(p)
        for p in st.encode():
            out.mux(p)
    with pytest.raises(ValueError, match="no video"):
        normalize_recording(src, tmp_path / "o.mp4")

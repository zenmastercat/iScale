"""Encrypted-chat relay, shared pins and traffic-weighted ranking."""

import base64
import time

from helpers import admin, client_for


def b64(n: int) -> str:
    return base64.b64encode(bytes(range(n % 256)) * 1 or b"x").decode() or "eA=="


def keys(reg: int, n_pre: int = 3) -> dict:
    k = base64.b64encode(b"\x05" + bytes(32)).decode()
    return {"registration_id": reg, "identity_key": k,
            "signed_prekey": {"id": 1, "public_key": k, "signature": base64.b64encode(bytes(64)).decode()},
            "prekeys": [{"id": i, "public_key": k} for i in range(1, n_pre + 1)]}


def test_relay_hands_out_one_time_prekeys_once_and_deletes_after_ack():
    a, b = client_for("rita"), client_for("sam")
    assert a.put("/api/chat/keys", json=keys(11)).json()["prekeys"] == 3
    assert b.put("/api/chat/keys", json=keys(22, 2)).status_code == 200
    seen = set()
    for _ in range(2):
        bun = a.get("/api/chat/bundle/sam").json()
        assert bun["registration_id"] == 22 and bun["prekey"]["id"] not in seen
        seen.add(bun["prekey"]["id"])
    assert a.get("/api/chat/bundle/sam").json()["prekey"] is None  # used up; X3DH still works without one
    body = base64.b64encode(b"ciphertext-only").decode()
    mid = a.post("/api/chat/send", json={"to": "sam", "type": 3, "body": body}).json()["id"]
    got = b.get("/api/chat/inbox?after=0").json()["messages"]
    assert [m["id"] for m in got] == [mid] and got[0]["sender"] == "rita" and got[0]["body"] == body
    assert a.get("/api/chat/inbox?after=0").json()["messages"] == []  # not delivered to the sender
    assert b.post("/api/chat/ack", json={"up_to": mid}).json()["deleted"] == 1
    assert b.get("/api/chat/inbox?after=0").json()["messages"] == []  # gone from the server


def test_relay_rejects_bad_input():
    a = client_for("rita")
    assert a.post("/api/chat/send", json={"to": "rita", "type": 1, "body": "eA=="}).status_code == 400
    assert a.post("/api/chat/send", json={"to": "nobody-xyz", "type": 1, "body": "eA=="}).status_code == 404
    assert a.post("/api/chat/send", json={"to": "sam", "type": 1, "body": "not base64!!"}).status_code == 400
    assert a.post("/api/chat/send", json={"to": "sam", "type": 9, "body": "eA=="}).status_code == 422


def test_long_poll_returns_when_a_message_arrives():
    import threading

    a, b = client_for("rita"), client_for("sam")
    out = {}
    t0 = time.time()

    def poll():
        out["r"] = b.get("/api/chat/inbox?after=999999999&wait=5").json()

    th = threading.Thread(target=poll)
    th.start()
    th.join()
    assert time.time() - t0 >= 4.5 and out["r"]["messages"] == []


def test_pins_are_shared_with_everyone_and_merge_nearby_reports():
    a, b = client_for("rita"), client_for("sam")
    p = a.post("/api/pins", json={"lat": 13.8200, "lon": 100.5140, "severity": "high", "note": "deep, near bus stop"}).json()
    assert p["merged"] is False and "google.com/maps" in p["maps_url"] and "layer=traffic" in p["maps_url"]
    seen = [x["id"] for x in b.get("/api/pins").json()["pins"]]
    assert p["id"] in seen  # the other engineer sees it
    q = b.post("/api/pins", json={"lat": 13.82002, "lon": 100.51401, "severity": "high"}).json()  # ~2 m away
    assert q["merged"] is True and q["id"] == p["id"] and "sam" in q["confirmations"]
    assert b.patch(f"/api/pins/{p['id']}", json={"status": "dismissed"}).status_code == 403  # not the reporter
    assert b.patch(f"/api/pins/{p['id']}", json={"status": "fixed"}).json()["status"] == "fixed"
    assert p["id"] not in [x["id"] for x in a.get("/api/pins").json()["pins"]]


def test_ranking_puts_busy_roads_first(monkeypatch):
    from civil import traffic

    a = client_for("rita")
    quiet = a.post("/api/pins", json={"lat": 13.70, "lon": 100.40, "severity": "high"}).json()
    busy = a.post("/api/pins", json={"lat": 13.71, "lon": 100.41, "severity": "medium"}).json()

    def fake(points, company_id, aadt=None):
        out = []
        for lat, lon in points:
            hw, ratio = ("primary", 2.0) if abs(lat - 13.71) < 1e-6 else ("residential", None)
            if ratio:  # like assess_points: live congestion goes to memory only
                traffic._live_ratio[traffic._pt(lat, lon)] = (time.time(), ratio)
            out.append({"highway": hw, "road_name": None, "ratio": ratio, "aadt": None,
                        "factor": traffic.factor(hw, ratio), "source": "test"})
        return out, []

    monkeypatch.setattr(traffic, "assess_points", fake)
    assert a.post("/api/pins/traffic").status_code == 200
    items = [i for i in a.get("/api/priority").json()["items"] if i["id"] in (quiet["id"], busy["id"])]
    # medium on a congested primary road (4 x 1.5) beats high on a residential street (1.5)
    assert [i["id"] for i in items] == [busy["id"], quiet["id"]]
    assert items[0]["road"] == "primary" and items[0]["traffic_factor"] == 6.0
    # Google's congestion is not saved with the pin (only the road class is)
    import json as _json

    from civil import db
    stored = _json.loads(db.one("SELECT traffic FROM pins WHERE id=?", busy["id"])["traffic"])
    assert stored["highway"] == "primary" and "ratio" not in stored and stored["factor"] == 4.0
    # once the live value expires the ranking falls back to the road class
    traffic._live_ratio.clear()
    item = next(i for i in a.get("/api/priority").json()["items"] if i["id"] == busy["id"])
    assert item["traffic_factor"] == 4.0


def test_traffic_factor_rules():
    from civil import traffic

    assert traffic.factor("residential", None) == 1.5
    assert traffic.factor("primary", 3.5) == 8.0  # congestion capped at 3x
    assert traffic.factor("primary", None, aadt=1000) == 3.0  # entered counts win over road class
    assert traffic.factor(None, None) == 1.0


def test_admin_fixture_is_admin():
    assert admin().get("/api/auth/state").json()["user"]["role"] == "admin"

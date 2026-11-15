"""XMPP chat plumbing (tokens, addresses, WebSocket gate, ejabberd config), shared pins and
traffic-weighted ranking. The OMEMO encryption itself runs in the browser and is checked there."""

import base64
import hashlib
import hmac
import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from civil import xmpp
from helpers import admin, client_for


def _jwt_claims(tok: str) -> dict:
    head, body, sig = tok.split(".")
    want = base64.urlsafe_b64encode(hmac.new(xmpp.jwt_secret(), f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert hmac.compare_digest(sig, want), "token not signed with the ejabberd key"
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def test_chat_token_is_a_short_lived_jwt_for_your_own_hashed_address():
    a = client_for("rita")
    t = a.get("/api/xmpp/token").json()
    claims = _jwt_claims(t["token"])
    assert claims["jid"] == t["jid"] and t["jid"].endswith("@" + xmpp.DOMAIN)
    assert "rita" not in t["jid"]                          # the server only sees a hash
    assert 0 < claims["exp"] - time.time() <= xmpp.TOKEN_TTL
    assert t["websocket"] == "/xmpp" and t["running"] is False   # tests never reach ejabberd


def test_chat_token_needs_a_signed_in_user():
    from fastapi.testclient import TestClient

    from civil.api import app
    assert TestClient(app, headers={"X-Civil-Scan": "1"}).get("/api/xmpp/token").status_code == 401


def test_username_to_address_and_back():
    a, _ = client_for("rita"), client_for("sam")
    p = a.get("/api/xmpp/jid?username=sam").json()
    assert p["username"] == "sam" and p["jid"].endswith("@" + xmpp.DOMAIN)
    assert a.get(f"/api/xmpp/whois?jid={p['jid']}/web-1234").json()["username"] == "sam"
    assert a.get("/api/xmpp/jid?username=nobody-xyz").status_code == 404
    assert a.get("/api/xmpp/whois?jid=sam@evil.example").status_code == 404


def test_websocket_gate_refuses_strangers_and_other_sites():
    from fastapi.testclient import TestClient

    from civil.api import app
    anon = TestClient(app, headers={"X-Civil-Scan": "1"})
    with pytest.raises(WebSocketDisconnect) as e:
        with anon.websocket_connect("/xmpp", subprotocols=["xmpp"]) as ws:
            ws.receive_text()
    assert e.value.code == 4401
    a = client_for("rita")
    with pytest.raises(WebSocketDisconnect) as e:
        with a.websocket_connect("/xmpp", subprotocols=["xmpp"], headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()
    assert e.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as e:   # signed in, same site, but ejabberd is down: "try again later"
        with a.websocket_connect("/xmpp", subprotocols=["xmpp"]) as ws:
            ws.receive_text()
    assert e.value.code == 1013


def test_ejabberd_config_is_local_only_and_keeps_no_archive():
    y = xmpp.config_yaml()
    assert 'ip: "127.0.0.1"' in y and "s2s:\n    deny: all" in y
    assert "mam: false" in y and "mod_mam" not in y            # no message archive on the server
    assert "  - jwt" in y and "muc_create:\n    deny: all" in y   # only iScale creates rooms
    assert "members_only: true" in y and "anonymous: false" in y


def test_chat_sign_in_gives_ejabberd_an_account_entry_once(monkeypatch):
    """JWT alone can't tell ejabberd a person exists, and it would bounce their offline messages."""
    calls = []

    def fake_api(cmd, **kw):
        calls.append((cmd, kw.get("user")))
        return 1 if cmd == "check_account" else 0
    monkeypatch.setattr(xmpp, "api", fake_api)
    monkeypatch.setattr(xmpp, "_accounts", set())
    a = client_for("rita")
    uid = a.get("/api/xmpp/token").json()["jid"].split("@")[0]
    a.get("/api/xmpp/token")
    assert calls == [("check_account", uid), ("register", uid)]   # second sign-in: cached, no calls
    y = xmpp.config_yaml()
    assert "auth_method:\n  - jwt\n  - internal" in y and "mod_register" not in y   # no self-registration


def test_group_rooms_follow_membership(monkeypatch):
    calls = []
    monkeypatch.setattr(xmpp, "ensure_room", lambda gid, name, uids, owner=None: calls.append((gid, name, set(uids), owner)))
    monkeypatch.setattr(xmpp, "drop_room", lambda gid: calls.append((gid, None, None, None)))
    a = admin()
    client_for("rita"), client_for("sam")
    g = a.post("/api/groups", json={"name": "Night crew", "members": ["rita"]}).json()
    assert g["jid"] == f"g{g['id']}@{xmpp.MUC}" and all(m["jid"].endswith(xmpp.DOMAIN) for m in g["members"])
    assert calls[-1][1] == "Night crew" and len(calls[-1][2]) == 2
    a.post(f"/api/groups/{g['id']}/members", json={"usernames": ["sam"]})
    assert len(calls[-1][2]) == 3
    a.delete(f"/api/groups/{g['id']}")
    assert calls[-1] == (g["id"], None, None, None)


def test_group_changes_still_work_while_ejabberd_is_down():
    a = admin()
    client_for("rita")
    r = a.post("/api/groups", json={"name": "Offline crew", "members": ["rita"]})
    assert r.status_code == 200, r.text   # synced on next xmpp.start()


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

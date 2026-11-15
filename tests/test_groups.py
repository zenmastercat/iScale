"""Group chats: admins create them, the relay delivers per-member ciphertext to members only."""

import base64

from helpers import admin, client_for
from test_messaging import keys

CT = base64.b64encode(b"per-member ciphertext").decode()


def _ready(*names):
    cs = [client_for(n) for n in names]
    for i, c in enumerate(cs):
        assert c.put("/api/chat/keys", json=keys(100 + i)).status_code == 200
    return cs


def test_only_admins_create_groups_and_members_see_them():
    a = admin()
    assert a.put("/api/chat/keys", json=keys(99)).status_code == 200
    gina, hal, ivy = _ready("gina", "hal", "ivy")
    assert gina.post("/api/groups", json={"name": "Crew", "members": ["hal"]}).status_code == 403
    r = a.post("/api/groups", json={"name": "Night crew", "members": ["gina", "@hal", "gina"]})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["name"] == "Night crew" and g["can_manage"]
    assert sorted(m["username"] for m in g["members"]) == ["admin", "gina", "hal"]
    assert [x["id"] for x in gina.get("/api/groups").json()] == [g["id"]]
    assert gina.get("/api/groups").json()[0]["can_manage"] is False
    assert ivy.get("/api/groups").json() == []
    assert a.post("/api/groups", json={"name": "X", "members": ["nobody-here"]}).status_code == 404
    # the group name is encrypted at rest
    from civil import db
    assert db.one("SELECT name FROM chat_groups WHERE id=?", g["id"])["name"].startswith("v1:")


def test_group_send_reaches_members_only():
    a = admin()
    gina, hal, ivy = _ready("gina", "hal", "ivy")
    g = a.post("/api/groups", json={"name": "Patch team", "members": ["gina", "hal"]}).json()
    copies = [{"to": "gina", "type": 1, "body": CT}, {"to": "hal", "type": 1, "body": CT}]
    assert a.post("/api/chat/send-group", json={"group_id": g["id"], "copies": copies}).json() == {"sent": 2}
    for c in (gina, hal):
        got = [m for m in c.get("/api/chat/inbox?after=0").json()["messages"] if m["group_id"] == g["id"]]
        assert len(got) == 1 and got[0]["sender"] == "admin" and got[0]["body"] == CT
    # a non-member can't post into the group, and members can't send copies to outsiders
    assert ivy.post("/api/chat/send-group", json={"group_id": g["id"], "copies": [{"to": "gina", "type": 1, "body": CT}]}).status_code == 403
    r = gina.post("/api/chat/send-group", json={"group_id": g["id"], "copies": [{"to": "ivy", "type": 1, "body": CT}]})
    assert r.status_code == 403
    dup = [{"to": "hal", "type": 1, "body": CT}] * 2
    assert gina.post("/api/chat/send-group", json={"group_id": g["id"], "copies": dup}).status_code == 400


def test_manage_members_and_leave():
    a = admin()
    gina, hal, ivy = _ready("gina", "hal", "ivy")
    g = a.post("/api/groups", json={"name": "Survey", "members": ["gina"]}).json()
    assert gina.post(f"/api/groups/{g['id']}/members", json={"usernames": ["ivy"]}).status_code == 403
    assert a.post(f"/api/groups/{g['id']}/members", json={"usernames": ["ivy"]}).status_code == 200
    assert g["id"] in [x["id"] for x in ivy.get("/api/groups").json()]
    # removed members lose undelivered copies and can't post
    a.post("/api/chat/send-group", json={"group_id": g["id"], "copies": [{"to": "ivy", "type": 1, "body": CT}]})
    assert gina.delete(f"/api/groups/{g['id']}/members/ivy").status_code == 403
    assert a.delete(f"/api/groups/{g['id']}/members/ivy").status_code == 200
    assert [m for m in ivy.get("/api/chat/inbox?after=0").json()["messages"] if m["group_id"] == g["id"]] == []
    assert ivy.post("/api/chat/send-group", json={"group_id": g["id"], "copies": [{"to": "gina", "type": 1, "body": CT}]}).status_code == 403
    # a member can leave on their own; renaming needs a manager
    assert gina.delete(f"/api/groups/{g['id']}/members/gina").status_code == 200
    assert g["id"] not in [x["id"] for x in gina.get("/api/groups").json()]
    assert hal.patch(f"/api/groups/{g['id']}", json={"name": "Nope"}).status_code == 403
    assert a.patch(f"/api/groups/{g['id']}", json={"name": "Survey crew"}).json()["name"] == "Survey crew"
    assert a.delete(f"/api/groups/{g['id']}").status_code == 200
    assert g["id"] not in [x["id"] for x in a.get("/api/groups").json()]

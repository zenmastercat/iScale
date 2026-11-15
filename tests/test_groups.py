"""Group chats: admins create them; each group is a members-only XMPP room whose member list
iScale keeps in step with the group (ejabberd then refuses anyone else)."""

import pytest

from civil import xmpp
from helpers import admin, client_for


@pytest.fixture
def rooms(monkeypatch):
    """A stand-in for ejabberd's room admin API: room id -> set of member uids."""
    state: dict[str, set] = {}
    monkeypatch.setattr(xmpp, "ensure_room", lambda gid, name, uids, owner=None: state.__setitem__(gid, set(uids)))
    monkeypatch.setattr(xmpp, "drop_room", lambda gid: state.pop(gid, None))
    return state


def _uid(c, username):
    return c.get(f"/api/xmpp/jid?username={username}").json()["jid"].split("@")[0]


def test_only_admins_create_groups_and_members_see_them(rooms):
    a = admin()
    gina, hal, ivy = (client_for(n) for n in ("gina", "hal", "ivy"))
    assert gina.post("/api/groups", json={"name": "Crew", "members": ["hal"]}).status_code == 403
    r = a.post("/api/groups", json={"name": "Night crew", "members": ["gina", "@hal", "gina"]})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["name"] == "Night crew" and g["can_manage"]
    assert sorted(m["username"] for m in g["members"]) == ["admin", "gina", "hal"]
    assert rooms[g["id"]] == {_uid(a, n) for n in ("admin", "gina", "hal")}
    assert [x["id"] for x in gina.get("/api/groups").json()] == [g["id"]]
    assert gina.get("/api/groups").json()[0]["can_manage"] is False
    assert ivy.get("/api/groups").json() == []
    assert a.post("/api/groups", json={"name": "X", "members": ["nobody-here"]}).status_code == 404
    # the group name is encrypted at rest
    from civil import db
    assert db.one("SELECT name FROM chat_groups WHERE id=?", g["id"])["name"].startswith("v1:")


def test_manage_members_and_leave(rooms):
    a = admin()
    gina, hal, ivy = (client_for(n) for n in ("gina", "hal", "ivy"))
    g = a.post("/api/groups", json={"name": "Survey", "members": ["gina"]}).json()
    assert gina.post(f"/api/groups/{g['id']}/members", json={"usernames": ["ivy"]}).status_code == 403
    assert a.post(f"/api/groups/{g['id']}/members", json={"usernames": ["ivy"]}).status_code == 200
    assert g["id"] in [x["id"] for x in ivy.get("/api/groups").json()]
    assert _uid(a, "ivy") in rooms[g["id"]]
    # removing a member takes them out of the room, so ejabberd stops letting them in
    assert gina.delete(f"/api/groups/{g['id']}/members/ivy").status_code == 403
    assert a.delete(f"/api/groups/{g['id']}/members/ivy").status_code == 200
    assert _uid(a, "ivy") not in rooms[g["id"]]
    # a member can leave on their own; renaming needs a manager
    assert gina.delete(f"/api/groups/{g['id']}/members/gina").status_code == 200
    assert g["id"] not in [x["id"] for x in gina.get("/api/groups").json()]
    assert hal.patch(f"/api/groups/{g['id']}", json={"name": "Nope"}).status_code == 403
    assert a.patch(f"/api/groups/{g['id']}", json={"name": "Survey crew"}).json()["name"] == "Survey crew"
    assert a.delete(f"/api/groups/{g['id']}").status_code == 200
    assert g["id"] not in [x["id"] for x in a.get("/api/groups").json()]
    assert g["id"] not in rooms

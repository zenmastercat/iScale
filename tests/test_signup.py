"""Self sign-up: a new company, joining one with a code, and individual accounts."""

import pytest
from fastapi.testclient import TestClient

from civil import auth
from civil.api import app

from helpers import HDR, admin, client_for, device_key, login, spki


@pytest.fixture(autouse=True)
def server_is_set_up(monkeypatch):
    admin()  # the host company exists; self sign-up is refused before setup
    monkeypatch.setattr(auth, "_register_log", {})  # every test client shares one address
    monkeypatch.setattr(auth, "SIGNUP_DEFAULT", {"company": True, "individual": True})  # these tests use open sign-up


def test_no_sign_up_before_the_server_is_set_up(monkeypatch):
    monkeypatch.setattr(auth, "setup_needed", lambda: True)
    assert register("individual", "su.early")[2].status_code == 409


def register(kind, username, **extra):
    c = TestClient(app, headers=HDR)
    key = device_key()
    r = c.post("/api/auth/register", json={"kind": kind, "username": username, "display_name": username.title(),
                                            "public_key": spki(key), **extra})
    return c, key, r


def signed_in(kind, username, **extra):
    c, key, r = register(kind, username, **extra)
    assert r.status_code == 200, r.text
    assert login(c, username, key).status_code == 200
    return c


def test_new_company_makes_you_its_admin_with_a_join_code():
    boss = signed_in("company", "su.boss", company="Rayong Roads Co")
    me = boss.get("/api/auth/state").json()["user"]
    assert me["role"] == "admin" and me["account"] == "company" and me["company"] == "Rayong Roads Co"
    code = boss.get("/api/company").json()["join_code"]
    assert code and len(code) == 9
    # a colleague joins with the code (case and dash don't matter) and lands in the same company as an engineer
    mate = signed_in("join", "su.mate", join_code=code.lower().replace("-", ""))
    them = mate.get("/api/auth/state").json()["user"]
    assert them["role"] == "engineer" and them["company_id"] == me["company_id"]
    assert "join_code" not in mate.get("/api/company").json()  # engineers don't see the code
    assert {u["username"] for u in boss.get("/api/team").json()} == {"su.boss", "su.mate"}


def test_new_code_stops_the_old_one_and_off_stops_joining():
    boss = signed_in("company", "su.boss2", company="Code Test Works")
    old = boss.get("/api/company").json()["join_code"]
    new = boss.post("/api/company/join-code").json()["join_code"]
    assert new != old
    assert register("join", "su.late", join_code=old)[2].status_code == 404
    assert boss.post("/api/company/join-code?off=true").json()["join_code"] is None
    assert register("join", "su.later", join_code=new)[2].status_code == 404


def test_individual_account_is_a_workspace_of_one_that_can_become_a_company():
    solo = signed_in("individual", "su.solo")
    me = solo.get("/api/auth/state").json()["user"]
    assert me["account"] == "individual" and me["company"] == "Independent" and me["role"] == "admin"
    assert solo.post("/api/team", json={"username": "su.helper", "display_name": "H"}).status_code == 400
    assert solo.post("/api/company/join-code").status_code == 400
    # its projects are its own
    assert solo.get("/api/projects").json() == []
    # turn it into a company: gets a join code, and can add people
    out = solo.patch("/api/company", json={"kind": "company", "name": "Solo Surveys"}).json()
    assert out["kind"] == "company" and out["join_code"]
    assert solo.post("/api/team", json={"username": "su.helper", "display_name": "H"}).status_code == 200
    assert solo.patch("/api/company", json={"kind": "individual"}).status_code == 400


def test_registration_binds_the_device_at_once():
    c, key, r = register("individual", "su.bound")
    assert r.status_code == 200
    other = TestClient(app, headers=HDR)
    assert login(other, "su.bound", device_key()).status_code == 403  # someone else's device can't claim it
    assert login(c, "su.bound", key).status_code == 200


def test_bad_input_and_taken_names():
    assert register("company", "su.noname", company="")[2].status_code == 400
    assert register("join", "su.nocode", join_code="ZZZZ-ZZZZ")[2].status_code == 404
    assert register("party", "su.kind")[2].status_code == 400
    assert register("individual", "x")[2].status_code == 400
    signed_in("individual", "su.taken")
    assert register("individual", "su.taken")[2].status_code == 409
    c = TestClient(app, headers=HDR)
    assert c.post("/api/auth/register", json={"kind": "individual", "username": "su.badkey", "display_name": "B",
                                               "public_key": "A" * 60}).status_code == 400


def test_host_admin_controls_which_sign_ups_are_allowed():
    host = admin()
    eng = client_for("su.eng")
    assert eng.put("/api/auth/signup", json={"company": False, "individual": False}).status_code == 403
    other_admin = signed_in("company", "su.other", company="Not The Host")
    assert other_admin.put("/api/auth/signup", json={"company": False, "individual": False}).status_code == 403
    try:
        assert host.put("/api/auth/signup", json={"company": False, "individual": True}).status_code == 200
        assert TestClient(app).get("/api/auth/state").json()["signup"] == {"company": False, "individual": True}
        assert register("company", "su.blocked", company="Blocked Co")[2].status_code == 403
        assert register("join", "su.blocked2", join_code="ABCD-EFGH")[2].status_code == 403
        assert register("individual", "su.allowed")[2].status_code == 200
    finally:
        host.put("/api/auth/signup", json={"company": True, "individual": True})


def test_too_many_accounts_from_one_address_are_refused(monkeypatch):
    monkeypatch.setattr(auth, "REGISTER_LIMIT", (2, 3600))
    monkeypatch.setattr(auth, "_register_log", {})
    assert register("individual", "su.r1")[2].status_code == 200
    assert register("individual", "su.r2")[2].status_code == 200
    assert register("individual", "su.r3")[2].status_code == 429


def test_sign_up_is_closed_by_default(monkeypatch):
    from civil import db

    monkeypatch.setattr(auth, "SIGNUP_DEFAULT", {"company": False, "individual": False})
    saved = db.get_setting("server", "signup", {})
    db.set_setting("server", "signup", {})  # nothing chosen by an admin yet: the default applies
    try:
        assert TestClient(app).get("/api/auth/state").json()["signup"] == {"company": False, "individual": False}
        assert register("individual", "su.closed")[2].status_code == 403
        assert register("company", "su.closed2", company="Closed Co")[2].status_code == 403
    finally:
        db.set_setting("server", "signup", saved)

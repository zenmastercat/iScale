"""Username-only sign-in bound to the device, companies, admin powers, project isolation."""

from fastapi.testclient import TestClient

from civil.api import app
from helpers import HDR, admin, client_for, device_key, login, sign_raw, spki


def test_claim_then_only_that_device_can_sign_in():
    a = admin()
    assert a.post("/api/team", json={"username": "bea", "display_name": "Bea"}).status_code == 200
    k1, k2 = device_key(), device_key()
    c1 = TestClient(app, headers=HDR)
    assert login(c1, "bea", k1).status_code == 200  # first sign-in claims the username
    assert c1.get("/api/auth/state").json()["user"]["username"] == "bea"
    c2 = TestClient(app, headers=HDR)
    r = login(c2, "bea", k2)  # same username, different device
    assert r.status_code == 403 and "another device" in r.json()["detail"]
    assert c2.get("/api/projects").status_code == 401
    # a signature from the wrong key is refused even without sending a public key
    ch = c2.post("/api/auth/challenge", json={"username": "bea"}).json()
    r = c2.post("/api/auth/login", json={"username": "bea", "nonce": ch["nonce"], "signature": sign_raw(k2, ch["message"].encode())})
    assert r.status_code == 403
    # nonce is single-use
    ch = c1.post("/api/auth/challenge", json={"username": "bea"}).json()
    body = {"username": "bea", "nonce": ch["nonce"], "signature": sign_raw(k1, ch["message"].encode()), "public_key": spki(k1)}
    assert c1.post("/api/auth/login", json=body).status_code == 200
    assert c1.post("/api/auth/login", json=body).status_code == 401
    # admin resets the device: a new device can claim it
    assert a.post("/api/team/bea/reset-device").status_code == 200
    assert c1.get("/api/projects").status_code == 401  # old sessions ended
    assert login(c2, "bea", k2).status_code == 200


def test_unknown_and_disabled_usernames():
    a = admin()
    c = TestClient(app, headers=HDR)
    assert c.post("/api/auth/challenge", json={"username": "nobody-here"}).status_code == 404
    assert c.post("/api/auth/challenge", json={"username": "../x"}).status_code == 400
    eng = client_for("cleo")
    assert a.post("/api/team/cleo/disable").status_code == 200
    assert eng.get("/api/projects").status_code == 401


def test_only_admins_manage_the_team_and_setup_runs_once():
    eng = client_for("dan")
    assert eng.post("/api/team", json={"username": "evil", "display_name": "x"}).status_code == 403
    assert eng.get("/api/team").status_code == 200
    c = TestClient(app, headers=HDR)
    assert c.post("/api/auth/setup", json={"company": "Other", "username": "boss", "display_name": "B"}).status_code == 409


def test_projects_are_private_to_a_company():
    from civil import auth as A

    eng = client_for("erin")
    pid = eng.post("/api/projects", json={"name": "Erin's district"}).json()["id"]
    # a second company on the same server
    cid = A.create_company("Other Co")
    A.create_user("oscar", "Oscar", cid, "admin")
    other = TestClient(app, headers=HDR)
    assert login(other, "oscar", device_key()).status_code == 200
    assert all(p["id"] != pid for p in other.get("/api/projects").json())
    assert other.get(f"/api/projects/{pid}").status_code == 404
    assert other.post(f"/api/projects/{pid}/chat", json={"message": "hi"}).status_code == 404
    # but engineers can find each other across companies by exact username
    names = [d["username"] for d in other.get("/api/directory?q=erin").json()]
    assert "erin" in names
    assert "erin" not in [d["username"] for d in other.get("/api/directory?q=eri").json()]


def test_usernames_and_names_are_encrypted_at_rest():
    from civil import db
    from helpers import client_for

    c = client_for("zara.field")
    raw = db.db_path().read_bytes() + (db.db_path().with_name("civil.db-wal").read_bytes()
                                       if db.db_path().with_name("civil.db-wal").exists() else b"")
    assert b"zara.field" not in raw and b"Zara.Field" not in raw
    row = db.one("SELECT username, username_enc, display_name FROM users WHERE username_enc IS NOT NULL LIMIT 1")
    assert row["username"].startswith("u") and row["username_enc"].startswith("v1:") and row["display_name"].startswith("v1:")
    # sign-in, team list and directory still show the real names
    me = c.get("/api/auth/state").json()["user"]
    assert me["username"] == "zara.field" and me["display_name"] == "Zara.Field"
    found = client_for("admin").get("/api/directory?q=zara").json()
    assert [r["username"] for r in found] == ["zara.field"]


def test_plain_accounts_from_older_versions_are_migrated(tmp_path, monkeypatch):
    import sqlite3

    from civil import config, db, vault

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(vault, "DATA_DIR", tmp_path)
    con = sqlite3.connect(tmp_path / "civil.db")
    con.executescript("""
      CREATE TABLE companies (id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL, is_host INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE users (username TEXT PRIMARY KEY, display_name TEXT NOT NULL, company_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'engineer', created REAL NOT NULL, auth_key TEXT, key_set_at REAL, disabled INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL,
        type INTEGER NOT NULL, body TEXT NOT NULL, sent REAL NOT NULL);
      INSERT INTO companies VALUES ('c1', 'Old Co', 0, 1);
      INSERT INTO users(username, display_name, company_id, role, created) VALUES ('olduser', 'Old User', 'c1', 'admin', 0);
      INSERT INTO users(username, display_name, company_id, role, created) VALUES ('other', 'Other', 'c1', 'engineer', 0);
      INSERT INTO messages(sender, recipient, type, body, sent) VALUES ('olduser', 'other', 1, 'AA==', 0);
    """)
    con.commit()
    con.close()
    from civil import auth

    u = auth.get_user("olduser")
    assert u["display_name"] == "Old User" and u["uid"] == vault.uid("olduser")
    m = db.one("SELECT sender, recipient FROM messages")
    assert m == {"sender": vault.uid("olduser"), "recipient": vault.uid("other")}


def test_sign_in_is_rate_limited_per_address(monkeypatch):
    from civil import auth

    monkeypatch.setattr(auth, "SIGNIN_LIMIT", (3, 60))
    c = TestClient(app, headers=HDR)
    codes = [c.post("/api/auth/challenge", json={"username": "nobody.here"}).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]


def test_security_headers():
    r = TestClient(app).get("/api/auth/state")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in r.headers  # only over https

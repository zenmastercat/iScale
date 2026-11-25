"""Username-only sign-in, bound to a device key.

There is no password. The first time a username signs in, the browser creates an
ECDSA P-256 key pair (WebCrypto, private key not extractable) and the server stores the
public key: the username is now bound to that device. Every later sign-in signs a fresh
server nonce with that key. Another device typing the same username is refused until an
admin resets the device. So the person only ever types their username, but knowing a
username is not enough to become that person.

Accounts: the first account on a fresh server is created by the setup screen and becomes the
admin of the host company. After that, people can also create their own account
(POST /auth/register), if the host admin allows it (Settings, Sign-up):
  company     start a new company; the creator is its admin and adds people or shares a join code
  join        join an existing company with the join code its admin shared (role: engineer)
  individual  a one-person workspace; can later be turned into a company
A company admin can still add people by username (POST /team). Registration binds the device
key at once, so nobody can claim a username between "create" and the first sign-in.

Usernames and names are encrypted at rest (vault.py): rows are keyed by `uid`, a keyed hash
of the username. User dicts returned here are decrypted: `username` and `display_name` are
plain, `uid` is the database key. Use `uid` in every SQL query.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, vault

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
COOKIE = "civil_session"
SESSION_DAYS = 30
CHALLENGE_TTL = 120
ROLES = ("admin", "engineer")
KINDS = ("company", "individual")
# Self sign-up is off unless the host admin turns it on (Settings, Sign-up) or the server is started with
# CIVIL_OPEN_SIGNUP=1: on a private server, accounts come from an admin (POST /team), not from strangers.
_OPEN = os.environ.get("CIVIL_OPEN_SIGNUP", "") in ("1", "true", "yes")
SIGNUP_DEFAULT = {"company": _OPEN, "individual": _OPEN}
JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
REGISTER_LIMIT = (10, 3600)  # accounts per client address per hour
_register_log: dict[str, list[float]] = {}
SIGNIN_LIMIT = (30, 60)  # challenge + login requests per client address per minute
_signin_log: dict[str, list[float]] = {}
# Secure cookie: on automatically over https; set CIVIL_SECURE_COOKIE=1 when a TLS proxy in front talks http to us.
SECURE_COOKIE = os.environ.get("CIVIL_SECURE_COOKIE", "") in ("1", "true", "yes")

router = APIRouter(prefix="/api")


def norm_username(u: str) -> str:
    u = (u or "").strip().lower().lstrip("@")
    if not USERNAME_RE.match(u):
        raise HTTPException(400, "usernames are 3-32 characters: letters, digits, dot, dash or underscore")
    return u


def decrypt_user(row) -> dict | None:
    if row is None:
        return None
    u = dict(row)
    u["uid"] = u["username"]
    u["username"] = vault.open_(u.pop("username_enc"), "users.username")
    u["display_name"] = vault.open_(u["display_name"], "users.display_name")
    return u


def get_user(username: str | None = None, *, uid: str | None = None, con=None) -> dict | None:
    """A user by plain (normalised) username or by uid, decrypted."""
    key = uid or vault.uid(username)
    sql = "SELECT * FROM users WHERE username=?"
    row = con.execute(sql, (key,)).fetchone() if con is not None else db.one(sql, key)
    return decrypt_user(row)


def users_where(sql_where: str, *args) -> list[dict]:
    return [decrypt_user(r) for r in db.all_(f"SELECT * FROM users WHERE {sql_where}", *args)]


def person(uid: str | None) -> dict | None:
    """Public card for a uid stored in another table (sender, reporter, ...)."""
    if not uid:
        return None
    u = get_user(uid=uid)
    if not u:
        return None
    comp = db.one("SELECT name, kind FROM companies WHERE id=?", u["company_id"]) or {}
    return {"username": u["username"], "display_name": u["display_name"],
            "company": comp.get("name") if comp.get("kind", "company") == "company" else "Independent",
            "jid": f"{u['uid']}@{_xmpp_domain()}"}


def public_user(u: dict) -> dict:
    comp = db.one("SELECT name, is_host, kind FROM companies WHERE id=?", u["company_id"]) or {}
    kind = comp.get("kind") or "company"
    return {"username": u["username"], "display_name": u["display_name"], "role": u["role"],
            "company_id": u["company_id"], "company": comp.get("name") if kind == "company" else "Independent",
            "account": kind, "host_admin": bool(comp.get("is_host")) and u["role"] == "admin",
            "device_bound": bool(u.get("auth_key")), "disabled": bool(u["disabled"])}


# --- sessions -------------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(response: Response, request: Request, uid: str) -> None:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.run("DELETE FROM sessions WHERE expires<?", now)  # housekeeping: expired sessions are useless
    db.run("INSERT INTO sessions(token_hash, username, created, expires) VALUES(?,?,?,?)",
           _hash(token), uid, now, now + SESSION_DAYS * 86400)
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="strict",
                        secure=SECURE_COOKIE or request.url.scheme == "https", path="/")


def session_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    r = db.one("SELECT u.* FROM sessions s JOIN users u ON u.username=s.username "
               "WHERE s.token_hash=? AND s.expires>? AND u.disabled=0", _hash(token), time.time())
    return decrypt_user(r)


def end_sessions(uid: str) -> None:
    db.run("DELETE FROM sessions WHERE username=?", uid)


# --- signatures ---------------------------------------------------------------------------
def load_key(spki_b64: str) -> ec.EllipticCurvePublicKey:
    try:
        key = serialization.load_der_public_key(base64.b64decode(spki_b64))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "bad public key") from e
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise HTTPException(400, "device key must be ECDSA P-256")
    return key


def login_message(username: str, nonce: str) -> bytes:
    return f"civil-scan-login:{nonce}:{username}".encode()


def verify_sig(key: ec.EllipticCurvePublicKey, msg: bytes, sig_b64: str) -> bool:
    try:
        raw = base64.b64decode(sig_b64)
    except (ValueError, TypeError):
        return False
    if len(raw) == 64:  # WebCrypto gives raw r||s (IEEE P1363)
        raw = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        key.verify(raw, msg, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


# --- models -------------------------------------------------------------------------------
class SetupIn(BaseModel):
    company: str = Field(min_length=2, max_length=80)
    username: str
    display_name: str = Field(min_length=1, max_length=80)


class RegisterIn(BaseModel):
    kind: str                                   # company | join | individual
    username: str
    display_name: str = Field(min_length=1, max_length=80)
    public_key: str = Field(min_length=40, max_length=400)
    company: str = Field(default="", max_length=80)
    join_code: str = Field(default="", max_length=20)


class SignupIn(BaseModel):
    company: bool = True
    individual: bool = True


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    kind: str | None = None                     # only individual -> company


class ChallengeIn(BaseModel):
    username: str


class LoginIn(BaseModel):
    username: str
    nonce: str = Field(max_length=100)
    signature: str = Field(max_length=400)
    public_key: str | None = Field(default=None, max_length=400)


class MemberIn(BaseModel):
    username: str
    display_name: str = Field(min_length=1, max_length=80)
    role: str = "engineer"


class MemberPatch(BaseModel):
    role: str | None = None
    display_name: str | None = Field(default=None, max_length=80)


def setup_needed() -> bool:
    return db.one("SELECT 1 AS x FROM companies LIMIT 1") is None


def create_company(name: str, is_host: bool = False, kind: str = "company") -> str:
    cid = secrets.token_hex(5)
    db.run("INSERT INTO companies(id,name,created,is_host,kind,join_code) VALUES(?,?,?,?,?,?)", cid, name.strip(),
           time.time(), int(is_host), kind, new_join_code() if kind == "company" else None)
    return cid


def new_join_code() -> str:
    raw = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def norm_join_code(c: str) -> str:
    c = re.sub(r"[^A-Z0-9]", "", (c or "").upper())
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else ""


def signup_settings() -> dict:
    return {**SIGNUP_DEFAULT, **(db.get_setting("server", "signup", {}) or {})}


def create_user(username: str, display_name: str, company_id: str, role: str = "engineer") -> dict:
    if role not in ROLES:
        raise HTTPException(400, "role must be admin or engineer")
    uid = vault.uid(username)
    if db.one("SELECT 1 AS x FROM users WHERE username=?", uid):
        raise HTTPException(409, "that username is taken")
    db.run("INSERT INTO users(username,username_enc,display_name,company_id,role,created) VALUES(?,?,?,?,?,?)",
           uid, vault.seal(username, "users.username"), vault.seal(display_name.strip(), "users.display_name"),
           company_id, role, time.time())
    return get_user(uid=uid)


def require(request: Request) -> dict:
    u = getattr(request.state, "user", None)
    if not u:
        raise HTTPException(401, "sign in first")
    return u


def require_admin(request: Request) -> dict:
    u = require(request)
    if u["role"] != "admin":
        raise HTTPException(403, "only an admin can do this")
    return u


def _xmpp_domain() -> str:
    from . import xmpp

    return xmpp.DOMAIN


# --- routes ---------------------------------------------------------------------------------
@router.get("/auth/state")
def state(request: Request):
    u = session_user(request)
    return {"setup_needed": setup_needed(), "user": public_user(u) if u else None, "signup": signup_settings()}


@router.post("/auth/setup")
def setup(body: SetupIn):
    with db.tx():
        if not setup_needed():
            raise HTTPException(409, "this server is already set up; ask your admin to add you")
        username = norm_username(body.username)
        cid = create_company(body.company, is_host=True)
        create_user(username, body.display_name, cid, "admin")
        # projects created before accounts existed belong to the first company
        from . import store

        store.adopt_orphan_projects(cid)
    return {"ok": True, "username": username}


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _signin_limit(request: Request) -> None:
    """At most SIGNIN_LIMIT[0] challenge/login calls per client address per minute (stops nonce flooding
    and hammering the signature check). The log is pruned so it can't grow without bound."""
    now, ip = time.time(), _client(request)
    if len(_signin_log) > 10_000:
        for k in [k for k, v in _signin_log.items() if not v or now - v[-1] > SIGNIN_LIMIT[1]]:
            del _signin_log[k]
    hits = [t for t in _signin_log.get(ip, []) if now - t < SIGNIN_LIMIT[1]]
    if len(hits) >= SIGNIN_LIMIT[0]:
        raise HTTPException(429, "too many sign-in attempts; wait a minute")
    _signin_log[ip] = hits + [now]


def _rate_limit(request: Request, record: bool = False) -> None:
    """At most REGISTER_LIMIT[0] new accounts per client address per hour (counts created accounts only)."""
    ip = _client(request)
    now = time.time()
    hits = [t for t in _register_log.get(ip, []) if now - t < REGISTER_LIMIT[1]]
    if record:
        _register_log[ip] = hits + [now]
    elif len(hits) >= REGISTER_LIMIT[0]:
        raise HTTPException(429, "too many new accounts from this address; try again in an hour")


@router.post("/auth/register")
def register(body: RegisterIn, request: Request):
    """Create your own account: a new company (you are its admin), join one with a code, or an individual one."""
    if setup_needed():
        raise HTTPException(409, "this server is not set up yet; use the setup screen")
    if body.kind not in ("company", "join", "individual"):
        raise HTTPException(400, "kind must be company, join or individual")
    allowed = signup_settings()
    if body.kind in ("company", "join") and not allowed["company"]:
        raise HTTPException(403, "this server doesn't allow new company accounts; ask its admin")
    if body.kind == "individual" and not allowed["individual"]:
        raise HTTPException(403, "this server doesn't allow individual accounts; ask its admin")
    username = norm_username(body.username)
    load_key(body.public_key)  # reject a malformed key before creating anything
    _rate_limit(request)
    with db.tx():
        if body.kind == "company":
            if len(body.company.strip()) < 2:
                raise HTTPException(400, "enter the company or department name")
            cid, role = create_company(body.company), "admin"
        elif body.kind == "join":
            code = norm_join_code(body.join_code)
            comp = db.one("SELECT id FROM companies WHERE join_code=? AND kind='company'", code) if code else None
            if not comp:
                raise HTTPException(404, "that join code doesn't match a company; check it with your admin")
            cid, role = comp["id"], "engineer"
        else:
            cid, role = create_company(body.display_name, kind="individual"), "admin"
        u = create_user(username, body.display_name, cid, role)
        db.run("UPDATE users SET auth_key=?, key_set_at=? WHERE username=?", body.public_key, time.time(), u["uid"])
    _rate_limit(request, record=True)
    return {"ok": True, "username": username, "kind": body.kind}


@router.put("/auth/signup")
def put_signup(body: SignupIn, request: Request):
    """Which kinds of self sign-up this server allows (only the host company's admin)."""
    me = require_admin(request)
    if not public_user(me)["host_admin"]:
        raise HTTPException(403, "only the admin of the company that set up this server can change sign-up")
    db.set_setting("server", "signup", body.model_dump())
    return signup_settings()


@router.get("/company")
def get_company(request: Request):
    me = require(request)
    c = db.one("SELECT id, name, kind, join_code, is_host FROM companies WHERE id=?", me["company_id"])
    out = {"name": c["name"], "kind": c["kind"], "members": db.one("SELECT COUNT(*) AS n FROM users WHERE company_id=?", c["id"])["n"],
           "is_host": bool(c["is_host"])}
    if me["role"] == "admin":
        out["join_code"] = c["join_code"]
        out["signup"] = signup_settings() if c["is_host"] else None
    return out


@router.patch("/company")
def patch_company(body: CompanyPatch, request: Request):
    me = require_admin(request)
    c = db.one("SELECT kind FROM companies WHERE id=?", me["company_id"])
    if body.kind is not None:
        if body.kind != "company":
            raise HTTPException(400, "a company can't be turned back into an individual account")
        if c["kind"] == "individual":
            if not body.name:
                raise HTTPException(400, "give the company a name")
            db.run("UPDATE companies SET kind='company', join_code=? WHERE id=?", new_join_code(), me["company_id"])
    if body.name:
        db.run("UPDATE companies SET name=? WHERE id=?", body.name.strip(), me["company_id"])
    return get_company(request)


@router.post("/company/join-code")
def rotate_join_code(request: Request, off: bool = False):
    """New join code (the old one stops working), or off=true to stop joining by code."""
    me = require_admin(request)
    c = db.one("SELECT kind FROM companies WHERE id=?", me["company_id"])
    if c["kind"] != "company":
        raise HTTPException(400, "turn your account into a company first")
    db.run("UPDATE companies SET join_code=? WHERE id=?", None if off else new_join_code(), me["company_id"])
    return get_company(request)


@router.post("/auth/challenge")
def challenge(body: ChallengeIn, request: Request):
    _signin_limit(request)
    username = norm_username(body.username)
    u = get_user(username)
    if not u or u["disabled"]:
        raise HTTPException(404, "no account with that username. Create one, or ask your company admin to add you")
    nonce = secrets.token_urlsafe(24)
    db.run("DELETE FROM challenges WHERE created<?", time.time() - CHALLENGE_TTL)
    db.run("INSERT INTO challenges(nonce,username,created) VALUES(?,?,?)", nonce, u["uid"], time.time())
    return {"nonce": nonce, "claim": not u["auth_key"], "message": login_message(username, nonce).decode()}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    _signin_limit(request)
    username = norm_username(body.username)
    uid = vault.uid(username)
    with db.tx() as con:
        ch = con.execute("DELETE FROM challenges WHERE nonce=? AND username=? RETURNING created", (body.nonce, uid)).fetchone()
        if not ch or time.time() - ch["created"] > CHALLENGE_TTL:
            raise HTTPException(401, "sign-in expired; try again")
        u = con.execute("SELECT * FROM users WHERE username=? AND disabled=0", (uid,)).fetchone()
        if not u:
            raise HTTPException(401, "no account with that username")
        if u["auth_key"]:
            key = load_key(u["auth_key"])
            if body.public_key and body.public_key != u["auth_key"]:
                raise HTTPException(403, "this username is linked to another device; ask your admin to reset it")
        else:
            if not body.public_key:
                raise HTTPException(400, "first sign-in needs this device's public key")
            key = load_key(body.public_key)
        if not verify_sig(key, login_message(username, body.nonce), body.signature):
            raise HTTPException(403, "this username is linked to another device; ask your admin to reset it")
        if not u["auth_key"]:
            con.execute("UPDATE users SET auth_key=?, key_set_at=? WHERE username=?", (body.public_key, time.time(), uid))
    create_session(response, request, uid)
    return {"user": public_user(get_user(uid=uid))}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        db.run("DELETE FROM sessions WHERE token_hash=?", _hash(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/team")
def team(request: Request):
    me = require(request)
    rows = users_where("company_id=?", me["company_id"])
    return [public_user(r) for r in sorted(rows, key=lambda r: r["display_name"].lower())]


@router.post("/team")
def add_member(body: MemberIn, request: Request):
    me = require_admin(request)
    if (db.one("SELECT kind FROM companies WHERE id=?", me["company_id"]) or {}).get("kind") == "individual":
        raise HTTPException(400, "an individual account has no team; turn it into a company in Settings first")
    username = norm_username(body.username)
    return public_user(create_user(username, body.display_name, me["company_id"], body.role))


def _member(me: dict, username: str) -> dict:
    u = get_user(norm_username(username))
    if not u or u["company_id"] != me["company_id"]:
        raise HTTPException(404, "no such member in your company")
    return u


@router.patch("/team/{username}")
def patch_member(username: str, body: MemberPatch, request: Request):
    me = require_admin(request)
    u = _member(me, username)
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, "role must be admin or engineer")
        if u["uid"] == me["uid"] and body.role != "admin":
            raise HTTPException(400, "you can't remove your own admin role")
        db.run("UPDATE users SET role=? WHERE username=?", body.role, u["uid"])
    if body.display_name:
        db.run("UPDATE users SET display_name=? WHERE username=?", vault.seal(body.display_name.strip(), "users.display_name"), u["uid"])
    return public_user(get_user(uid=u["uid"]))


@router.post("/team/{username}/reset-device")
def reset_device(username: str, request: Request):
    """Unbind the username from its device (lost phone, new laptop). Chat keys are removed too:
    contacts will see that the person's security code changed."""
    me = require_admin(request)
    u = _member(me, username)
    with db.tx() as con:
        con.execute("UPDATE users SET auth_key=NULL, key_set_at=NULL WHERE username=?", (u["uid"],))
        con.execute("DELETE FROM sessions WHERE username=?", (u["uid"],))
    from . import xmpp  # late import: xmpp imports this module

    xmpp.remove_account_sessions(u["uid"])  # their chat devices must sign in again; contacts see a new OMEMO key
    return public_user(get_user(uid=u["uid"]))


@router.post("/team/{username}/disable")
def disable_member(username: str, request: Request):
    me = require_admin(request)
    u = _member(me, username)
    if u["uid"] == me["uid"]:
        raise HTTPException(400, "you can't disable your own account")
    db.run("UPDATE users SET disabled=1 WHERE username=?", u["uid"])
    end_sessions(u["uid"])
    from . import xmpp

    xmpp.remove_account_sessions(u["uid"])
    return public_user(get_user(uid=u["uid"]))


@router.post("/team/{username}/enable")
def enable_member(username: str, request: Request):
    me = require_admin(request)
    u = _member(me, username)
    db.run("UPDATE users SET disabled=0 WHERE username=?", u["uid"])
    return public_user(get_user(uid=u["uid"]))


@router.get("/directory")
def directory(request: Request, q: str = ""):
    """Engineers in your company whose name or username matches, plus an exact username
    match from any company on this server (so people can reach each other by username)."""
    me = require(request)
    q = q.strip().lower().lstrip("@")[:40]
    # names are encrypted, so the company's members are decrypted and matched here
    rows = [r for r in users_where("company_id=? AND disabled=0 AND username<>?", me["company_id"], me["uid"])
            if q in r["username"] or q in r["display_name"].lower()]
    rows = sorted(rows, key=lambda r: r["display_name"].lower())[:50]
    if q and USERNAME_RE.match(q) and q != me["username"] and not any(r["username"] == q for r in rows):
        ex = get_user(q)
        if ex and not ex["disabled"]:
            rows.append(ex)
    out = []
    for r in rows:
        p = public_user(r)
        out.append({k: p[k] for k in ("username", "display_name", "company", "role")} | {"can_chat": True, "jid": f"{r['uid']}@{_xmpp_domain()}"})
    return out

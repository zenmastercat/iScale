"""Engineer chat over XMPP: an ejabberd server on the company's own machine.

Why XMPP: it is the open messaging standard (RFC 6120/6121; WhatsApp itself started on
ejabberd), so any XMPP client can in principle talk to it, and group chats are standard
XMPP multi-user chat rooms (XEP-0045).

How it fits iScale
  * ejabberd runs as a child process of `civil serve`, listening on 127.0.0.1 only:
    5280 /xmpp  XMPP over WebSocket (RFC 7395)   5281 /api  admin API (rooms)
    No server-to-server federation, no ports open to the network.
  * Browsers reach it through iScale's own port: GET /xmpp is a WebSocket that iScale
    passes through to ejabberd after checking the session cookie, so HTTPS and the
    "who can reach the app" network setting cover chat too.
  * Sign-in: iScale gives the signed-in browser a short-lived JSON Web Token (HS256,
    1 hour) naming its JID; ejabberd checks it (auth_method: jwt). No XMPP passwords exist.
  * JIDs are <uid>@iscale.local, where uid is the keyed hash of the username (vault.py).
    ejabberd's own database therefore never holds a username or a name; the browser asks
    iScale who a uid is (GET /api/xmpp/whois).
  * Messages are end-to-end encrypted in the browser with OMEMO (XEP-0384, the
    eu.siacs.conversations.axolotl version that Conversations, Gajim and Monal use), which is
    the Signal Protocol's Double Ratchet carried in XMPP. ejabberd only ever stores
    ciphertext: 1:1 messages in its offline store until delivered (then deleted), group
    messages as the room's last HISTORY_SIZE messages so members who were away catch up.
    No message archive (MAM) is kept.
  * Groups: a company admin creates them in iScale; iScale creates a members-only,
    non-anonymous, persistent room and sets each member's affiliation through the admin API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket

from . import auth, db
from .config import DATA_DIR

router = APIRouter()

DOMAIN = os.environ.get("CIVIL_XMPP_DOMAIN", "iscale.local")
MUC = f"conference.{DOMAIN}"
WS_PORT = int(os.environ.get("CIVIL_XMPP_WS_PORT", "5280"))
API_PORT = int(os.environ.get("CIVIL_XMPP_API_PORT", "5281"))
TOKEN_TTL = 3600
HISTORY_SIZE = 200
MAX_OFFLINE = 5000
_proc: subprocess.Popen | None = None


# --- files ---------------------------------------------------------------------------------------------------
def home() -> Path:
    return DATA_DIR / "xmpp"


def jwt_secret() -> bytes:
    """The HS256 key shared with ejabberd (data/secrets/xmpp-jwt.key, made once)."""
    p = DATA_DIR / "secrets" / "xmpp-jwt.key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(32))
        p.chmod(0o600)
    return p.read_bytes()


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jid_of(uid: str) -> str:
    return f"{uid}@{DOMAIN}"


def room_jid(gid: str) -> str:
    return f"g{gid}@{MUC}"


def token(uid: str, ttl: int = TOKEN_TTL) -> str:
    """A JWT ejabberd accepts as the SASL PLAIN password for jid_of(uid)."""
    head = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64u(json.dumps({"jid": jid_of(uid), "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(jwt_secret(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def config_yaml() -> str:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    jwk = h / "jwt.jwk"
    jwk.write_text(json.dumps({"kty": "oct", "k": _b64u(jwt_secret())}))
    jwk.chmod(0o600)
    return f"""# Written by iScale (civil/xmpp.py) on every start; edit that file, not this one.
hosts:
  - "{DOMAIN}"
loglevel: warning
log_rotate_count: 1
# jwt: people sign in only with the short-lived token iScale issues. internal: holds an account
# entry (with a random password nobody knows) so ejabberd knows the person exists and keeps
# their messages while they are offline; JWT alone can't answer "does this user exist?".
auth_method:
  - jwt
  - internal
jwt_key: "{jwk}"
jwt_jid_field: "jid"
s2s_access: s2s
acl:
  loopback:
    ip:
      - 127.0.0.0/8
      - ::1/128
access_rules:
  s2s:
    deny: all
  local:
    allow: all
  muc_create:
    deny: all
shaper_rules:
  max_user_offline_messages: {MAX_OFFLINE}
  max_user_sessions: 10
api_permissions:
  "iScale on this computer":
    from:
      - mod_http_api
    who:
      access:
        allow:
          - acl: loopback
    what:
      - "*"
listen:
  - port: {WS_PORT}
    ip: "127.0.0.1"
    module: ejabberd_http
    request_handlers:
      /xmpp: ejabberd_http_ws
  - port: {API_PORT}
    ip: "127.0.0.1"
    module: ejabberd_http
    request_handlers:
      /api: mod_http_api
modules:
  mod_caps: {{}}
  mod_disco: {{}}
  mod_ping: {{}}
  mod_stream_mgmt: {{}}
  mod_carboncopy: {{}}
  mod_roster: {{}}
  mod_http_api: {{}}
  mod_admin_extra: {{}}
  mod_muc_admin: {{}}
  mod_offline:
    access_max_user_messages: max_user_offline_messages
  mod_pubsub:
    plugins:
      - flat
      - pep
  mod_muc:
    host: "{MUC}"
    access_create: muc_create
    history_size: {HISTORY_SIZE}
    max_users: 500
    default_room_options:
      persistent: true
      members_only: true
      anonymous: false
      allowpm: none
      allow_subscription: false
      mam: false
      public: false
      public_list: false
"""


def ejabberdctl() -> str | None:
    """Path to ejabberdctl: $CIVIL_EJABBERDCTL, then PATH, then the nix store."""
    p = os.environ.get("CIVIL_EJABBERDCTL") or shutil.which("ejabberdctl")
    if p:
        return p
    for c in sorted(Path("/nix/store").glob("*-ejabberd-*/bin/ejabberdctl"), reverse=True):
        return str(c)
    return None


def _env() -> dict:
    h = home()
    env = {k: v for k, v in os.environ.items() if k not in ("ROBOFLOW_API_KEY", "CIVIL_DB_KEY")}
    env.update({"HOME": str(h), "ERL_EPMD_ADDRESS": "127.0.0.1", "ERLANG_NODE": "iscale@127.0.0.1",
                "INET_DIST_INTERFACE": "{127,0,0,1}"})
    return env


def _ctl_args() -> list[str]:
    h = home()
    return ["--config-dir", str(h), "--config", str(h / "ejabberd.yml"), "--ctl-config", str(h / "ejabberdctl.cfg"),
            "--spool", str(h / "db"), "--logs", str(h / "logs"), "--node", "iscale@127.0.0.1"]


def start() -> str:
    """Write the config and start ejabberd in the background. Returns a status line."""
    global _proc
    ctl = ejabberdctl()
    if not ctl:
        return "XMPP chat is off: ejabberd is not installed (set CIVIL_EJABBERDCTL to ejabberdctl)"
    if running():
        return "XMPP: ejabberd already running"
    h = home()
    for d in ("db", "logs"):
        (h / d).mkdir(parents=True, exist_ok=True)
    (h / "ejabberd.yml").write_text(config_yaml())
    (h / "ejabberdctl.cfg").write_text('ERLANG_NODE=iscale@127.0.0.1\nINET_DIST_INTERFACE="{127,0,0,1}"\n')
    cookie = h / ".erlang.cookie"
    if not cookie.exists():
        cookie.write_text(base64.b32encode(os.urandom(20)).decode())
        cookie.chmod(0o400)
    log = open(h / "logs" / "console.log", "ab")
    _proc = subprocess.Popen([ctl, *_ctl_args(), "foreground"], env=_env(), stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(120):
        if running():
            return f"XMPP: ejabberd running for {DOMAIN} (WebSocket via /xmpp)"
        if _proc.poll() is not None:
            return f"XMPP: ejabberd exited with {_proc.returncode}; see {h / 'logs'}"
        time.sleep(0.5)
    return "XMPP: ejabberd is slow to start; chat connects once it is up"


def stop() -> None:
    global _proc
    """Stop the ejabberd we started. The ejabberdctl wrapper exits at once, but the Erlang VM in
    its process group shuts down gracefully, so wait until every process in the group is gone
    (otherwise the next start finds the Erlang node still registered)."""

    def alive() -> bool:
        try:
            os.killpg(_proc.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    if _proc:
        if alive():
            os.killpg(_proc.pid, signal.SIGTERM)
        _proc.poll()  # reap the wrapper so it doesn't linger as a zombie in the group
        deadline = time.time() + 20
        while time.time() < deadline and alive():
            _proc.poll()
            time.sleep(0.3)
        if alive():
            os.killpg(_proc.pid, signal.SIGKILL)
    _proc = None


def running() -> bool:
    try:
        r = httpx.post(f"http://127.0.0.1:{API_PORT}/api/status", json={}, timeout=2, headers={"Host": DOMAIN})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


# --- admin API (rooms) ---------------------------------------------------------------------------------------
def api(command: str, **args) -> object:
    try:
        r = httpx.post(f"http://127.0.0.1:{API_PORT}/api/{command}", json=args, timeout=10, headers={"Host": DOMAIN})
    except httpx.HTTPError as e:
        raise HTTPException(503, "the chat server (ejabberd) is not running") from e
    if r.status_code != 200:
        raise HTTPException(502, f"chat server refused {command}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return r.text


def ensure_room(gid: str, name: str, member_uids: list[str], owner_uid: str | None = None) -> None:
    """Create the group's room if needed and make its member list exactly member_uids."""
    room = f"g{gid}"
    rooms = api("muc_online_rooms", service=MUC) or []
    if room_jid(gid) not in rooms:
        api("create_room_with_opts", room=room, service=MUC, host=DOMAIN, options=[
            {"name": "title", "value": name[:80]}, {"name": "persistent", "value": "true"},
            {"name": "members_only", "value": "true"}, {"name": "anonymous", "value": "false"},
            {"name": "allowpm", "value": "none"}, {"name": "public", "value": "false"},
            {"name": "public_list", "value": "false"}, {"name": "mam", "value": "false"},
            {"name": "allow_change_subj", "value": "false"}, {"name": "allow_query_users", "value": "false"},
            {"name": "allow_user_invites", "value": "false"}])
    else:
        api("change_room_option", room=room, service=MUC, option="title", value=name[:80])
    want = {jid_of(u) for u in member_uids}
    have = {a["jid"]: a["affiliation"] for a in (api("get_room_affiliations", room=room, service=MUC) or [])
            if isinstance(a, dict) and a.get("jid")}
    for j in want:
        aff = "owner" if owner_uid and j == jid_of(owner_uid) else "member"
        if have.get(j) != aff:
            api("set_room_affiliation", room=room, service=MUC, user=j.split("@")[0], host=DOMAIN, affiliation=aff)
    for j in set(have) - want:
        api("set_room_affiliation", room=room, service=MUC, user=j.split("@")[0], host=DOMAIN, affiliation="none")


def room_members(gid: str) -> dict[str, str]:
    return {a["jid"]: a["affiliation"] for a in (api("get_room_affiliations", room=f"g{gid}", service=MUC) or [])
            if isinstance(a, dict) and a.get("jid")}


def drop_room(gid: str) -> None:
    api("destroy_room", room=f"g{gid}", service=MUC)


def remove_account_sessions(uid: str) -> None:
    """End a person's chat sessions (device reset, disabled account). Quiet if ejabberd is down."""
    try:
        api("kick_user", user=uid, host=DOMAIN)
    except HTTPException:
        pass


_accounts: set[str] = set()


def ensure_account(uid: str) -> None:
    """Give ejabberd an account entry for uid (see auth_method in config_yaml). Quiet if down."""
    if uid in _accounts:
        return
    try:
        if api("check_account", user=uid, host=DOMAIN) != 0:
            api("register", user=uid, host=DOMAIN, password=_b64u(os.urandom(32)))
        _accounts.add(uid)
    except HTTPException:
        pass


# --- routes --------------------------------------------------------------------------------------------------
@router.get("/api/xmpp/token")
def get_token(request: Request):
    me = auth.require(request)
    ensure_account(me["uid"])
    return {"jid": jid_of(me["uid"]), "token": token(me["uid"]), "domain": DOMAIN, "muc": MUC,
            "websocket": "/xmpp", "expires_in": TOKEN_TTL, "running": running()}


@router.get("/api/xmpp/jid")
def jid_for(request: Request, username: str):
    """The chat address for a username: what the browser needs to start a 1:1 OMEMO chat."""
    auth.require(request)
    u = auth.get_user(username.strip().lower().lstrip("@")[:40])
    if not u or u["disabled"]:
        raise HTTPException(404, "no such engineer on this server")
    return auth.person(u["uid"])


@router.get("/api/xmpp/whois")
def whois(request: Request, jid: str):
    """Who a chat address belongs to: the uid in a JID is a hash, so only iScale can name it."""
    auth.require(request)
    local, _, dom = jid.partition("@")
    if dom.split("/")[0] != DOMAIN:
        raise HTTPException(404, "not a person on this server")
    p = auth.person(local)
    if not p:
        raise HTTPException(404, "not a person on this server")
    return p | {"jid": jid_of(local)}


@router.websocket("/xmpp")
async def ws_proxy(ws: WebSocket):
    """Pass XMPP-over-WebSocket frames between the browser and ejabberd (signed-in users only)."""
    import websockets

    user = auth.session_user(ws)  # same cookie as the rest of the app
    origin = ws.headers.get("origin", "")
    host = ws.headers.get("host", "")
    if user is None or (origin and origin.split("://", 1)[-1] != host):
        await ws.close(code=4401)
        return
    await ws.accept(subprotocol="xmpp")
    try:
        upstream = await websockets.connect(f"ws://127.0.0.1:{WS_PORT}/xmpp", subprotocols=["xmpp"],
                                            max_size=2 ** 20, open_timeout=10)
    except (OSError, websockets.WebSocketException):
        await ws.close(code=1013)
        return

    async def up():
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            data = m.get("text") if m.get("text") is not None else m.get("bytes")
            if data is not None:
                await upstream.send(data)

    async def down():
        async for data in upstream:
            if isinstance(data, bytes):
                await ws.send_bytes(data)
            else:
                await ws.send_text(data)

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await upstream.close()
        try:
            await ws.close()
        except RuntimeError:
            pass


def ensure_schema() -> None:
    db.connect()

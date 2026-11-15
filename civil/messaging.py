"""Relay for end-to-end encrypted chat (Signal Protocol, the protocol WhatsApp uses).

The server never sees message content. Each device publishes a pre-key bundle (identity
key, signed pre-key, one-time pre-keys); senders fetch a bundle, run X3DH in their
browser, and send Double-Ratchet ciphertext here. The server stores the ciphertext only
until the recipient's device confirms it has it, then deletes it. Undelivered messages
expire after RETENTION_DAYS. Nothing is logged or sent anywhere else.

Group chats (groups.py) use the same sessions: the sender's device encrypts the message
once for each member and posts the copies together (/send-group). The server checks that
the sender and every recipient are members, and relays each copy like a 1:1 message.
People are referred to by uid (vault.py) in every table.
"""

from __future__ import annotations

import asyncio
import base64
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, db, vault

router = APIRouter(prefix="/api/chat")

MAX_BODY = 64 * 1024  # base64 ciphertext
MAX_PREKEYS = 200
RETENTION_DAYS = 30
SEND_PER_MINUTE = 120


def _b64(s: str, max_len: int = 200) -> str:
    if len(s) > max_len:
        raise HTTPException(400, "key too long")
    try:
        base64.b64decode(s, validate=True)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "keys must be base64") from e
    return s


class SignedPreKey(BaseModel):
    id: int = Field(ge=0, lt=2**24)
    public_key: str
    signature: str


class PreKey(BaseModel):
    id: int = Field(ge=0, lt=2**24)
    public_key: str


class KeysIn(BaseModel):
    registration_id: int = Field(ge=1, lt=2**14 + 1)
    identity_key: str
    signed_prekey: SignedPreKey
    prekeys: list[PreKey] = Field(default_factory=list, max_length=MAX_PREKEYS)


class PreKeysIn(BaseModel):
    prekeys: list[PreKey] = Field(max_length=MAX_PREKEYS)


class SendIn(BaseModel):
    to: str
    type: int = Field(ge=1, le=3)  # 3 = PreKeyWhisperMessage (first message), 1 = WhisperMessage
    body: str = Field(max_length=MAX_BODY)


class GroupCopy(BaseModel):
    to: str
    type: int = Field(ge=1, le=3)
    body: str = Field(max_length=MAX_BODY)


class GroupSendIn(BaseModel):
    group_id: str = Field(max_length=40)
    copies: list[GroupCopy] = Field(max_length=200)


class AckIn(BaseModel):
    up_to: int = Field(ge=0)


def _store_prekeys(con, username: str, prekeys: list[PreKey]) -> None:
    con.executemany("INSERT OR REPLACE INTO signal_prekeys(username,key_id,public_key) VALUES(?,?,?)",
                    [(username, p.id, _b64(p.public_key)) for p in prekeys])
    n = con.execute("SELECT COUNT(*) AS n FROM signal_prekeys WHERE username=?", (username,)).fetchone()["n"]
    if n > MAX_PREKEYS:
        raise HTTPException(400, "too many pre-keys")


@router.put("/keys")
def publish_keys(body: KeysIn, request: Request):
    me = auth.require(request)
    with db.tx() as con:
        old = con.execute("SELECT identity_key FROM signal_identity WHERE username=?", (me["uid"],)).fetchone()
        if old and old["identity_key"] != body.identity_key:
            # a new identity on this account: old one-time keys belong to the old identity
            con.execute("DELETE FROM signal_prekeys WHERE username=?", (me["uid"],))
        con.execute("INSERT OR REPLACE INTO signal_identity(username,registration_id,identity_key,signed_prekey_id,"
                    "signed_prekey,signed_prekey_sig,updated) VALUES(?,?,?,?,?,?,?)",
                    (me["uid"], body.registration_id, _b64(body.identity_key), body.signed_prekey.id,
                     _b64(body.signed_prekey.public_key), _b64(body.signed_prekey.signature), time.time()))
        _store_prekeys(con, me["uid"], body.prekeys)
    return key_status(request)


@router.post("/prekeys")
def add_prekeys(body: PreKeysIn, request: Request):
    me = auth.require(request)
    with db.tx() as con:
        if not con.execute("SELECT 1 FROM signal_identity WHERE username=?", (me["uid"],)).fetchone():
            raise HTTPException(409, "publish your identity first")
        _store_prekeys(con, me["uid"], body.prekeys)
    return key_status(request)


@router.get("/keys")
def key_status(request: Request):
    me = auth.require(request)
    ident = db.one("SELECT identity_key FROM signal_identity WHERE username=?", me["uid"])
    n = db.one("SELECT COUNT(*) AS n FROM signal_prekeys WHERE username=?", me["uid"])["n"]
    return {"identity_key": ident["identity_key"] if ident else None, "prekeys": n}


@router.get("/bundle/{username}")
def bundle(username: str, request: Request):
    auth.require(request)
    username = auth.norm_username(username)
    uid = vault.uid(username)
    card = auth.person(uid)
    with db.tx() as con:
        u = con.execute("SELECT 1 FROM users WHERE username=? AND disabled=0", (uid,)).fetchone()
        ident = con.execute("SELECT * FROM signal_identity WHERE username=?", (uid,)).fetchone()
        if not u or not ident or not card:
            raise HTTPException(404, "that engineer hasn't signed in on a device yet")
        pk = con.execute("SELECT key_id, public_key FROM signal_prekeys WHERE username=? ORDER BY key_id LIMIT 1",
                         (uid,)).fetchone()
        if pk:  # one-time pre-keys are handed out once
            con.execute("DELETE FROM signal_prekeys WHERE username=? AND key_id=?", (uid, pk["key_id"]))
    return {"username": username, "display_name": card["display_name"], "company": card["company"],
            "registration_id": ident["registration_id"], "identity_key": ident["identity_key"],
            "signed_prekey": {"id": ident["signed_prekey_id"], "public_key": ident["signed_prekey"],
                              "signature": ident["signed_prekey_sig"]},
            "prekey": {"id": pk["key_id"], "public_key": pk["public_key"]} if pk else None}


@router.post("/send")
def send(body: SendIn, request: Request):
    me = auth.require(request)
    to = _recipient(me, body.to)
    _b64(body.body, MAX_BODY)
    _rate(me, 1)
    mid = db.run("INSERT INTO messages(sender,recipient,type,body,sent) VALUES(?,?,?,?,?)",
                 me["uid"], to, body.type, body.body, time.time())
    return {"id": mid}


def _recipient(me: dict, username: str) -> str:
    to = vault.uid(auth.norm_username(username))
    if to == me["uid"]:
        raise HTTPException(400, "you can't message yourself")
    if not db.one("SELECT 1 AS x FROM signal_identity s JOIN users u ON u.username=s.username WHERE s.username=? AND u.disabled=0", to):
        raise HTTPException(404, f"@{username} hasn't signed in on a device yet")
    return to


def _rate(me: dict, n: int) -> None:
    """Counts send actions, not copies: a group message to 30 people is one action."""
    recent = db.one("SELECT COUNT(DISTINCT sent) AS n FROM messages WHERE sender=? AND sent>?", me["uid"], time.time() - 60)["n"]
    if recent + n > SEND_PER_MINUTE:
        raise HTTPException(429, "too many messages; wait a minute")


@router.post("/send-group")
def send_group(body: GroupSendIn, request: Request):
    me = auth.require(request)
    members = {r["username"] for r in db.all_("SELECT username FROM chat_group_members WHERE group_id=?", body.group_id)}
    if me["uid"] not in members:
        raise HTTPException(403, "you're not in this group")
    rows, seen = [], set()
    for c in body.copies:
        to = _recipient(me, c.to)
        if to not in members:
            raise HTTPException(403, f"@{c.to} is not in this group")
        if to in seen:
            raise HTTPException(400, "one copy per member")
        seen.add(to)
        rows.append((to, c.type, _b64(c.body, MAX_BODY)))
    _rate(me, 1)
    now = time.time()
    with db.tx() as con:
        con.executemany("INSERT INTO messages(sender,recipient,type,body,sent,group_id) VALUES(?,?,?,?,?,?)",
                        [(me["uid"], to, t, b, now, body.group_id) for to, t, b in rows])
    return {"sent": len(rows)}


def _pending(username: str, after: int) -> list[dict]:
    db.run("DELETE FROM messages WHERE sent<?", time.time() - RETENTION_DAYS * 86400)
    rows = db.all_("SELECT id, sender, type, body, sent, group_id FROM messages WHERE recipient=? AND id>? "
                   "ORDER BY id LIMIT 200", username, after)
    cards: dict[str, dict | None] = {}
    out = []
    for r in rows:
        if r["sender"] not in cards:
            cards[r["sender"]] = auth.person(r["sender"])
        c = cards[r["sender"]]
        if not c:  # sender account was removed
            continue
        out.append({**r, "sender": c["username"], "sender_name": c["display_name"], "sender_company": c["company"]})
    return out


@router.get("/inbox")
async def inbox(request: Request, after: int = 0, wait: int = 0):
    """Long poll: returns as soon as something arrives, or after `wait` seconds (max 25)."""
    me = auth.require(request)
    deadline = time.time() + max(0, min(wait, 25))
    while True:
        rows = _pending(me["uid"], after)
        if rows or time.time() >= deadline or await request.is_disconnected():
            return {"messages": rows}
        await asyncio.sleep(1.0)


@router.post("/ack")
def ack(body: AckIn, request: Request):
    """The device has decrypted and saved everything up to this id: delete it from the server."""
    me = auth.require(request)
    n = db.run("DELETE FROM messages WHERE recipient=? AND id<=?", me["uid"], body.up_to)
    return {"deleted": n}

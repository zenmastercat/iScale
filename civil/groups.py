"""Group chats. A company admin creates a group and picks members: anyone in their company,
or any engineer on this server by exact username (people they've talked to or searched for).

iScale keeps the roster (group id, encrypted group name, member uids) and mirrors it into an
XMPP multi-user chat room on ejabberd (xmpp.ensure_room): members-only, non-anonymous, one
room per group, room JID g<id>@conference.<domain>. Messages are OMEMO-encrypted on the
sender's device for every member's devices, so neither iScale nor ejabberd sees what's said.

Who manages a group: the admin who created it, and the admins of the group's company.
Any member can leave.
"""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, db, vault, xmpp

router = APIRouter(prefix="/api/groups")
MAX_MEMBERS = 100


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    members: list[str] = Field(default_factory=list, max_length=MAX_MEMBERS)


class GroupPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MembersIn(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=MAX_MEMBERS)


def _group(gid: str) -> dict:
    g = db.one("SELECT * FROM chat_groups WHERE id=?", gid)
    if not g:
        raise HTTPException(404, "no such group")
    return g


def sync_room(gid: str) -> bool:
    """Mirror one group into its XMPP room. False (and nothing raised) when ejabberd is down;
    xmpp.start() re-syncs every group when it comes up."""
    g = db.one("SELECT * FROM chat_groups WHERE id=?", gid)
    try:
        if g is None:
            xmpp.drop_room(gid)
        else:
            xmpp.ensure_room(gid, vault.open_(g["name"], "chat_groups.name"), _member_uids(gid), g["created_by"])
        return True
    except HTTPException as e:
        if e.status_code == 503:
            return False
        raise


def sync_all_rooms() -> int:
    n = 0
    for g in db.all_("SELECT id FROM chat_groups"):
        n += sync_room(g["id"])
    return n


def _member_uids(gid: str) -> list[str]:
    return [r["username"] for r in db.all_("SELECT username FROM chat_group_members WHERE group_id=? ORDER BY added", gid)]


def _can_manage(me: dict, g: dict) -> bool:
    return me["uid"] == g["created_by"] or (me["role"] == "admin" and me["company_id"] == g["company_id"])


def _out(me: dict, g: dict) -> dict:
    members = [p for p in (auth.person(u) for u in _member_uids(g["id"])) if p]
    creator = auth.person(g["created_by"])
    return {"id": g["id"], "name": vault.open_(g["name"], "chat_groups.name"), "created": g["created"],
            "jid": xmpp.room_jid(g["id"]),
            "created_by": creator["username"] if creator else None,
            "members": sorted(members, key=lambda p: p["display_name"].lower()),
            "can_manage": _can_manage(me, g)}


def _resolve(usernames: list[str]) -> list[str]:
    uids = []
    for name in usernames:
        u = auth.get_user(auth.norm_username(name))
        if not u or u["disabled"]:
            raise HTTPException(404, f"no engineer with username @{name.strip().lstrip('@')}")
        uids.append(u["uid"])
    return list(dict.fromkeys(uids))


def _check_size(gid: str, adding: int) -> None:
    if len(_member_uids(gid)) + adding > MAX_MEMBERS:
        raise HTTPException(400, f"a group can have at most {MAX_MEMBERS} members")


@router.get("")
def my_groups(request: Request):
    me = auth.require(request)
    rows = db.all_("SELECT g.* FROM chat_groups g JOIN chat_group_members m ON m.group_id=g.id "
                   "WHERE m.username=? ORDER BY g.created DESC", me["uid"])
    return [_out(me, g) for g in rows]


@router.post("")
def create_group(body: GroupIn, request: Request):
    me = auth.require_admin(request)
    uids = [u for u in _resolve(body.members) if u != me["uid"]]
    if len(uids) + 1 > MAX_MEMBERS:
        raise HTTPException(400, f"a group can have at most {MAX_MEMBERS} members")
    gid = secrets.token_hex(8)
    now = time.time()
    with db.tx() as con:
        con.execute("INSERT INTO chat_groups(id,company_id,name,created_by,created) VALUES(?,?,?,?,?)",
                    (gid, me["company_id"], vault.seal(body.name.strip(), "chat_groups.name"), me["uid"], now))
        con.executemany("INSERT INTO chat_group_members(group_id,username,added) VALUES(?,?,?)",
                        [(gid, u, now + i * 1e-6) for i, u in enumerate([me["uid"], *uids])])
    sync_room(gid)
    return _out(me, _group(gid))


@router.patch("/{gid}")
def rename_group(gid: str, body: GroupPatch, request: Request):
    me = auth.require(request)
    g = _group(gid)
    if not _can_manage(me, g):
        raise HTTPException(403, "only the group's admins can rename it")
    db.run("UPDATE chat_groups SET name=? WHERE id=?", vault.seal(body.name.strip(), "chat_groups.name"), gid)
    sync_room(gid)
    return _out(me, _group(gid))


@router.post("/{gid}/members")
def add_members(gid: str, body: MembersIn, request: Request):
    me = auth.require(request)
    g = _group(gid)
    if not _can_manage(me, g):
        raise HTTPException(403, "only the group's admins can add people")
    uids = [u for u in _resolve(body.usernames) if u not in set(_member_uids(gid))]
    _check_size(gid, len(uids))
    now = time.time()
    with db.tx() as con:
        con.executemany("INSERT OR IGNORE INTO chat_group_members(group_id,username,added) VALUES(?,?,?)",
                        [(gid, u, now) for u in uids])
    sync_room(gid)
    return _out(me, g)


@router.delete("/{gid}/members/{username}")
def remove_member(gid: str, username: str, request: Request):
    """An admin removes someone, or a member leaves (username = their own)."""
    me = auth.require(request)
    g = _group(gid)
    uid = vault.uid(auth.norm_username(username))
    if uid != me["uid"] and not _can_manage(me, g):
        raise HTTPException(403, "only the group's admins can remove people")
    with db.tx() as con:
        con.execute("DELETE FROM chat_group_members WHERE group_id=? AND username=?", (gid, uid))
        left = con.execute("SELECT COUNT(*) AS n FROM chat_group_members WHERE group_id=?", (gid,)).fetchone()["n"]
        if not left:
            con.execute("DELETE FROM chat_groups WHERE id=?", (gid,))
    sync_room(gid)  # removing the affiliation also stops them reading the room
    return {"ok": True}


@router.delete("/{gid}")
def delete_group(gid: str, request: Request):
    me = auth.require(request)
    g = _group(gid)
    if not _can_manage(me, g):
        raise HTTPException(403, "only the group's admins can delete it")
    with db.tx() as con:
        con.execute("DELETE FROM chat_groups WHERE id=?", (gid,))
    sync_room(gid)
    return {"ok": True}

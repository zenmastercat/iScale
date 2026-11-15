"""SQLite store for accounts, sessions, chat groups, Civil Helper library and settings.

Everything lives in data/civil.db on the company's own server. Chat messages are not
stored here: they travel over XMPP (civil/xmpp.py, ejabberd) as OMEMO ciphertext. The
signal_identity, signal_prekeys and messages tables are left over from the earlier relay
and are kept only so old databases still migrate.
People are stored by a keyed hash of their username (vault.uid); the username, display
name and group names are AES-GCM encrypted (vault.seal). Every `username`, `sender`,
`recipient`, `reporter`, `uploader` and `resolved_by` column below holds that uid.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL, is_host INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'company', join_code TEXT
);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, username_enc TEXT, display_name TEXT NOT NULL, company_id TEXT NOT NULL REFERENCES companies(id),
  role TEXT NOT NULL DEFAULT 'engineer', created REAL NOT NULL, auth_key TEXT, key_set_at REAL,
  disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
  nonce TEXT PRIMARY KEY, username TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_identity (
  username TEXT PRIMARY KEY, registration_id INTEGER NOT NULL, identity_key TEXT NOT NULL,
  signed_prekey_id INTEGER NOT NULL, signed_prekey TEXT NOT NULL, signed_prekey_sig TEXT NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_prekeys (
  username TEXT NOT NULL, key_id INTEGER NOT NULL, public_key TEXT NOT NULL, PRIMARY KEY (username, key_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL,
  type INTEGER NOT NULL, body TEXT NOT NULL, sent REAL NOT NULL, group_id TEXT
);
CREATE INDEX IF NOT EXISTS messages_recipient ON messages (recipient, id);
CREATE TABLE IF NOT EXISTS chat_groups (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), name TEXT NOT NULL,
  created_by TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_group_members (
  group_id TEXT NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE, username TEXT NOT NULL,
  added REAL NOT NULL, PRIMARY KEY (group_id, username)
);
CREATE INDEX IF NOT EXISTS chat_group_members_user ON chat_group_members (username);
CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL, filename TEXT NOT NULL,
  created REAL NOT NULL, chars INTEGER NOT NULL, uploader TEXT NOT NULL, embedded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL, embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks (doc_id, ord);
CREATE TABLE IF NOT EXISTS settings (
  scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS traffic_cache (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched REAL NOT NULL
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised: set[str] = set()


def db_path() -> Path:
    return DATA_DIR / "civil.db"


def connect() -> sqlite3.Connection:
    path = str(db_path())
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "path", None) != path:
        db_path().parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA secure_delete=ON")  # deleted rows (delivered ciphertext, old names) are zeroed
        _local.con, _local.path = con, path
    with _init_lock:
        if path not in _initialised:
            _pre_migrate(con)
            con.executescript(SCHEMA)
            _migrate(con)
            _initialised.add(path)
    return con


def _cols(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _pre_migrate(con) -> None:
    """Columns added after the first release (CREATE TABLE IF NOT EXISTS won't add them)."""
    if _cols(con, "messages") and "group_id" not in _cols(con, "messages"):
        con.execute("ALTER TABLE messages ADD COLUMN group_id TEXT")
    if _cols(con, "users") and "username_enc" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN username_enc TEXT")
    if _cols(con, "companies") and "kind" not in _cols(con, "companies"):
        # 'company' (a team with an admin) or 'individual' (a one-person workspace)
        con.execute("ALTER TABLE companies ADD COLUMN kind TEXT NOT NULL DEFAULT 'company'")
    if _cols(con, "companies") and "join_code" not in _cols(con, "companies"):
        con.execute("ALTER TABLE companies ADD COLUMN join_code TEXT")


# (table, column) pairs that refer to a person
PERSON_COLUMNS = [("sessions", "username"), ("challenges", "username"), ("signal_identity", "username"),
                  ("signal_prekeys", "username"), ("messages", "sender"), ("messages", "recipient"),
                  ("pins", "reporter"), ("pins", "resolved_by"), ("pin_confirms", "username"),
                  ("docs", "uploader"), ("chat_groups", "created_by"), ("chat_group_members", "username")]


def _migrate(con) -> None:
    """Encrypt accounts stored by an earlier version (plain usernames and names)."""
    from . import vault

    plain = con.execute("SELECT username, display_name FROM users WHERE username_enc IS NULL").fetchall()
    if not plain:
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("PRAGMA defer_foreign_keys=ON")
        for row in plain:
            name, uid = row["username"], vault.uid(row["username"])
            con.execute("UPDATE users SET username=?, username_enc=?, display_name=? WHERE username=?",
                        (uid, vault.seal(name, "users.username"), vault.seal(row["display_name"], "users.display_name"), name))
            for table, col in PERSON_COLUMNS:
                if _cols(con, table):
                    con.execute(f"UPDATE OR IGNORE {table} SET {col}=? WHERE {col}=?", (uid, name))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    # rewrite the file and empty the write-ahead log so no page still holds the old plain names
    con.execute("VACUUM")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")


@contextmanager
def tx():
    con = connect()
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def one(sql: str, *args) -> dict | None:
    r = connect().execute(sql, args).fetchone()
    return dict(r) if r else None


def all_(sql: str, *args) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def run(sql: str, *args) -> int:
    cur = connect().execute(sql, args)
    return cur.lastrowid or cur.rowcount


def get_setting(scope: str, key: str, default=None):
    r = one("SELECT value FROM settings WHERE scope=? AND key=?", scope, key)
    return json.loads(r["value"]) if r else default


def set_setting(scope: str, key: str, value) -> None:
    run("INSERT INTO settings(scope,key,value) VALUES(?,?,?) ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value",
        scope, key, json.dumps(value))


def now() -> float:
    return time.time()

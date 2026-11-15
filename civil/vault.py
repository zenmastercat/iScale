"""Encryption at rest for usernames, names and group names on the company server.

* Every table refers to a person by a keyed hash of the username (`uid`, HMAC-SHA256), so
  the database never holds a username in the clear and lookups still work.
* The username and display name themselves are kept with AES-256-GCM, so the server can
  show them to signed-in colleagues.

The 32-byte server key comes from the CIVIL_DB_KEY environment variable (base64) or, if that
is unset, from data/secrets/db.key, created on first start with 0600 permissions. Keep a
copy of the key: without it the accounts can't be read. For the strongest protection keep
the key out of the data folder (set CIVIL_DB_KEY), so a copied database or backup alone
reveals nobody.

There are no passwords to store: sign-in is a device key whose private half never leaves
the device (see auth.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as _secrets
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import DATA_DIR

PREFIX = "v1:"


def _key_path():
    return DATA_DIR / "secrets" / "db.key"


@lru_cache(maxsize=4)
def _keys(data_dir: str) -> tuple[bytes, bytes]:
    env = os.environ.get("CIVIL_DB_KEY")
    if env:
        master = base64.b64decode(env)
    else:
        p = _key_path()
        if p.is_file():
            master = base64.b64decode(p.read_text().strip())
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            master = _secrets.token_bytes(32)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(base64.b64encode(master).decode() + "\n")
    if len(master) != 32:
        raise RuntimeError("CIVIL_DB_KEY / db.key must be 32 bytes, base64")

    def derive(info: bytes) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)

    return derive(b"civil-scan field encryption v1"), derive(b"civil-scan blind index v1")


def _k() -> tuple[bytes, bytes]:
    return _keys(str(DATA_DIR))


def uid(username: str) -> str:
    """Stable, non-reversible id for a (normalised) username."""
    return "u" + hmac.new(_k()[1], username.encode(), hashlib.sha256).hexdigest()[:40]


def seal(text: str, field: str) -> str:
    nonce = _secrets.token_bytes(12)
    ct = AESGCM(_k()[0]).encrypt(nonce, text.encode(), field.encode())
    return PREFIX + base64.b64encode(nonce + ct).decode()


def open_(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not value.startswith(PREFIX):
        raise ValueError(f"{field} is not encrypted")
    raw = base64.b64decode(value[len(PREFIX):])
    return AESGCM(_k()[0]).decrypt(raw[:12], raw[12:], field.encode()).decode()


def is_sealed(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)

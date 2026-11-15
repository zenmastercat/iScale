"""Write-only secret store for admin-entered keys (LLM provider key, Google Maps key).

Kept in data/secrets/<scope>.json with 0600 permissions, never returned by the API.
An environment variable of the same name wins (useful for the server operator).
"""

from __future__ import annotations

import json
import os
import re

from .config import DATA_DIR

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _path(scope: str):
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", scope):
        raise ValueError("bad scope")
    return DATA_DIR / "secrets" / f"{scope}.json"


def _read(scope: str) -> dict:
    p = _path(scope)
    return json.loads(p.read_text()) if p.is_file() else {}


def get(scope: str, name: str) -> str | None:
    return os.environ.get(name) or _read(scope).get(name) or _read("server").get(name)


def has(scope: str, name: str) -> bool:
    return bool(get(scope, name))


def put(scope: str, name: str, value: str | None) -> None:
    if not NAME_RE.match(name):
        raise ValueError("bad secret name")
    p = _path(scope)
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    data = _read(scope)
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, p)

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="civil-test-")
os.environ["CIVIL_DATA_DIR"] = _tmp
os.environ["CIVIL_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
# never touch a running ejabberd: unit tests see the chat server as "down"
os.environ["CIVIL_XMPP_API_PORT"] = "9"
os.environ["CIVIL_XMPP_WS_PORT"] = "9"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_signin_limit(monkeypatch):
    """Every TestClient shares one address; the per-address sign-in limit is tested on its own in test_auth."""
    from civil import auth

    monkeypatch.setattr(auth, "SIGNIN_LIMIT", (10**9, 60))
    monkeypatch.setattr(auth, "_signin_log", {})

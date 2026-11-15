"""Sign in from tests the way the browser does: device key + signed nonce."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient

from civil.api import app

HDR = {"X-Civil-Scan": "1"}
_admin: TestClient | None = None
_clients: dict[str, TestClient] = {}


def device_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def spki(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def sign_raw(key: ec.EllipticCurvePrivateKey, msg: bytes) -> str:
    r, s = decode_dss_signature(key.sign(msg, ec.ECDSA(hashes.SHA256())))
    return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()  # WebCrypto format


def login(client: TestClient, username: str, key: ec.EllipticCurvePrivateKey):
    ch = client.post("/api/auth/challenge", json={"username": username})
    assert ch.status_code == 200, ch.text
    ch = ch.json()
    return client.post("/api/auth/login", json={"username": username, "nonce": ch["nonce"],
                                                "signature": sign_raw(key, ch["message"].encode()),
                                                "public_key": spki(key)})


def admin() -> TestClient:
    """The setup admin of the test company (created on first use)."""
    global _admin
    if _admin is None:
        c = TestClient(app, headers=HDR)
        st = c.get("/api/auth/state").json()
        if st["setup_needed"]:
            r = c.post("/api/auth/setup", json={"company": "Test Works Dept", "username": "admin", "display_name": "Admin"})
            assert r.status_code == 200, r.text
        key = device_key()
        assert login(c, "admin", key).status_code == 200
        _admin = c
    return _admin


def client_for(username: str, role: str = "engineer") -> TestClient:
    a = admin()
    if username == "admin":
        return a
    if username in _clients:
        return _clients[username]
    r = a.post("/api/team", json={"username": username, "display_name": username.title(), "role": role})
    assert r.status_code in (200, 409), r.text
    c = TestClient(app, headers=HDR)
    r = login(c, username, device_key())
    assert r.status_code == 200, r.text
    _clients[username] = c
    return c

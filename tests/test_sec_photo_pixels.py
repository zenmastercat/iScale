"""Security review L2: refuse photos by pixel count (read from the header) before the full decode."""

import struct
import zlib

from helpers import client_for


def _png_header_only(w: int, h: int) -> bytes:
    """A few hundred bytes that claim to be a w x h greyscale PNG (decompression-bomb shape)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * (w + 1) * 4, 9)  # first rows only
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_huge_pixel_count_refused_before_decode(monkeypatch):
    calls = []
    import cv2
    real = cv2.imdecode
    monkeypatch.setattr(cv2, "imdecode", lambda *a, **k: calls.append(1) or real(*a, **k))
    c = client_for("sec.photo")
    p = c.post("/api/pins", json={"lat": 13.70, "lon": 100.50, "severity": "medium"}).json()
    bomb = _png_header_only(20_000, 20_000)
    assert len(bomb) < 5_000
    r = c.post(f"/api/pins/{p['id']}/photo", files={"file": ("bomb.png", bomb, "image/png")})
    assert r.status_code == 413, r.text
    assert "pixels" in r.json()["detail"]
    assert not calls, "the full decode must not run"
    from civil import images

    assert images.MAX_PIXELS <= 100_000_000

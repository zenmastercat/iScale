"""Pixel-count guard: read an image's size from its header before any full decode (decompression bombs)."""

from __future__ import annotations

MAX_PIXELS = 60_000_000  # 60 MP: above any phone photo or camera frame this app takes


def check_pixels(src, limit: int = MAX_PIXELS) -> tuple[int, int] | None:
    """(width, height) from the header, or None when Pillow cannot identify the format.

    Raises ValueError when width x height exceeds `limit`. `src` is a path or a binary file object.
    """
    from PIL import Image

    try:
        with Image.open(src) as im:
            w, h = im.size
    except Image.DecompressionBombError:
        raise ValueError(f"image has more than {limit // 1_000_000} million pixels") from None
    except Exception:  # noqa: BLE001 - unknown format: the caller's decoder decides
        return None
    if w * h > limit:
        raise ValueError(f"image has {w * h / 1e6:.0f} million pixels (limit {limit // 1_000_000} million)")
    return w, h

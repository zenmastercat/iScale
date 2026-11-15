from __future__ import annotations

from .base import Decoder, DecoderError
from .demo import DemoDecoder
from .external import load_external
from .lingbot_clip import LingbotClipDecoder, PotholeVideoDecoder
from .ply_import import PlyImportDecoder


def registry() -> dict[str, Decoder]:
    decs: dict[str, Decoder] = {d.name: d for d in (PotholeVideoDecoder(), DemoDecoder(), PlyImportDecoder(), LingbotClipDecoder())}
    for ext in load_external():
        if ext.name in decs:
            continue
        decs[ext.name] = ext
    return decs


def get_decoder(name: str) -> Decoder:
    decs = registry()
    if name not in decs:
        raise DecoderError(f"unknown decoder '{name}'")
    return decs[name]


__all__ = ["Decoder", "DecoderError", "registry", "get_decoder"]

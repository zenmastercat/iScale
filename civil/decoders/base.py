"""Decoder plug-in interface.

A decoder turns a survey's raw input (video, images, a LiDAR export, ...) into a
Reconstruction: points (+ optional colours, camera poses, per-point labels, GPS).
The app never runs a learned model itself; a decoder may call one as an external
process (see external.py), import its result (ply_import.py) or synthesise a scene
for testing (demo.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..pointcloud import Reconstruction


class DecoderError(RuntimeError):
    pass


class Decoder(ABC):
    name: str = "base"
    label: str = "Base decoder"
    description: str = ""
    accepts: tuple[str, ...] = ()  # file kinds: video, images, ply, poses, gps
    internal: bool = False  # created by the app itself, not offered in the UI

    def available(self) -> tuple[bool, str]:
        """(usable now?, reason if not)."""
        return True, ""

    def describe(self) -> dict:
        ok, why = self.available()
        return {"name": self.name, "label": self.label, "description": self.description,
                "accepts": list(self.accepts), "available": ok, "unavailable_reason": why,
                "internal": self.internal}

    @abstractmethod
    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        """Read files from input_dir, write scratch files to work_dir, return a Reconstruction."""


VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def classify_inputs(input_dir: Path) -> dict[str, list[Path]]:
    kinds: dict[str, list[Path]] = {"video": [], "images": [], "ply": [], "poses": [], "gps": [], "other": []}
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        stem = p.stem.lower()
        if ext in VIDEO_EXT:
            kinds["video"].append(p)
        elif ext in IMAGE_EXT:
            kinds["images"].append(p)
        elif ext == ".ply":
            kinds["ply"].append(p)
        elif ext == ".csv" and ("gps" in stem or "gnss" in stem or "track" in stem):
            kinds["gps"].append(p)
        elif ext in {".json", ".txt"} and ("pose" in stem or "traj" in stem or "camera" in stem):
            kinds["poses"].append(p)
        else:
            kinds["other"].append(p)
    return kinds

"""Run an external reconstruction model (LingBot-Map or any other) as a separate process.

Configured in config/decoders.json, for example:

    "lingbot_map": {
      "label": "LingBot-Map",
      "enabled": true,
      "command": ["/path/to/venv/bin/python", "/path/to/run.py", "--input", "{frames_dir}", "--out", "{output}"],
      "extract_frames": {"fps": 3, "max_side": 1024},
      "outputs": {"points": "points.ply", "poses": "poses.json"},
      "meta": {"metric": false, "up_axis": "auto"},
      "timeout_s": 7200
    }

Placeholders in "command": {input} first video or the input folder, {input_dir},
{frames_dir} extracted frames (when extract_frames is set), {python} civil-scan's own
Python (for adapters/), {output} the folder the
model must write into.  The command runs without a shell, in its own process, with
a timeout; its stdout/stderr go to decoder.log in the survey's work folder.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import CONFIG_DIR, ROOT, SECRET_ENV
from ..pointcloud import Reconstruction, read_gps_csv
from .base import Decoder, DecoderError, classify_inputs
from .ply_import import load_outputs

PLACEHOLDERS = ("{python}", "{input}", "{input_dir}", "{frames_dir}", "{output}")


def find_ffmpeg(cfg: dict) -> str | None:
    p = cfg.get("ffmpeg") or os.environ.get("CIVIL_FFMPEG") or shutil.which("ffmpeg")
    return p if p and Path(p).exists() else None


class ExternalDecoder(Decoder):
    def __init__(self, key: str, cfg: dict, global_cfg: dict):
        self.name = key
        self.cfg = cfg
        self.global_cfg = global_cfg
        self.label = cfg.get("label", key)
        self.description = cfg.get("description", "External reconstruction model run as a separate process.")
        self.accepts = tuple(cfg.get("accepts", ("video", "images")))

    def available(self) -> tuple[bool, str]:
        if not self.cfg.get("enabled", False):
            return False, "disabled in config/decoders.json (set enabled: true and the command)"
        cmd = self.cfg.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
            return False, "command must be a non-empty list of strings"
        exe = sys.executable if cmd[0] == "{python}" else cmd[0]
        if not (Path(exe).exists() or shutil.which(exe)):
            return False, f"executable not found: {exe}"
        if self.cfg.get("extract_frames") and not find_ffmpeg(self.global_cfg):
            return False, "extract_frames needs ffmpeg (set 'ffmpeg' in config/decoders.json or CIVIL_FFMPEG)"
        return True, ""

    def _extract_frames(self, video: Path, frames_dir: Path, log) -> None:
        ff = find_ffmpeg(self.global_cfg)
        if not ff:
            raise DecoderError("ffmpeg not found")
        opt = self.cfg.get("extract_frames") or {}
        fps = float(opt.get("fps", 2))
        side = int(opt.get("max_side", 1280))
        frames_dir.mkdir(parents=True, exist_ok=True)
        vf = f"fps={fps},scale='if(gt(iw,ih),min({side},iw),-2)':'if(gt(iw,ih),-2,min({side},ih))'"
        cmd = [ff, "-nostdin", "-v", "error", "-i", str(video), "-vf", vf, "-q:v", "2", str(frames_dir / "%06d.jpg")]
        r = subprocess.run(cmd, stdout=log, stderr=log, timeout=3600, check=False)
        if r.returncode != 0 or not any(frames_dir.iterdir()):
            raise DecoderError("frame extraction failed; see decoder.log")

    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        ok, why = self.available()
        if not ok:
            raise DecoderError(why)
        kinds = classify_inputs(input_dir)
        out_dir = work_dir / "decoder_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = work_dir / "frames"
        log_path = work_dir / "decoder.log"
        with open(log_path, "ab") as log:
            primary = kinds["video"][0] if kinds["video"] else input_dir
            if self.cfg.get("extract_frames"):
                if kinds["video"]:
                    self._extract_frames(kinds["video"][0], frames_dir, log)
                elif kinds["images"]:
                    frames_dir.mkdir(parents=True, exist_ok=True)
                    for i, img in enumerate(kinds["images"]):
                        shutil.copy2(img, frames_dir / f"{i:06d}{img.suffix.lower()}")
                else:
                    raise DecoderError("this decoder needs a video or images")
            subs = {"{python}": sys.executable, "{input}": str(primary), "{input_dir}": str(input_dir),
                    "{frames_dir}": str(frames_dir), "{output}": str(out_dir)}
            cmd = []
            for part in self.cfg["command"]:
                for k, v in subs.items():
                    part = part.replace(k, v)
                cmd.append(part)
            env = {**{k: v for k, v in os.environ.items() if k not in SECRET_ENV}, **{k: str(v) for k, v in (self.cfg.get("env") or {}).items()}}
            log.write(("\n$ " + " ".join(cmd) + "\n").encode())
            log.flush()
            try:
                r = subprocess.run(cmd, cwd=self.cfg.get("workdir") or str(ROOT), env=env, stdout=log, stderr=log,
                                   timeout=float(self.cfg.get("timeout_s", 7200)), check=False)
            except subprocess.TimeoutExpired as e:
                raise DecoderError(f"decoder timed out after {e.timeout:.0f}s") from e
            except OSError as e:
                raise DecoderError(f"could not start decoder: {e}") from e
            if r.returncode != 0:
                raise DecoderError(f"decoder exited with code {r.returncode}; see decoder.log")
        outs = self.cfg.get("outputs") or {}
        rec = load_outputs(out_dir, outs.get("points"), outs.get("poses"), outs.get("labels"), outs.get("gps"))
        if rec.gps is None and kinds["gps"]:
            rec.gps = read_gps_csv(kinds["gps"][0])
        rec.meta.update(self.cfg.get("meta") or {})
        rec.meta["decoder"] = self.name
        return rec


def load_external(config_path: Path | None = None) -> list[ExternalDecoder]:
    path = config_path or (CONFIG_DIR / "decoders.json")
    if not path.is_file():
        return []
    raw = json.loads(path.read_text())
    global_cfg = {k: v for k, v in raw.items() if not isinstance(v, dict)}
    out = []
    for key, cfg in raw.items():
        if isinstance(cfg, dict) and not key.startswith("_"):
            out.append(ExternalDecoder(key, cfg, global_cfg))
    return out

"""Decoders for the video pipeline.

pothole_video  user-facing: upload a drive video (+ gps.csv); the survey becomes a
               video job (civil.video.job) that creates one lingbot_clip survey per
               detection window.
lingbot_clip   internal: frames of one window -> LingBot-Map batch_demo.py (separate
               process, the user's conda env) -> NPZ -> adapters/lingbot_map.convert
               (with detector boxes as labelled points) -> Reconstruction.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

from ..config import ROOT, SECRET_ENV
from ..pointcloud import Reconstruction
from .base import Decoder, DecoderError
from .ply_import import load_outputs


def _video_cfg() -> dict:
    from ..video.job import video_config

    return video_config()


def _adapter():
    spec = importlib.util.spec_from_file_location("lingbot_adapter", ROOT / "adapters" / "lingbot_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_gpu_gb() -> float | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        r = subprocess.run([smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, check=True)
        return max(float(x) for x in r.stdout.split()) / 1024
    except (subprocess.SubprocessError, ValueError):
        return None


def lingbot_ready(lb: dict) -> tuple[bool, str]:
    from ..worker import takes

    if takes("lingbot_clip"):  # CIVIL_3D=remote: the GPU worker runs LingBot-Map, not this server
        return True, ""
    for key in ("python", "repo", "model"):
        if not Path(lb.get(key, "")).exists():
            return False, f"lingbot.{key} not found: {lb.get(key)} (config/video.json)"
    if not (Path(lb["repo"]) / "demo_render" / "batch_demo.py").is_file():
        return False, "batch_demo.py not found in the LingBot-Map repo"
    return True, ""


class PotholeVideoDecoder(Decoder):
    name = "pothole_video"
    label = "Drive video → pothole detector → LingBot 3D clips"
    description = ("Scans the video with the Roboflow pothole model; every detection opens a window 10 s before to "
                   "10 s after, and only those windows are turned into 3D by LingBot-Map. Add gps.csv for real-world scale.")
    accepts = ("video", "gps")

    def available(self) -> tuple[bool, str]:
        cfg = _video_cfg()
        env = cfg["detector"].get("api_key_env", "ROBOFLOW_API_KEY")
        if cfg["detector"].get("kind") == "roboflow" and not os.environ.get(env):
            return False, f"{env} is not set for the server (start it with the Roboflow key in the environment)"
        return lingbot_ready(cfg["lingbot"])

    def decode(self, input_dir, work_dir, params):  # handled by civil.video.job
        raise DecoderError("pothole_video runs as a video job")


class LingbotClipDecoder(Decoder):
    name = "lingbot_clip"
    label = "LingBot-Map clip (internal)"
    description = "One detection window of a video job."
    accepts = ()
    internal = True

    def available(self) -> tuple[bool, str]:
        return lingbot_ready(_video_cfg()["lingbot"])

    def decode(self, input_dir: Path, work_dir: Path, params: dict) -> Reconstruction:
        lb = _video_cfg()["lingbot"]
        ok, why = lingbot_ready(lb)
        if not ok:
            raise DecoderError(why)
        need = float(lb.get("min_free_gpu_gb", 13))
        free = free_gpu_gb()
        if free is not None and free < need:
            raise DecoderError(f"GPU busy: {free:.1f} GB free, LingBot-Map needs about {need:.0f} GB. "
                               "Free the GPU (for example, unload the Ollama model), then choose Try again.")
        frames = input_dir / "frames"
        if not frames.is_dir() or len(list(frames.glob("*.jpg"))) < 2:
            raise DecoderError("clip has fewer than 2 frames")
        meta = json.loads((input_dir / "boxes.json").read_text())
        raw = work_dir / "lingbot_raw"
        raw.mkdir(parents=True, exist_ok=True)
        if lb.get("bf16_weights"):  # wrapper that runs batch_demo.py with bfloat16 weights (16 GB GPUs)
            head = [lb["python"], str(ROOT / "adapters" / "lingbot_lowmem.py"), "--lingbot-repo", lb["repo"]]
        else:
            head = [lb["python"], str(Path(lb["repo"]) / "demo_render" / "batch_demo.py")]
        cmd = [*head, "--input_folder", str(frames), "--output_folder", str(raw), "--model_path", lb["model"],
               "--mode", lb.get("mode", "streaming"), "--save_predictions", "--no_render", *lb.get("extra_args", [])]
        log = work_dir / "decoder.log"
        with open(log, "ab") as fh:
            fh.write(("\n$ " + " ".join(cmd) + "\n").encode())
            fh.flush()
            try:
                env = {**{k: v for k, v in os.environ.items() if k not in SECRET_ENV}, **{k: str(v) for k, v in (lb.get("env") or {}).items()}}
                r = subprocess.run(cmd, cwd=lb["repo"], env=env, stdout=fh, stderr=fh,
                                   timeout=float(lb.get("timeout_s", 3600)), check=False)
            except subprocess.TimeoutExpired as e:
                raise DecoderError(f"LingBot-Map timed out after {e.timeout:.0f}s") from e
        if r.returncode != 0:
            tail = log.read_text(errors="replace")[-600:]
            raise DecoderError(f"LingBot-Map exited with code {r.returncode}; see work/decoder.log. Last lines: {tail}")
        boxes = {int(k): v for k, v in meta.get("boxes", {}).items()}
        conv = work_dir / "decoded"
        info = _adapter().convert(raw, conv, fps=float(params.get("clip_fps", 10)), boxes=boxes,
                                  t0=float(params.get("clip_start", 0.0)),
                                  max_depth=float(params["max_depth"]) if params.get("max_depth") else None)
        rec = load_outputs(conv, "points.ply", "poses.json", "labels.json")
        if (input_dir / "gps.csv").is_file():
            from ..pointcloud import read_gps_csv

            rec.gps = read_gps_csv(input_dir / "gps.csv")
        rec.meta.update({"metric": False, "up_axis": "auto", "camera_convention": "opencv",
                         "decoder": self.name, "lingbot": info,
                         "camera_height_m": params.get("camera_height_m")})
        return rec


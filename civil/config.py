from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("CIVIL_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("CIVIL_DATA_DIR", ROOT / "data"))
STATIC_DIR = ROOT / "static"

# Defaults for the demo project (KMUTNB area, Bangkok). Change per project.
DEFAULT_ORIGIN = (13.8196, 100.5137)

# Host names the server answers to (DNS-rebinding protection). Add your machine's name or IP
# here (comma-separated) if you deliberately serve the app on a network.
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("CIVIL_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]").split(",") if h.strip()]

# Secrets that must not be handed to decoder subprocesses
SECRET_ENV = ("ROBOFLOW_API_KEY", "CIVIL_DB_KEY")

# Upload limits
MAX_UPLOAD_BYTES = int(os.environ.get("CIVIL_MAX_UPLOAD_MB", "4096")) * 1024 * 1024


def unit_costs() -> dict:
    return json.loads((CONFIG_DIR / "unit_costs.json").read_text())


def analysis_params() -> dict:
    p = CONFIG_DIR / "analysis.json"
    base = {
        "road_half_width_m": 3.6,
        "segment_length_m": 25.0,
        "raster_m": 0.1,
        "pothole_min_depth_m": 0.025,
        "pothole_min_area_m2": 0.04,
        "pothole_max_depth_m": 0.4,
        "roughness_std_m": 0.007,
        "roughness_min_area_m2": 1.0,
        "heave_min_height_m": 0.025,
        "trip_hazard_step_m": 0.02,
        "sidewalk_band_m": [0.6, 2.6],
        "object_min_height_m": 0.4,
    }
    if p.is_file():
        base.update({k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")})
    return base

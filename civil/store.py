"""File-based project store (JSON + NPZ), safe for one server process.

data/projects/<pid>/
  project.json
  workorders.json
  surveys/<sid>/survey.json      status, decoder, params, notes
  surveys/<sid>/input/           uploaded files
  surveys/<sid>/work/            decoder scratch + decoder.log
  surveys/<sid>/recon.npz        aligned reconstruction (ENU, metres)
  surveys/<sid>/analysis.json    segments, findings, path
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from .config import DATA_DIR

ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock(pid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.RLock())


def new_id() -> str:
    return secrets.token_hex(5)


def check_id(x: str) -> str:
    if not isinstance(x, str) or not ID_RE.match(x):
        raise KeyError("invalid id")
    return x


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    tmp.replace(path)


def _read_json(path: Path, default=None):
    if not path.is_file():
        if default is not None:
            return default
        raise KeyError(f"not found: {path.name}")
    return json.loads(path.read_text())


def projects_dir() -> Path:
    return DATA_DIR / "projects"


def project_dir(pid: str) -> Path:
    return projects_dir() / check_id(pid)


def survey_dir(pid: str, sid: str) -> Path:
    return project_dir(pid) / "surveys" / check_id(sid)


# --- projects ---------------------------------------------------------------
def create_project(name: str, origin_lat: float, origin_lon: float, company_id: str | None = None) -> dict:
    if not (-90 <= origin_lat <= 90 and -180 <= origin_lon <= 180):
        raise ValueError("origin out of range")
    pid = new_id()
    proj = {"id": pid, "name": name[:120] or "Untitled", "origin_lat": origin_lat, "origin_lon": origin_lon,
            "created": time.time(), "surveys": [], "baseline": None, "company_id": company_id}
    _write_json(project_dir(pid) / "project.json", proj)
    _write_json(project_dir(pid) / "workorders.json", [])
    return proj


def adopt_orphan_projects(company_id: str) -> None:
    """Projects made before accounts existed go to the first company."""
    for proj in list_projects():
        if not proj.get("company_id"):
            proj["company_id"] = company_id
            save_project(proj)


def list_projects(company_id: str | None = None) -> list[dict]:
    out = []
    if projects_dir().is_dir():
        for d in sorted(projects_dir().iterdir()):
            f = d / "project.json"
            if f.is_file():
                out.append(json.loads(f.read_text()))
    if company_id is not None:
        out = [p for p in out if p.get("company_id") == company_id]
    out.sort(key=lambda p: p["created"], reverse=True)
    return out


def get_project(pid: str) -> dict:
    return _read_json(project_dir(pid) / "project.json")


def save_project(proj: dict) -> None:
    _write_json(project_dir(proj["id"]) / "project.json", proj)


def delete_project(pid: str) -> None:
    d = project_dir(pid)
    if d.is_dir():
        shutil.rmtree(d)


# --- surveys -----------------------------------------------------------------
def create_survey(pid: str, name: str, decoder: str, params: dict) -> dict:
    with lock(pid):
        proj = get_project(pid)
        sid = new_id()
        sv = {"id": sid, "project_id": pid, "name": name[:120] or "Survey", "decoder": decoder, "params": params,
              "status": "queued", "stage": "", "error": None, "created": time.time(), "notes": [], "stats": {}}
        d = survey_dir(pid, sid)
        (d / "input").mkdir(parents=True, exist_ok=True)
        (d / "work").mkdir(parents=True, exist_ok=True)
        _write_json(d / "survey.json", sv)
        proj["surveys"].append(sid)
        save_project(proj)
        return sv


def get_survey(pid: str, sid: str) -> dict:
    return _read_json(survey_dir(pid, sid) / "survey.json")


def update_survey(pid: str, sid: str, **fields) -> dict:
    with lock(pid):
        sv = get_survey(pid, sid)
        sv.update(fields)
        _write_json(survey_dir(pid, sid) / "survey.json", sv)
        return sv


def list_surveys(pid: str) -> list[dict]:
    proj = get_project(pid)
    out = []
    for sid in proj["surveys"]:
        try:
            out.append(get_survey(pid, sid))
        except KeyError:
            pass
    return out


def get_analysis(pid: str, sid: str) -> dict:
    return _read_json(survey_dir(pid, sid) / "analysis.json")


def save_analysis(pid: str, sid: str, an: dict) -> None:
    _write_json(survey_dir(pid, sid) / "analysis.json", an)


def recon_path(pid: str, sid: str) -> Path:
    return survey_dir(pid, sid) / "recon.npz"


# --- work orders ---------------------------------------------------------------
def get_workorders(pid: str) -> list[dict]:
    return _read_json(project_dir(pid) / "workorders.json", default=[])


def save_workorders(pid: str, wos: list[dict]) -> None:
    _write_json(project_dir(pid) / "workorders.json", wos)


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base[:120] or "upload"

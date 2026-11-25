"""Rich project metadata validation, per-user wizard drafts, and project site photos."""

from __future__ import annotations

import datetime
import math
import re
import time
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, db, measure, measure_api, scene_scale, store
from .config import DEFAULT_ORIGIN
from .forge.types import validate_forge_params

router = APIRouter(prefix="/api")

MAX_PROJECT_JSON_BYTES = 65_536  # wizard metadata and draft payloads are a few KB
MAX_PROJECT_PHOTOS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SOURCE_KINDS = ("pothole_video", "ply_import", "forge_slam", "photos", "demo")

Lat = Annotated[float, Field(ge=-90.0, le=90.0, allow_inf_nan=False)]
Lon = Annotated[float, Field(ge=-180.0, le=180.0, allow_inf_nan=False)]
CoordPair = Annotated[list[float], Field(min_length=2, max_length=2)]


def _check_date(v: str) -> str:
    s = v.strip()
    if not s:
        return ""
    if not DATE_RE.match(s):
        raise ValueError("survey_date must be YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        raise ValueError("survey_date is not a valid calendar date") from None
    return s


def _check_route(pts: list[list[float]]) -> list[list[float]]:
    out = []
    for p in pts:
        lat, lon = p[0], p[1]
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError("route coordinates must be finite numbers")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError("route coordinates out of range")
        out.append([round(float(lat), 7), round(float(lon), 7)])
    return out


class SampleMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_label: str = Field(default="", max_length=60)
    area_m2: float = Field(gt=0, le=10_000, allow_inf_nan=False)
    width_m: float = Field(gt=0, le=500, allow_inf_nan=False)
    length_m: float = Field(gt=0, le=500, allow_inf_nan=False)
    pct_area: float | None = Field(default=None, ge=0, le=1_000, allow_inf_nan=False)


class ScaleSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure_ref: str = Field(default="", max_length=20)
    ref_width_cm: float | None = Field(default=None, ge=0.5, le=5_000, allow_inf_nan=False)
    ref_length_cm: float | None = Field(default=None, ge=0.5, le=10_000, allow_inf_nan=False)
    scene_ref_ids: list[str] = Field(default_factory=list, max_length=10)
    camera_height_m: float | None = Field(default=None, ge=0.2, le=10.0, allow_inf_nan=False)
    heading_deg: float | None = Field(default=None, ge=0.0, le=360.0, allow_inf_nan=False)
    up_axis: Literal["", "z", "y", "-y"] = ""
    metric: bool = False
    sample_measurement: SampleMeasurement | None = None

    @field_validator("measure_ref")
    @classmethod
    def _valid_measure_ref(cls, v: str) -> str:
        s = v.strip()
        if not s:
            return ""
        known = {r["id"] for r in measure.presets()["refs"]}
        if s not in known:
            raise ValueError(f"unknown measure_ref {s!r}")
        return s

    @field_validator("scene_ref_ids")
    @classmethod
    def _valid_scene_refs(cls, ids: list[str]) -> list[str]:
        if not ids:
            return []
        known = {o["id"] for o in scene_scale.load_catalog()["objects"]}
        out: list[str] = []
        for x in ids:
            if not isinstance(x, str) or x not in known:
                raise ValueError(f"unknown scene_ref_id {x!r}")
            if x not in out:
                out.append(x)
        return out


class ReportPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: Literal["metric", "imperial"] = "metric"
    materials_preset: Literal["company", "doh_defaults"] = "company"
    include_doh_materials: bool = True
    export_formats: list[Literal["csv", "geojson", "ply"]] = Field(
        default_factory=lambda: ["csv", "geojson"], max_length=3
    )

    @field_validator("export_formats")
    @classmethod
    def _dedupe_formats(cls, fmts: list[str]) -> list[str]:
        return list(dict.fromkeys(fmts))


class ProjectCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    origin_lat: Lat = DEFAULT_ORIGIN[0]
    origin_lon: Lon = DEFAULT_ORIGIN[1]
    road_name: str = Field(default="", max_length=160)
    client: str = Field(default="", max_length=160)
    survey_date: str = Field(default="", max_length=10)
    notes: str = Field(default="", max_length=2000)
    route: list[CoordPair] = Field(default_factory=list, max_length=200)
    scale_setup: ScaleSetup = Field(default_factory=ScaleSetup)
    report_prefs: ReportPrefs = Field(default_factory=ReportPrefs)

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("name must not be empty")
        return s

    @field_validator("road_name", "client", "notes")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("survey_date")
    @classmethod
    def _date(cls, v: str) -> str:
        return _check_date(v)

    @field_validator("route")
    @classmethod
    def _route(cls, v: list[list[float]]) -> list[list[float]]:
        return _check_route(v)


class ProjectDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(default=0, ge=0, le=5)
    name: str = Field(default="", max_length=120)
    road_name: str = Field(default="", max_length=160)
    client: str = Field(default="", max_length=160)
    survey_date: str = Field(default="", max_length=10)
    notes: str = Field(default="", max_length=2000)
    origin_lat: Lat | None = None
    origin_lon: Lon | None = None
    loc_mode: Literal["point", "route"] = "point"
    route: list[CoordPair] = Field(default_factory=list, max_length=200)
    sources: list[Literal["pothole_video", "ply_import", "forge_slam", "photos", "demo"]] = Field(
        default_factory=list, max_length=5
    )
    source_names: dict[str, str] = Field(default_factory=dict)
    forge_params: dict = Field(default_factory=dict)
    scale_setup: ScaleSetup = Field(default_factory=ScaleSetup)
    report_prefs: ReportPrefs = Field(default_factory=ReportPrefs)
    had_files: bool = False

    @field_validator("survey_date")
    @classmethod
    def _date(cls, v: str) -> str:
        return _check_date(v)

    @field_validator("route")
    @classmethod
    def _route(cls, v: list[list[float]]) -> list[list[float]]:
        return _check_route(v)

    @field_validator("sources")
    @classmethod
    def _dedupe_sources(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @field_validator("source_names")
    @classmethod
    def _check_source_names(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > len(SOURCE_KINDS):
            raise ValueError("too many source_names entries")
        out = {}
        for k, name in v.items():
            if k not in SOURCE_KINDS:
                raise ValueError(f"unknown source {k!r}")
            if not isinstance(name, str) or len(name) > 120:
                raise ValueError("source name must be a string up to 120 chars")
            out[k] = name.strip()
        return out

    @field_validator("forge_params")
    @classmethod
    def _check_forge_params(cls, v: dict) -> dict:
        if not v:
            return {}
        return validate_forge_params(v)


def _draft_scope(me: dict) -> str:
    # uid is already the keyed hash (no plaintext username stored in SQLite)
    return f"draft:{me['company_id']}:{me['uid']}"


@router.get("/project-draft")
def get_draft(request: Request):
    me = measure_api.require_staff(request)
    return {"draft": db.get_setting(_draft_scope(me), "create_project", None)}


@router.put("/project-draft")
def put_draft(body: ProjectDraftIn, request: Request):
    me = measure_api.require_staff(request)
    draft = {**body.model_dump(), "updated_at": time.time()}
    db.set_setting(_draft_scope(me), "create_project", draft)
    return {"draft": draft}


@router.delete("/project-draft")
def delete_draft(request: Request):
    me = measure_api.require_staff(request)
    db.run("DELETE FROM settings WHERE scope=? AND key=?", _draft_scope(me), "create_project")
    return {"ok": True}


# --- project site / reference photos --------------------------------------------------------
def _photo_path(pid: str, photo_id: str):
    return store.project_dir(pid) / "photos" / f"{store.check_id(photo_id)}.jpg"


def _photo_url(pid: str, photo_id: str, created: float) -> str:
    return f"/api/projects/{pid}/photos/{photo_id}?v={int(created)}"


@router.get("/projects/{pid}/photos")
def list_photos(pid: str):
    proj = store.get_project(pid)
    photos = []
    for p in proj.get("photos") or []:
        if _photo_path(pid, p["id"]).is_file():
            photos.append({**p, "url": _photo_url(pid, p["id"], p.get("created", 0))})
    return {"photos": photos}


@router.post("/projects/{pid}/photos")
async def upload_photo(pid: str, request: Request, file: UploadFile = File(...)):
    me = measure_api.require_staff(request)
    proj = store.get_project(pid)
    if len(proj.get("photos") or []) >= MAX_PROJECT_PHOTOS:
        raise HTTPException(400, f"a project can have at most {MAX_PROJECT_PHOTOS} site photos")
    photo_id = store.new_id()
    path = _photo_path(pid, photo_id)
    info = await measure_api._save_photo(file, path)
    rec = {
        "id": photo_id,
        "filename": store.safe_filename(file.filename or "photo.jpg"),
        "w": info["w"],
        "h": info["h"],
        "bytes": info["bytes"],
        "created": time.time(),
        "by": me["uid"],
    }
    with store.lock(pid):
        proj = store.get_project(pid)
        if len(proj.get("photos") or []) >= MAX_PROJECT_PHOTOS:
            path.unlink(missing_ok=True)
            raise HTTPException(400, f"a project can have at most {MAX_PROJECT_PHOTOS} site photos")
        proj.setdefault("photos", []).append(rec)
        store.save_project(proj)
    return {**rec, "url": _photo_url(pid, photo_id, rec["created"])}


@router.get("/projects/{pid}/photos/{photo_id}")
def get_photo(pid: str, photo_id: str):
    path = _photo_path(pid, photo_id)
    if not path.is_file():
        raise HTTPException(404, "no photo")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/projects/{pid}/photos/{photo_id}")
def delete_photo(pid: str, photo_id: str, request: Request):
    measure_api.require_staff(request)
    path = _photo_path(pid, photo_id)
    with store.lock(pid):
        proj = store.get_project(pid)
        before = proj.get("photos") or []
        after = [p for p in before if p.get("id") != photo_id]
        if len(after) == len(before) and not path.is_file():
            raise HTTPException(404, "no photo")
        proj["photos"] = after
        store.save_project(proj)
        path.unlink(missing_ok=True)
    return {"ok": True}

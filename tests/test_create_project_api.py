"""TDD API tests for the Create Project wizard: rich project metadata, validation, drafts, and project photos."""

from __future__ import annotations

import io
import json
import struct
import zlib

from fastapi.testclient import TestClient
from PIL import Image

from civil.api import app
from helpers import HDR, client_for, device_key, login


def _sample_jpeg(w: int = 120, h: int = 90) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (72, 110, 150)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _png_bomb(w: int, h: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * (w + 1) * 4, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_create_project_persists_rich_metadata_and_keeps_minimal_compat():
    c = client_for("wiz.basic")
    # Minimal payload (legacy callers) still works
    minimal = c.post("/api/projects", json={"name": "Legacy caller project"})
    assert minimal.status_code == 200, minimal.text
    mp = minimal.json()
    assert mp["name"] == "Legacy caller project"
    assert mp["road_name"] == ""
    assert mp["route"] == []

    # Rich wizard payload
    payload = {
        "name": "Highway 304 Resurfacing",
        "road_name": "Route 304 km 12-15",
        "client": "DOH District 4",
        "survey_date": "2026-11-25",
        "notes": "Northbound outer lane, morning dry surface",
        "origin_lat": 13.8201,
        "origin_lon": 100.5142,
        "route": [[13.8201, 100.5142], [13.8215, 100.5150], [13.8230, 100.5161]],
        "scale_setup": {
            "measure_ref": "a4",
            "scene_ref_ids": ["th_lane_width_drr"],
            "camera_height_m": 1.35,
            "heading_deg": 45.0,
            "up_axis": "z",
            "metric": False,
        },
        "report_prefs": {
            "units": "metric",
            "materials_preset": "company",
            "include_doh_materials": True,
            "export_formats": ["csv", "geojson", "ply"],
        },
    }
    r = c.post("/api/projects", json=payload)
    assert r.status_code == 200, r.text
    proj = r.json()
    pid = proj["id"]
    fetched = c.get(f"/api/projects/{pid}").json()
    assert fetched["name"] == "Highway 304 Resurfacing"
    assert fetched["road_name"] == "Route 304 km 12-15"
    assert fetched["client"] == "DOH District 4"
    assert fetched["survey_date"] == "2026-11-25"
    assert fetched["notes"] == "Northbound outer lane, morning dry surface"
    assert len(fetched["route"]) == 3
    assert fetched["scale_setup"]["measure_ref"] == "a4"
    assert fetched["scale_setup"]["camera_height_m"] == 1.35
    assert fetched["report_prefs"]["units"] == "metric"
    assert fetched["report_prefs"]["export_formats"] == ["csv", "geojson", "ply"]


def test_create_project_rejects_invalid_inputs_and_oversized_bodies():
    c = client_for("wiz.val")
    # Blank / whitespace name
    assert c.post("/api/projects", json={"name": "   "}).status_code in (400, 422)
    # Name too long
    assert c.post("/api/projects", json={"name": "x" * 121}).status_code == 422
    # Invalid calendar date
    assert c.post("/api/projects", json={"name": "Bad date", "survey_date": "2026-02-30"}).status_code in (400, 422)
    assert c.post("/api/projects", json={"name": "Bad fmt", "survey_date": "25/11/2026"}).status_code in (400, 422)
    # Out-of-range coordinates & NaN
    assert c.post("/api/projects", json={"name": "Bad lat", "origin_lat": 95.0, "origin_lon": 100.0}).status_code == 422
    assert c.post("/api/projects", content=json.dumps({"name": "NaN", "origin_lat": float("nan")}),
                  headers={"content-type": "application/json"}).status_code in (400, 422)
    # Route point out of range or wrong arity or too many points
    assert c.post("/api/projects", json={"name": "Bad route", "route": [[91.0, 100.0]]}).status_code in (400, 422)
    assert c.post("/api/projects", json={"name": "Bad arity", "route": [[13.8, 100.5, 5.0]]}).status_code == 422
    assert c.post("/api/projects", json={"name": "Long route", "route": [[13.8, 100.5]] * 201}).status_code == 422
    # Unknown measure_ref / scene_ref_id / up_axis / extra fields
    assert c.post("/api/projects", json={"name": "Bad ref", "scale_setup": {"measure_ref": "banana"}}).status_code in (400, 422)
    assert c.post("/api/projects", json={"name": "Bad scene", "scale_setup": {"scene_ref_ids": ["nope_id"]}}).status_code in (400, 422)
    assert c.post("/api/projects", json={"name": "Bad axis", "scale_setup": {"up_axis": "w"}}).status_code in (400, 422)
    assert c.post("/api/projects", json={"name": "Extra", "sneaky": 1}).status_code == 422
    # Tight body size cap (64 KB) for project creation JSON
    big = json.dumps({"name": "Big", "notes": "a" * 70_000})
    assert c.post("/api/projects", content=big, headers={"content-type": "application/json"}).status_code == 413


def test_project_draft_lifecycle_isolation_and_validation():
    c1 = client_for("wiz.draft1")
    c2 = client_for("wiz.draft2")
    anon = TestClient(app, headers=HDR)

    # Requires auth
    assert anon.get("/api/project-draft").status_code == 401
    assert anon.put("/api/project-draft", json={"step": 1, "name": "No auth"}).status_code == 401
    # Requires CSRF header on PUT/DELETE
    no_csrf = TestClient(app)
    assert no_csrf.put("/api/project-draft", json={"step": 0}).status_code == 403

    # Initially empty
    assert c1.get("/api/project-draft").json() == {"draft": None}

    # Save draft mid-way
    draft_in = {
        "step": 2,
        "name": "Soi Ari Survey",
        "road_name": "Phahonyothin Soi 7",
        "client": "BMA",
        "survey_date": "2026-11-25",
        "notes": "Draft note",
        "origin_lat": 13.7796,
        "origin_lon": 100.5447,
        "loc_mode": "route",
        "route": [[13.7796, 100.5447], [13.7810, 100.5452]],
        "sources": ["ply_import", "photos"],
        "source_names": {"ply_import": "Ari cloud"},
        "scale_setup": {"measure_ref": "a4", "camera_height_m": 1.4},
        "report_prefs": {"units": "metric", "include_doh_materials": True, "export_formats": ["csv"]},
        "had_files": True,
    }
    saved = c1.put("/api/project-draft", json=draft_in)
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["name"] == "Soi Ari Survey"
    assert saved.json()["draft"]["step"] == 2
    assert isinstance(saved.json()["draft"]["updated_at"], float)

    # Re-fetch returns the same draft for c1, but NOT for c2 (per-user isolation)
    assert c1.get("/api/project-draft").json()["draft"]["name"] == "Soi Ari Survey"
    assert c2.get("/api/project-draft").json() == {"draft": None}

    # Draft validates step bounds, forge_params, unknown keys, body size
    assert c1.put("/api/project-draft", json={"step": 9}).status_code == 422
    assert c1.put("/api/project-draft", json={"forge_params": {"max_ram_bytes": 1}}).status_code in (400, 422)
    assert c1.put("/api/project-draft", json={"unknown_field": 1}).status_code == 422
    assert c1.put("/api/project-draft", content=json.dumps({"notes": "x" * 70_000}),
                  headers={"content-type": "application/json"}).status_code == 413

    # Delete clears draft
    assert c1.delete("/api/project-draft").status_code == 200
    assert c1.get("/api/project-draft").json() == {"draft": None}


def test_project_photos_upload_list_fetch_delete_and_security():
    from civil import auth as A

    c = client_for("wiz.photo")
    pid = c.post("/api/projects", json={"name": "Photo project"}).json()["id"]

    # Valid JPEG upload
    r = c.post(f"/api/projects/{pid}/photos", files={"file": ("pothole_ref.jpg", _sample_jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    ph = r.json()
    assert ph["w"] == 120 and ph["h"] == 90
    assert ph["url"].startswith(f"/api/projects/{pid}/photos/{ph['id']}")

    # List & fetch
    listed = c.get(f"/api/projects/{pid}/photos").json()
    assert len(listed["photos"]) == 1 and listed["photos"][0]["id"] == ph["id"]
    img_r = c.get(f"/api/projects/{pid}/photos/{ph['id']}")
    assert img_r.status_code == 200 and img_r.headers["content-type"] == "image/jpeg"

    # Decompression bomb (>60 MP header) refused with 413 before decode
    bomb_r = c.post(f"/api/projects/{pid}/photos", files={"file": ("bomb.png", _png_bomb(20_000, 20_000), "image/png")})
    assert bomb_r.status_code == 413, bomb_r.text

    # Path traversal photo id refused with 404
    assert c.get(f"/api/projects/{pid}/photos/..%2Fproject.json").status_code == 404
    assert c.delete(f"/api/projects/{pid}/photos/not-a-valid-id!!").status_code == 404

    # Other company cannot view or upload photos on this project
    cid = A.create_company("Rival Works")
    A.create_user("wiz.rival", "Rival", cid, "admin")
    other = TestClient(app, headers=HDR)
    assert login(other, "wiz.rival", device_key()).status_code == 200
    assert other.get(f"/api/projects/{pid}/photos").status_code == 404
    assert other.get(f"/api/projects/{pid}/photos/{ph['id']}").status_code == 404
    assert other.post(f"/api/projects/{pid}/photos", files={"file": ("x.jpg", _sample_jpeg(), "image/jpeg")}).status_code == 404

    # Delete photo removes file and list entry
    assert c.delete(f"/api/projects/{pid}/photos/{ph['id']}").status_code == 200
    assert c.get(f"/api/projects/{pid}/photos/{ph['id']}").status_code == 404
    assert c.get(f"/api/projects/{pid}/photos").json()["photos"] == []

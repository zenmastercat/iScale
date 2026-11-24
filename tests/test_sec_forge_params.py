"""Security review M2: forge knobs from a survey upload must be range-checked (no RAM/CPU exhaustion)."""

import json

import pytest

from helpers import admin


@pytest.fixture(scope="module")
def proj():
    c = admin()
    return c, c.post("/api/projects", json={"name": "forge knobs", "origin_lat": 13.75, "origin_lon": 100.5}).json()


@pytest.mark.parametrize("forge", [
    {"max_ram_bytes": 1e15},             # disables eviction: RAM exhaustion
    {"max_ram_bytes": 10},               # a spill per insert: SSD/CPU thrash
    {"keyframe_dist_m": 0.001},          # a keyframe on every scan
    {"voxel_size_m": 0.0},
    {"max_gaussians": 10**9},
    {"num_threads": 512},
    {"loop_min_time_s": -5},
    {"keyframe_dist_m": float("nan")},   # json.dumps writes NaN; Python's json.loads accepts it
    {"keyframe_dist_m": float("inf")},
    {"max_ram_bytes": True},             # bool is not a number here
    {"keyframe_dist_m": "1.0"},
    {"enable_gsplat": "yes"},
    {"no_such_knob": 1},
])
def test_bad_forge_params_rejected_at_upload(proj, forge):
    c, p = proj
    r = c.post(f"/api/projects/{p['id']}/surveys",
               data={"name": "x", "decoder": "forge_slam", "params": json.dumps({"forge": forge})})
    assert r.status_code == 400, (forge, r.status_code, r.text)
    assert "forge" in r.json()["detail"]


def test_valid_forge_params_pass_the_validator():
    from civil.forge.types import ForgeConfig, validate_forge_params

    ok = validate_forge_params({"max_ram_bytes": 64 * 1024 * 1024, "keyframe_dist_m": 2, "enable_gsplat": False})
    cfg = ForgeConfig(**ok)
    assert cfg.max_ram_bytes == 64 * 1024 * 1024 and cfg.keyframe_dist_m == 2.0 and cfg.enable_gsplat is False
    assert validate_forge_params({}) == {}


def test_decoder_rejects_bad_params_already_stored(tmp_path):
    """Defence in depth: a survey saved before the check (or edited on disk) must not reach ForgeConfig."""
    from civil.decoders.base import DecoderError
    from civil.decoders.forge_slam import ForgeSlamDecoder
    from civil.forge.io import create_synthetic_forge_dataset

    ds = create_synthetic_forge_dataset(tmp_path / "seq", n_keyframes=6, with_pothole=False, with_loop=False, with_dynamic=False)
    with pytest.raises(DecoderError, match="max_ram_bytes"):
        ForgeSlamDecoder().decode(ds, tmp_path / "work", {"forge": {"max_ram_bytes": 10**15}})

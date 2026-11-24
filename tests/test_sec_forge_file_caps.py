"""Security review L3: per-file size caps (and an image pixel cap) for FORGE survey inputs."""

import json

import numpy as np
import pytest


@pytest.fixture
def seq(tmp_path):
    from civil.forge.io import create_synthetic_forge_dataset

    return create_synthetic_forge_dataset(tmp_path / "seq", n_keyframes=6, with_pothole=False, with_loop=False, with_dynamic=False)


@pytest.mark.parametrize("kind,victim", [
    ("scan", "lidar"), ("table", "imu.csv"), ("calibration", "calibration.json"), ("image", "rgb"),
])
def test_oversized_input_file_refused_by_preflight_and_loader(seq, monkeypatch, kind, victim):
    from civil.forge import io as fio

    target = seq / victim
    if target.is_dir():
        target = sorted(target.iterdir())[0]
    monkeypatch.setitem(fio.MAX_FILE_BYTES, kind, target.stat().st_size - 1)
    pf = fio.preflight_check(seq)
    assert not pf["ok"]
    assert any(target.name in i and "too large" in i for i in pf["issues"]), pf["issues"]
    with pytest.raises(ValueError, match="too large"):
        fio.load_forge_sequence(seq)


def test_image_with_huge_pixel_count_refused(seq):
    from civil.forge import io as fio
    from test_sec_photo_pixels import _png_header_only

    rgb = sorted((seq / "rgb").iterdir())[0]
    rgb.write_bytes(_png_header_only(20_000, 20_000))
    pf = fio.preflight_check(seq)
    assert any(rgb.name in i and "pixels" in i for i in pf["issues"]), pf["issues"]


def test_caps_are_sane_defaults():
    from civil.forge.io import MAX_FILE_BYTES

    assert MAX_FILE_BYTES["calibration"] <= 1 << 20
    assert MAX_FILE_BYTES["scan"] <= 512 << 20 and MAX_FILE_BYTES["image"] <= 128 << 20
    assert all(v <= 2 << 30 for v in MAX_FILE_BYTES.values())

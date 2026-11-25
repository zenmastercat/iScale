"""Unit tests for civil.bench_potholes matching, scoring, and analytical GT integration."""

from __future__ import annotations

import math

import pytest

from civil.bench_potholes import (
    AnalyticalPotholeSpec,
    PotholeGT,
    SyntheticRoadScene,
    aggregate_scores,
    match_and_score,
)


def test_analytical_parabolic_pothole_gt_matches_closed_form():
    # Parabolic bowl d(r) = D * (1 - (r/R)^2): Area = pi*R^2, Volume = 0.5 * pi * R^2 * D
    R = 0.35
    D = 0.08
    sc = SyntheticRoadScene(
        name="t", split="dev", length_m=10.0, half_width_m=3.0,
        crown_slope=0.0, grade_slope=0.0, noise_sigma_m=0.0,
        potholes=[AnalyticalPotholeSpec("p1", 5.0, 0.0, R, R, D, 0.0, "parabolic")],
    )
    gt = sc.ground_truth(step_m=0.004)[0]
    expected_area = math.pi * R * R
    expected_vol = 0.5 * expected_area * D
    assert gt.depth_m == pytest.approx(D, abs=1e-4)
    assert gt.area_m2 == pytest.approx(expected_area, rel=0.005)
    assert gt.volume_m3 == pytest.approx(expected_vol, rel=0.005)


def test_match_and_score_separates_hits_misclassifications_and_false_positives():
    gt = [
        PotholeGT("g1", 10.0, 0.0, depth_m=0.06, area_m2=0.20, volume_m3=0.006, diameter_m=0.50),
        PotholeGT("g2", 20.0, 1.0, depth_m=0.08, area_m2=0.40, volume_m3=0.016, diameter_m=0.71),
        PotholeGT("g3", 30.0, 0.0, depth_m=0.05, area_m2=0.15, volume_m3=0.004, diameter_m=0.44),
    ]
    findings = [
        {"type": "pothole", "x": 10.05, "y": -0.02, "metrics": {"depth_max_m": 0.055, "area_m2": 0.18, "volume_m3": 0.0054}},
        {"type": "manhole_sunken", "x": 20.05, "y": 1.02, "metrics": {"depth_max_m": 0.08, "area_m2": 0.40, "volume_m3": 0.016}},
        {"type": "pothole", "x": 50.0, "y": 0.0, "metrics": {"depth_max_m": 0.04, "area_m2": 0.10, "volume_m3": 0.002}},
    ]
    s = match_and_score(gt, findings)
    assert s["n_matched"] == 1
    assert s["false_positives"] == 1
    assert len(s["misclassified"]) == 1 and s["misclassified"][0]["gt_id"] == "g2"
    assert s["missed"] == ["g3"]
    agg = aggregate_scores([s], runtime_s=1.2)
    assert agg["recall"] == pytest.approx(1 / 3, abs=1e-3)
    assert agg["precision"] == pytest.approx(0.5, abs=1e-3)
    assert agg["depth_mae_cm"] == pytest.approx(0.5, abs=1e-2)
    assert agg["area_mae_pct"] == pytest.approx(10.0, abs=1e-2)
    assert agg["vol_mae_pct"] == pytest.approx(10.0, abs=1e-2)

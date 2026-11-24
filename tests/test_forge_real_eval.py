"""Tests for the real-data evaluation metrics and dataset readers (synthetic inputs; no dataset files)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np


def test_ate_is_zero_for_rigidly_moved_copy_and_rpe_sees_drift():
    from civil.forge.real_eval import ate_rpe

    t = np.linspace(0, 100, 1001)
    ref = np.column_stack([t, 10 * np.sin(t / 15), np.zeros_like(t)])
    yaw = 0.7
    R = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    est = ref @ R.T + [5.0, -3.0, 1.0]
    m = ate_rpe(t, est, t, ref)
    assert m["ate_rmse_m"] < 1e-6 and m["rpe_10m_rmse_m"] < 1e-6

    drift = ref + np.column_stack([0.01 * t, np.zeros_like(t), np.zeros_like(t)])  # 1 % scale drift along x
    m2 = ate_rpe(t, drift, t, ref)
    assert 0.5 < m2["rpe_10m_pct"] < 1.5


def test_association_interpolates_and_drops_unmatched_times():
    from civil.forge.real_eval import associate

    t_ref = np.array([0.0, 1.0, 2.0])
    p_ref = np.array([[0.0, 0, 0], [10.0, 0, 0], [20.0, 0, 0]])
    ok, p = associate(np.array([0.5, 1.0, 5.0]), t_ref, p_ref, max_dt=1.0)
    assert ok.tolist() == [True, True, False]
    np.testing.assert_allclose(p[:2, 0], [5.0, 10.0])


def test_pointcloud2_parsing_keeps_xyz_intensity_and_time():
    from civil.forge.datasets import _pointcloud2_xyz_time

    dt = np.dtype({"names": ["x", "y", "z", "intensity", "ring", "time"],
                   "formats": ["f4", "f4", "f4", "f4", "u2", "f4"], "offsets": [0, 4, 8, 16, 20, 24], "itemsize": 32})
    arr = np.zeros(3, dtype=dt)
    arr["x"] = [1.0, 0.0, 5.0]
    arr["y"] = [2.0, 0.0, 0.0]
    arr["intensity"] = [7, 8, 9]
    arr["time"] = [0.0, 0.05, 0.09]
    fields = [SimpleNamespace(name=n, offset=o, datatype=d) for n, o, d in
              [("x", 0, 7), ("y", 4, 7), ("z", 8, 7), ("intensity", 16, 7), ("ring", 20, 4), ("time", 24, 7)]]
    msg = SimpleNamespace(fields=fields, point_step=32, width=3, height=1, data=arr.tobytes())
    xyz, inten, tt = _pointcloud2_xyz_time(msg)
    assert len(xyz) == 2  # the point at the origin is dropped
    np.testing.assert_allclose(xyz[:, 0], [1.0, 5.0])
    np.testing.assert_allclose(inten, [7, 9])
    np.testing.assert_allclose(tt, [0.0, 0.09], atol=1e-7)


def test_ros_image_reads_8uc3_grey_as_three_channels():
    # M2DGR /thermal_image_raw is published as 8UC3 with three equal channels
    from civil.forge.datasets import _ros_image_to_array

    grey = np.arange(4 * 5, dtype=np.uint8).reshape(4, 5)
    data = np.repeat(grey[:, :, None], 3, axis=2).tobytes()
    msg = SimpleNamespace(encoding="8UC3", height=4, width=5, step=15, is_bigendian=0, data=data)
    arr = _ros_image_to_array(msg)
    assert arr.shape == (4, 5, 3) and (arr[:, :, 1] == grey).all()


def test_ecef_to_enu_east_north_up():
    from civil.forge.datasets import ecef_to_enu

    lat, lon = np.radians(31.0), np.radians(121.4)  # Shanghai, where M2DGR was recorded
    a, e2 = 6378137.0, 6.69437999014e-3
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    o = np.array([n * np.cos(lat) * np.cos(lon), n * np.cos(lat) * np.sin(lon), n * (1 - e2) * np.sin(lat)])
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    enu = ecef_to_enu(np.vstack([o + 10 * up, o + 5 * east]), o)
    np.testing.assert_allclose(enu, [[0, 0, 10], [5, 0, 0]], atol=1e-3)


def test_edge_alignment_control_shifts_a_centred_object():
    """A 2 m square 5 m ahead of a far wall, seen head-on: the 2-degree control must move its edges clearly."""
    from civil.forge.real_eval import edge_alignment
    from civil.forge.types import CameraFrame

    def wall(half, step, z):
        g = np.arange(-half, half + 1e-9, step)
        x, y = np.meshgrid(g, g)
        return np.column_stack([x.ravel(), y.ravel(), np.full(x.size, z)])

    pts = np.vstack([wall(1.0, 0.02, 5.0), wall(6.0, 0.05, 15.0)])
    img = np.full((200, 200), 50, np.uint8)
    img[60:141, 60:141] = 200  # the square projects to u, v in [60, 140] with f = 200
    K = np.array([[200.0, 0, 100], [0, 200.0, 100], [0, 0, 1]])
    frame = CameraFrame(0.0, img, K, np.zeros(5), np.eye(4), "thermal", "relative")
    r = edge_alignment(pts, [frame], (np.array([0.0]), np.eye(4)[None]))["+0.000s"]
    assert r["median_px"] < 2.0, r
    assert r["median_px_extrinsic_rotated_2deg"] > r["median_px"] + 2.0, r


def test_same_points_compares_coordinates_within_a_micrometre_not_counts():
    from civil.forge.real_eval import same_points

    a = np.random.default_rng(1).normal(size=(500, 3))
    assert same_points(a, a[::-1].copy())
    assert same_points(a, a + 1e-9)  # runs differ by float rounding (loop closure / GTSAM are not bit-reproducible)
    b = a.copy()
    b[7, 2] += 1e-3
    assert not same_points(a, b)
    assert not same_points(a, a[:-1])


def test_loop_scoring_counts_correct_and_wrong_constraints():
    from civil.forge.real_eval import loop_precision_recall
    from civil.forge.types import ForgeConfig, LoopConstraint

    # straight out-and-back along x: keyframes every 5 m out, then back
    xs = list(range(0, 50, 5)) + list(range(45, -5, -5))
    kfs = [SimpleNamespace(t=float(i * 5), id=i) for i in range(len(xs))]
    t_ref = np.array([k.t for k in kfs])
    p_ref = np.column_stack([xs, np.zeros(len(xs)), np.zeros(len(xs))]).astype(float)
    good = np.eye(4)
    bad = np.eye(4)
    bad[0, 3] = 4.0
    q = len(xs) - 1  # back at x = 0, revisits keyframe 0
    slam = SimpleNamespace(
        cfg=ForgeConfig(loop_min_time_s=20.0, loop_min_dist_m=20.0), keyframes=kfs,
        loop_constraints=[LoopConstraint(0, q, good, 0.05, 0.9, 0.1), LoopConstraint(1, q - 3, bad, 0.05, 0.9, 0.1)],
        loops=SimpleNamespace(summary=lambda: {"rejected_by_reason": {}}),
    )
    r = loop_precision_recall(slam, t_ref, p_ref)
    assert r["accepted"] == 2 and r["correct"] == 1 and r["precision"] == 0.5
    assert r["revisits_closed"] >= 1 and 0 < r["recall"] <= 1


def test_evaluate_dataset_runs_end_to_end_on_a_synthetic_stream(tmp_path):
    from civil.forge.io import create_synthetic_forge_dataset, load_forge_sequence
    from civil.forge.real_eval import evaluate_dataset, make_figures
    from civil.forge.types import ForgeConfig

    ds = create_synthetic_forge_dataset(tmp_path / "seq", n_keyframes=10, with_pothole=True, with_loop=False, with_dynamic=True)
    calib, imu, scans, rgb, thr, _, gt = load_forge_sequence(ds)

    def make_stream(with_cameras: bool):
        ev = [(s.t, 0, s) for s in imu] + [(s.t, 1, s) for s in scans]
        if with_cameras:
            ev += [(f.t, 2, f) for f in rgb] + [(f.t, 3, f) for f in thr]
        return calib, (e for _, _, e in sorted(ev, key=lambda x: (x[0], x[1])))

    rep = evaluate_dataset("synthetic", make_stream, gt[:, 0], gt[:, 1:4], np.zeros(3), tmp_path / "out",
                           ForgeConfig(gsplat_iters=1), ram_cap_bytes=40_000, thermal_is_radiometric=True)
    assert rep["forge"]["ate_rmse_m"] < 0.2
    assert rep["memory_capped"]["ssd_evictions_total"] > 0
    assert rep["memory_capped"]["map_identical_to_uncapped"]
    assert (tmp_path / "out" / "report.json").is_file()
    assert len(make_figures(tmp_path / "out", tmp_path / "fig" / "syn", "synthetic")) == 2

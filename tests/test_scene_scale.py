"""Scene-reference scaling of a monocular 3D clip (civil/scene_scale.py).

A synthetic road is seen by a moving pinhole camera. The cloud is built the way LingBot-Map's
depth maps are back-projected (adapters/lingbot_map.py), in "model units" that are the true
metres divided by an unknown factor S. Tapping the two ends of a known length in one frame must
give back S."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from civil import scene_scale as ss

S_TRUE = 2.7                       # true metres per model unit
CAM_H = 1.35                       # camera height, metres
PITCH = math.radians(12)           # looking down
F_MODEL, MW, MH = 420.0, 518, 280  # model-image intrinsics (pixels)
GEO = {"sx": 518 / 960, "sy": 280 / 540, "crop_top": 0, "y0": 0}   # 960 x 540 frame file -> model image


def c2w_at(y: float, x: float = 0.0, pitch: float = PITCH, h: float = CAM_H) -> np.ndarray:
    """OpenCV camera (x right, y down, z forward) at (x, y, h) metres looking along +y, pitched down."""
    z = np.array([0.0, math.cos(pitch), -math.sin(pitch)])
    xa = np.array([1.0, 0.0, 0.0])
    ya = np.cross(z, xa)
    m = np.eye(4)
    m[:3, :3] = np.stack([xa, ya, z], 1)
    m[:3, 3] = [x, y, h]
    return m


K = np.array([[F_MODEL, 0, MW / 2], [0, F_MODEL, MH / 2], [0, 0, 1.0]])


def ground_depth(c2w: np.ndarray, noise: float, rng) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Back-project every 2nd model pixel that sees the road plane z=0, like the adapter does."""
    vv, uu = np.mgrid[0:MH:2, 0:MW:2]
    d_cam = np.stack([(uu + 0.5 - K[0, 2]) / K[0, 0], (vv + 0.5 - K[1, 2]) / K[1, 1], np.ones_like(uu, float)], -1)
    d_w = d_cam @ c2w[:3, :3].T
    o = c2w[:3, 3]
    t = -o[2] / np.where(d_w[..., 2] < -1e-6, d_w[..., 2], np.nan)  # z-depth multiplier (d_cam has z=1)
    ok = np.isfinite(t) & (t > 0) & (t < 40)
    z = t[ok] * (1 + rng.normal(0, noise, ok.sum()))
    pc = d_cam[ok] * z[:, None]
    return pc @ c2w[:3, :3].T + o, uu[ok], vv[ok]


def scene(noise: float = 0.004, seed: int = 0, floaters: int = 0):
    """(cloud in model units, cameras) for a 12-frame drive along +y."""
    rng = np.random.default_rng(seed)
    pts, cams = [], []
    for i in range(12):
        c = c2w_at(0.8 * i)
        p, _, _ = ground_depth(c, noise, rng)
        pts.append(p)
        cm = c.copy()
        cm[:3, 3] /= S_TRUE
        cams.append(ss.Camera(c2w=cm, K=K.copy(), geo=GEO))
    xyz = np.concatenate(pts) / S_TRUE
    if floaters:
        # sparse junk in front of the road (sky / windscreen noise)
        xyz = np.concatenate([xyz, rng.uniform([-3, 0, 0.2], [3, 12, 1.2], (floaters, 3)) / S_TRUE])
    return xyz.astype(np.float32), cams


def to_frame_px(cam: ss.Camera, p_world_m: np.ndarray) -> list[float]:
    """Project a world point (metres) into the stored frame's pixels."""
    w2c = np.linalg.inv(cam.c2w)
    pc = w2c[:3, :3] @ (np.asarray(p_world_m) / S_TRUE) + w2c[:3, 3]
    u, v = cam.K[0, 0] * pc[0] / pc[2] + cam.K[0, 2], cam.K[1, 1] * pc[1] / pc[2] + cam.K[1, 2]
    return [u / GEO["sx"], (v + GEO["crop_top"]) / GEO["sy"]]


A = np.array([-1.75, 9.0, 0.0])    # two painted marks 3.5 m apart across the road, 9 m ahead of frame 0
B = np.array([1.75, 9.0, 0.0])
KNOWN = 3.5


def ref(cams, frame=0, a=A, b=B, known=KNOWN, rel=0.0):
    return {"points": [{"frame": frame, "xy": to_frame_px(cams[frame], a)}, {"frame": frame, "xy": to_frame_px(cams[frame], b)}],
            "known_m": known, "rel_error": rel}


# ---------------------------------------------------------------------------------------------------------
def test_frame_pixels_map_to_model_pixels_like_the_detector_boxes():
    geo = {"sx": 0.5, "sy": 0.25, "crop_top": 10}
    assert ss.frame_to_model([100, 200], geo) == pytest.approx([50, 40])
    assert ss.frame_to_model([100, 200], None) == pytest.approx([100, 200])


def test_a_ray_through_a_pixel_hits_the_road_where_it_should():
    xyz, cams = scene()
    o, d = cams[0].ray(to_frame_px(cams[0], A))
    hit = ss.intersect(xyz, o, d, F_MODEL)
    assert hit["support"] >= 8
    assert np.allclose(hit["point"] * S_TRUE, A, atol=0.03)


def test_recovers_a_known_scale_within_1_percent():
    xyz, cams = scene()
    r = ss.measure_ref(xyz, cams, ref(cams))
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.01)
    assert r["d3"] == pytest.approx(KNOWN / S_TRUE, rel=0.01)
    assert len(r["points_3d"]) == 2 and min(r["support"]) >= 8
    assert 0 < r["rel_sigma"] < 0.05
    lo, hi = r["range"]
    assert lo < r["scale"] < hi


def test_recovers_scale_along_the_road_and_from_two_different_frames():
    xyz, cams = scene()
    # a 6 m dashed line along the road, near the camera's lane
    a, b = np.array([1.75, 6.0, 0.0]), np.array([1.75, 12.0, 0.0])
    r = ss.measure_ref(xyz, cams, ref(cams, a=a, b=b, known=6.0, frame=2))
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.01)
    # same physical points seen in two different frames
    two = {"points": [{"frame": 0, "xy": to_frame_px(cams[0], a)}, {"frame": 5, "xy": to_frame_px(cams[5], b)}], "known_m": 6.0}
    r2 = ss.measure_ref(xyz, cams, two)
    assert r2["scale"] == pytest.approx(S_TRUE, rel=0.01)


def test_floaters_in_front_of_the_road_do_not_win():
    xyz, cams = scene(floaters=3000)
    r = ss.measure_ref(xyz, cams, ref(cams))
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.015)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_thick_noisy_layer_is_met_in_its_middle_not_at_its_near_edge(seed):
    """3 % depth noise (a road 'layer' +-27 cm thick at 9 m): the first dense points along the ray are the
    near edge of the layer; taking them would make every length too short and the scale too big."""
    xyz, cams = scene(noise=0.03, seed=seed, floaters=1500)
    r = ss.measure_ref(xyz, cams, ref(cams))
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.02)
    lo, hi = r["range"]
    assert lo * 0.98 < S_TRUE < hi * 1.02


def test_order_of_taps_does_not_matter():
    xyz, cams = scene()
    r1 = ss.measure_ref(xyz, cams, ref(cams))
    rr = ref(cams)
    rr["points"] = rr["points"][::-1]
    r2 = ss.measure_ref(xyz, cams, rr)
    assert r1["scale"] == pytest.approx(r2["scale"], rel=1e-9)
    assert r1["rel_sigma"] == pytest.approx(r2["rel_sigma"], rel=0.25)


def test_rays_that_miss_the_cloud_raise_a_clear_error():
    xyz, cams = scene()
    rr = ref(cams)
    rr["points"][1]["xy"] = [480.0, 5.0]           # top of the frame: the sky, no 3D points there
    with pytest.raises(ss.ScaleError, match="point 2.*does not hit the 3D"):
        ss.measure_ref(xyz, cams, rr)
    rr = ref(cams)
    rr["points"][1] = dict(rr["points"][0])        # both ends on the same spot
    with pytest.raises(ss.ScaleError, match="same spot"):
        ss.measure_ref(xyz, cams, rr)
    rr = ref(cams, frame=0)
    rr["points"][0]["frame"] = 99
    with pytest.raises(ss.ScaleError, match="frame 99"):
        ss.measure_ref(xyz, cams, rr)


def test_reference_uncertainty_adds_to_the_tap_uncertainty():
    xyz, cams = scene()
    r0 = ss.measure_ref(xyz, cams, ref(cams, rel=0.0))
    r1 = ss.measure_ref(xyz, cams, ref(cams, rel=0.05))
    assert r1["scale"] == pytest.approx(r0["scale"])
    assert r1["rel_sigma"] == pytest.approx(math.hypot(r0["rel_sigma"], 0.05), rel=1e-6)


def test_combining_three_references_flags_the_outlier():
    out = ss.combine([{"scale": 2.70, "rel_sigma": 0.02}, {"scale": 2.66, "rel_sigma": 0.03},
                      {"scale": 3.60, "rel_sigma": 0.02}])
    assert out["outliers"] == [False, False, True]
    assert out["scale"] == pytest.approx(2.69, abs=0.02)           # the outlier is left out of the result
    assert 0 < out["rel_sigma"] < 0.03 and out["used"] == 2
    lo, hi = out["range"]
    assert lo < out["scale"] < hi


def test_combining_agreeing_references_shrinks_the_error_and_weights_by_it():
    out = ss.combine([{"scale": 2.0, "rel_sigma": 0.04}, {"scale": 2.1, "rel_sigma": 0.04}])
    assert out["outliers"] == [False, False]
    assert out["rel_sigma"] < 0.04
    w = ss.combine([{"scale": 2.0, "rel_sigma": 0.01}, {"scale": 2.1, "rel_sigma": 0.10}])
    assert abs(w["scale"] - 2.0) < abs(w["scale"] - 2.1)
    one = ss.combine([{"scale": 2.0, "rel_sigma": 0.03}])
    assert one["scale"] == pytest.approx(2.0) and one["rel_sigma"] == pytest.approx(0.03)
    # two that disagree: no outlier can be picked, but the error grows to cover both
    two = ss.combine([{"scale": 2.0, "rel_sigma": 0.01}, {"scale": 2.4, "rel_sigma": 0.01}])
    assert two["outliers"] == [False, False] and two["rel_sigma"] > 0.05 and two["warnings"]
    with pytest.raises(ss.ScaleError):
        ss.combine([])


def test_combined_scale_is_the_inverse_variance_weighted_mean_in_log_space():
    items = [{"scale": 1.30, "rel_sigma": 0.02}, {"scale": 1.36, "rel_sigma": 0.04}, {"scale": 1.33, "rel_sigma": 0.03}]
    out = ss.combine(items)
    x = np.log([i["scale"] for i in items])
    w = 1 / np.array([i["rel_sigma"] for i in items]) ** 2
    mean = float(np.sum(w * x) / np.sum(w))
    assert out["scale"] == pytest.approx(math.exp(mean), rel=1e-9)
    # these three agree within their errors (chi2/dof < 1): the ± is the plain 1/sqrt(sum of weights)
    chi2 = float(np.sum(w * (x - mean) ** 2) / 2)
    assert out["chi2_dof"] == pytest.approx(chi2) and chi2 < 1
    assert out["rel_sigma"] == pytest.approx(1 / math.sqrt(w.sum()), rel=1e-9)
    assert out["pct"] == round(100 * out["rel_sigma"], 1)
    # the range is the 10th-90th percentile of a log-normal with that sigma
    lo, hi = out["range"]
    assert lo == pytest.approx(out["scale"] * math.exp(-1.2815515655 * out["rel_sigma"]), rel=1e-6)
    assert hi == pytest.approx(out["scale"] * math.exp(1.2815515655 * out["rel_sigma"]), rel=1e-6)


def test_scatter_beyond_the_errors_widens_the_range_by_the_birge_ratio():
    items = [{"scale": 1.0, "rel_sigma": 0.01}, {"scale": 1.05, "rel_sigma": 0.01}, {"scale": 1.10, "rel_sigma": 0.01}]
    out = ss.combine(items)
    assert out["outliers"] == [False, False, False]          # 1.10 is 4.8 % off: not > 3 sigma of the combined
    assert out["chi2_dof"] > 1
    assert out["rel_sigma"] == pytest.approx(0.01 / math.sqrt(3) * math.sqrt(out["chi2_dof"]), rel=1e-9)


def test_an_outlier_needs_a_majority_that_agrees():
    # two references cannot outvote each other: nothing is flagged (see the two-reference case above);
    # with four, one bad tap is flagged and the other three decide
    four = ss.combine([{"scale": 1.33, "rel_sigma": 0.02}, {"scale": 1.35, "rel_sigma": 0.02},
                       {"scale": 1.34, "rel_sigma": 0.03}, {"scale": 0.95, "rel_sigma": 0.02}])
    assert four["outliers"] == [False, False, False, True] and four["used"] == 3
    assert four["scale"] == pytest.approx(1.34, abs=0.01) and four["z"][3] > 3
    assert any("left out" in w for w in four["warnings"])
    # three that all disagree: no majority, nothing silently dropped, a warning instead
    split = ss.combine([{"scale": 1.0, "rel_sigma": 0.01}, {"scale": 1.5, "rel_sigma": 0.01}, {"scale": 2.2, "rel_sigma": 0.01}])
    assert split["outliers"] == [False, False, False] and split["used"] == 3
    assert "no majority" in split["warnings"][0] and split["pct"] > 15   # the ± shows how bad it is


def test_a_height_uses_only_the_vertical_part_of_the_two_points():
    """Kerb, cone, tyre: the catalog marks them vertical. A wall 9 m ahead, 1.2 m tall; the second tap is
    0.4 m to the side of the first, as a sloppy tap on a kerb face would be."""
    xyz, cams = scene()
    gx, gz = np.meshgrid(np.arange(-2, 2, 0.02), np.arange(0, 1.2, 0.02))
    wall = np.stack([gx.ravel(), np.full(gx.size, 9.0), gz.ravel()], 1) / S_TRUE
    xyz = np.concatenate([xyz, wall.astype(np.float32)])
    foot, top = np.array([0.6, 9.0, 0.1]), np.array([1.0, 9.0, 0.7])
    r = ss.measure_ref(xyz, cams, {**ref(cams, a=foot, b=top, known=0.6), "vertical": True})
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.03)
    straight = ss.measure_ref(xyz, cams, ref(cams, a=foot, b=top, known=0.6))
    assert straight["d3"] * S_TRUE == pytest.approx(math.hypot(0.4, 0.6), rel=0.03)    # the slanted length
    # far apart sideways for a height: said so
    side = ss.measure_ref(xyz, cams, {**ref(cams, a=np.array([-1.0, 9.0, 0.3]), b=np.array([1.0, 9.0, 0.6]), known=0.3),
                                      "vertical": True})
    assert any("one vertical line" in w for w in side["warnings"])


def test_taps_on_the_same_kind_of_object_share_its_size_error():
    """Three kerbs of one assumed height (±33 %): more taps average the tap noise, not the kerb height."""
    ref_e, meas = 0.33, 0.05
    sig = math.hypot(ref_e, meas)
    same = [{"scale": k, "rel_sigma": sig, "rel_ref": ref_e, "key": "kerb_height"} for k in (0.50, 0.52, 0.46)]
    out = ss.combine(same)
    assert out["rel_sigma"] >= math.sqrt(ref_e ** 2 + meas ** 2 / 3) * 0.999       # not sig / sqrt(3)
    assert out["rel_sigma"] > 0.3 and any("same kind of object" in w for w in out["warnings"])
    # their scatter (chi2/dof > 1 here) widens only the tap part, not the shared ±33 % again
    assert out["chi2_dof"] > 1 and out["rel_sigma"] < math.hypot(ref_e, meas) * 1.02
    indep = ss.combine([{k: v for k, v in i.items() if k != "key"} for i in same])  # pretending they were independent
    assert indep["rel_sigma"] == pytest.approx(sig / math.sqrt(3), rel=1e-6)
    # a different object brings independent information and does shrink the ±
    mixed = ss.combine(same + [{"scale": 0.49, "rel_sigma": 0.06, "rel_ref": 0.05, "key": "lane_width_urban"}])
    assert mixed["rel_sigma"] < 0.07 and mixed["scale"] == pytest.approx(0.49, rel=0.03)
    # one bad tap among the kerbs is still flagged: their shared size cancels in the comparison
    bad = same + [{"scale": 0.80, "rel_sigma": sig, "rel_ref": ref_e, "key": "kerb_height"}]
    assert ss.combine(bad)["outliers"] == [False, False, False, True]


def test_describe_names_the_objects_used():
    refs = [{"label": "Lane width"}, {"label": "Kerb height"}, {"label": "Lane width"}, {"label": "Bad tap"}]
    assert ss.describe_parts(refs, [0, 1, 2]) == "Lane width ×2, Kerb height ×1"
    assert ss.describe(refs, [0, 1, 2]) == "3 scene references (Lane width ×2, Kerb height ×1)"
    assert ss.describe(refs[:1]) == "1 scene reference (Lane width ×1)"


def test_estimate_end_to_end_with_several_references():
    xyz, cams = scene()
    refs = [ref(cams, rel=0.02), ref(cams, a=np.array([1.75, 6.0, 0]), b=np.array([1.75, 12.0, 0]), known=6.0, frame=1, rel=0.02),
            ref(cams, known=KNOWN * 1.4, rel=0.02)]                   # wrong size typed: an outlier
    out = ss.estimate(xyz, cams, refs)
    assert out["combined"]["outliers"] == [False, False, True]
    assert out["combined"]["scale"] == pytest.approx(S_TRUE, rel=0.01)


# --- the clip's cameras ----------------------------------------------------------------------------------
def test_lingbot_convert_saves_the_intrinsics_and_the_clip_cameras_come_back(tmp_path):
    from civil.decoders.lingbot_clip import _adapter

    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(1)
    for i in range(4):
        c = c2w_at(0.8 * i)
        c[:3, 3] /= S_TRUE
        w2c = np.linalg.inv(c)[:3, :4]
        vv, uu = np.mgrid[0:MH, 0:MW]
        d_cam = np.stack([(uu + 0.5 - K[0, 2]) / K[0, 0], (vv + 0.5 - K[1, 2]) / K[1, 1], np.ones_like(uu, float)], -1)
        dz = (d_cam @ c[:3, :3].T)[..., 2]
        depth = np.where(dz < -1e-6, -c[2, 3] / np.where(dz < -1e-6, dz, -1), 0.0)
        depth = np.where(depth * S_TRUE < 40, depth, 0.0) * (1 + rng.normal(0, 0.002, depth.shape))
        np.savez(raw / f"frame_{i:06d}.npz", extrinsic=w2c[None], intrinsic=K[None], depth=depth[None, ..., None],
                 depth_conf=np.full((1, MH, MW), 2.0), images=np.full((1, 3, MH, MW), 0.5, np.float32))
    out = tmp_path / "decoded"
    _adapter().convert(raw, out, pose="w2c")
    pj = json.loads((out / "poses.json").read_text())
    assert len(pj["intrinsics"]) == 4 and np.allclose(pj["intrinsics"][0], K)

    from civil.decoders.ply_import import load_outputs

    rec = load_outputs(out, "points.ply", "poses.json")
    assert len(rec.meta["intrinsics"]) == 4
    rec.meta["frame_geometry"] = GEO
    cams = ss.cameras_from_rec(rec)
    r = ss.measure_ref(rec.points, cams, ref(cams, frame=1))
    assert r["scale"] == pytest.approx(S_TRUE, rel=0.01)


def test_cameras_survive_alignment_and_rescaling(tmp_path):
    """align() rotates and scales the recon; the rays follow the poses, so the scale found afterwards is the
    remaining factor, and rescale() by that factor makes the reference read its known size."""
    from civil.align import align
    from civil.pointcloud import Reconstruction

    xyz, cams = scene()
    rec = Reconstruction(points=xyz, poses=np.stack([c.c2w for c in cams]),
                         meta={"intrinsics": [K.tolist()] * len(cams), "frame_geometry": GEO, "camera_convention": "opencv",
                               "camera_height_m": 1.4, "up_axis": "auto"})
    align(rec, 13.8, 100.5, {"camera_height_m": 1.4})
    cams2 = ss.cameras_from_rec(rec)
    r = ss.measure_ref(rec.points, cams2, ref(cams))         # same pixels as before alignment
    assert r["scale"] == pytest.approx(CAM_H / 1.4, rel=0.02)  # the camera-height guess was 1.4 m, truth 1.35 m
    ss.rescale(rec, r["scale"])
    r2 = ss.measure_ref(rec.points, ss.cameras_from_rec(rec), ref(cams))
    assert r2["scale"] == pytest.approx(1.0, rel=0.005)
    assert r2["d3"] == pytest.approx(KNOWN, rel=0.01)


# --- the catalog ---------------------------------------------------------------------------------------------
def test_shipped_catalog_is_sourced_or_says_it_is_provisional():
    cat = ss.load_catalog()
    assert cat["objects"][-1]["id"] == "custom"
    std = [o for o in cat["objects"] if not o["custom"]]
    assert std, "the provisional list is shipped"
    for o in std:
        # a size without a source is provisional, with a note saying so: nothing unsourced passes as a standard
        assert o["source_urls"] or (o["provisional"] and "provisional" in (o["source_note"] or "")), o["id"]
        assert o["name_th"] and o["name_en"] and o["plane"] in ("flat", "upright") and o["value_m"] > 0, o["id"]
        assert 0 < o["rel_error"] < 0.5 and not o["rel_unknown"], o["id"]
    assert ss.resolve({"ref_id": std[0]["id"]}, cat)["provisional"] == std[0]["provisional"]
    r = ss.resolve({"ref_id": "custom", "known_m": 3.0, "tol_m": 0.03}, cat)
    assert r["known_m"] == 3.0 and r["rel_error"] == pytest.approx(0.01) and not r["rel_unknown"]
    assert ss.resolve({"ref_id": "custom", "known_m": 3.0}, cat)["rel_unknown"]
    with pytest.raises(ss.ScaleError):
        ss.resolve({"ref_id": "custom"}, cat)
    with pytest.raises(ss.ScaleError):
        ss.resolve({"ref_id": "not_there", "known_m": 1}, cat)


def test_research_catalog_entries_are_read_as_given(tmp_path, monkeypatch):
    """The research file's fields; the numbers here are test data, not standard sizes."""
    f = tmp_path / "refs.json"
    f.write_text(json.dumps({"objects": [
        {"id": "t_lane", "name_en": "Test lane width", "dimension_name": "lane width", "value_m": 3.0, "rel_error": 5,
         "plane": "road", "source_urls": ["https://example.org/a"], "source_dates": "2020"},
        {"id": "t_plate", "name_en": "Test plate", "dimension_name": "plate width", "value_m": 0.4, "tolerance_m": 0.004,
         "plane": "vertical", "source_urls": ["https://example.org/b"]},
        {"id": "t_cover", "name_en": "Test cover", "dimension_name": "diameter", "value_m": 0.6, "spread": [0.55, 0.65]},
        {"id": "t_bad", "name_en": "No size", "value_m": None},
        {"id": "custom", "name_en": "theirs"},
    ]}))
    monkeypatch.setenv("CIVIL_SCENE_REFS", str(f))
    cat = ss.load_catalog()
    by = {o["id"]: o for o in cat["objects"]}
    assert set(by) == {"t_lane", "t_plate", "t_cover", "custom"}
    assert by["t_lane"]["rel_error"] == pytest.approx(0.05) and by["t_lane"]["group"] == "road_markings"
    assert by["t_plate"]["rel_error"] == pytest.approx(0.01) and by["t_plate"]["group"] == "vehicles"
    assert by["t_cover"]["rel_error"] == pytest.approx(0.05 / 0.6, rel=1e-3) and by["t_cover"]["group"] == "street_furniture"
    assert by["custom"]["name_en"] == "Custom known distance"
    r = ss.resolve({"ref_id": "t_plate"}, cat)
    assert r["known_m"] == 0.4 and r["label"] == "Test plate"
    # entries with sources are standards; one without is provisional even when the file does not say so
    assert not by["t_lane"]["provisional"] and not by["t_plate"]["provisional"] and by["t_cover"]["provisional"]

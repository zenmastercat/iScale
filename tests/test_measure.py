"""Reference-object measurement: a known rectangle (or a 2-point ruler) on the road gives the scale.

The synthetic photos come from a real pinhole camera (focal length, height, tilt), so the image-to-road
homography is the one a phone would produce, not a hand-made matrix.
"""

import math

import numpy as np
import pytest

from civil import measure

W, H = 1920, 1080


def camera(height=1.5, pitch_deg=50.0, f=1500.0, yaw_deg=0.0, size=(W, H)):
    """Project road points (x east, y ahead, z=0) into a pinhole camera at (0, 0, height)."""
    t, y = math.radians(pitch_deg), math.radians(yaw_deg)
    fwd = np.array([math.sin(y) * math.cos(t), math.cos(y) * math.cos(t), -math.sin(t)])
    right = np.array([math.cos(y), -math.sin(y), 0.0])
    down = np.cross(fwd, right)
    R = np.stack([right, down, fwd])
    K = np.array([[f, 0, size[0] / 2], [0, f, size[1] / 2], [0, 0, 1]])
    C = np.array([0, 0, height])

    def project(pts):
        P = np.c_[np.asarray(pts, float), np.zeros(len(pts))]
        c = (K @ (R @ (P - C).T)).T
        return c[:, :2] / c[:, 2:3]

    return project


def rect(cx, cy, w, l, ang_deg):
    a = math.radians(ang_deg)
    u, v = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    c = np.array([cx, cy])
    return np.array([c - u * w / 2 - v * l / 2, c + u * w / 2 - v * l / 2, c + u * w / 2 + v * l / 2, c - u * w / 2 + v * l / 2])


# an irregular pothole outline on the road, metres
HOLE = np.array([[0.55, 2.35], [0.95, 2.25], [1.20, 2.45], [1.15, 2.80], [0.85, 2.95], [0.50, 2.75]])


def truth(poly):
    import cv2

    x, y = poly[:, 0], poly[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
    per = float(np.sum(np.linalg.norm(poly - np.roll(poly, 1, 0), axis=1)))
    (_, _), (a, b), _ = cv2.minAreaRect((poly * 1000).astype(np.float32))
    return area, per, min(a, b) / 1000, max(a, b) / 1000


A4 = measure.reference("a4")


def test_presets_are_exact_standard_sizes():
    refs = {r["id"]: r for r in measure.presets()["refs"]}
    assert (refs["a4"]["width_m"], refs["a4"]["length_m"]) == (0.210, 0.297)
    assert (refs["a3"]["width_m"], refs["a3"]["length_m"]) == (0.297, 0.420)
    assert sorted((refs["id1"]["width_m"], refs["id1"]["length_m"])) == [0.05398, 0.0856]
    assert refs["custom"]["kind"] == "rect" and refs["ruler"]["kind"] == "line"
    assert "straight down" in refs["ruler"]["note"]
    c = measure.reference("custom", width_cm=50, length_cm=80)
    assert (c["width_m"], c["length_m"]) == (0.5, 0.8)
    with pytest.raises(measure.MeasureError):
        measure.reference("custom")
    with pytest.raises(measure.MeasureError):
        measure.reference("banana")


@pytest.mark.parametrize("pitch,ang", [(50, 20), (35, 0), (70, -35), (45, 90)])
def test_area_and_dimensions_within_2_percent(pitch, ang):
    cam = camera(pitch_deg=pitch)
    ref = rect(0.25, 2.55, 0.210, 0.297, ang)
    r = measure.measure((W, H), A4, cam(ref), outline=cam(HOLE))
    area, per, w, l = truth(HOLE)
    assert r["area_m2"] == pytest.approx(area, rel=0.02)
    assert r["perimeter_m"] == pytest.approx(per, rel=0.02)
    assert r["width_m"] == pytest.approx(w, rel=0.02)
    assert r["length_m"] == pytest.approx(l, rel=0.02)
    longest = max(np.linalg.norm(a - b) for a in HOLE for b in HOLE)
    assert r["longest_m"] == pytest.approx(longest, rel=0.02)
    centre = HOLE.mean(0)
    assert r["distance_m"] == pytest.approx(np.linalg.norm(centre - ref.mean(0)), abs=0.05)
    assert not [x for x in r["warnings"] if "uncertain" not in x]  # no distance or size warning here


def test_long_side_pointing_away_is_still_read_the_right_way_round():
    # low camera: the 29.7 cm side, pointing away, looks shorter in the photo than the 21 cm side
    cam = camera(height=1.2, pitch_deg=22)
    ref = rect(0.2, 2.6, 0.210, 0.297, 0)
    img = cam(ref)
    near, far = np.linalg.norm(img[1] - img[0]), np.linalg.norm(img[2] - img[1])
    assert far < near  # foreshortened: the long side is shorter on screen
    r = measure.measure((W, H), A4, img, outline=cam(HOLE))
    assert r["area_m2"] == pytest.approx(truth(HOLE)[0], rel=0.02)
    other = "length" if r["ref"]["first_edge"] == "width" else "width"
    forced = measure.measure((W, H), A4, img, outline=cam(HOLE), first_edge=other)
    # swapping is an area-preserving stretch, so the area is the same but the shape is visibly wrong
    assert forced["area_m2"] == pytest.approx(r["area_m2"], rel=1e-3)
    assert abs(forced["length_m"] / truth(HOLE)[3] - 1) > 0.1 and abs(forced["width_m"] / truth(HOLE)[2] - 1) > 0.1


def test_point_order_does_not_matter():
    cam = camera()
    img = cam(rect(0.25, 2.55, 0.210, 0.297, 15))
    base = measure.measure((W, H), A4, img, outline=cam(HOLE))
    for perm in ([2, 0, 3, 1], [3, 2, 1, 0], [1, 3, 0, 2]):
        r = measure.measure((W, H), A4, img[perm], outline=cam(HOLE))
        assert r["area_m2"] == pytest.approx(base["area_m2"], rel=1e-6)
        assert r["width_m"] == pytest.approx(base["width_m"], rel=1e-6)
    # the outline may be traced either way round
    r = measure.measure((W, H), A4, img, outline=cam(HOLE)[::-1])
    assert r["area_m2"] == pytest.approx(base["area_m2"], rel=1e-6)


def test_detector_box_is_measured_as_its_four_corners():
    cam = camera()
    img = cam(rect(0.25, 2.55, 0.210, 0.297, 0))
    hole = cam(HOLE)
    box = [hole[:, 0].min(), hole[:, 1].min(), hole[:, 0].max(), hole[:, 1].max()]
    r = measure.measure((W, H), A4, img, box=box)
    corners = np.array([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]])
    r2 = measure.measure((W, H), A4, img, outline=corners)
    assert r["area_m2"] == pytest.approx(r2["area_m2"]) and r["outline_from"] == "box"
    assert r["area_m2"] > truth(HOLE)[0]  # a box is larger than the hole inside it


def test_two_point_ruler_on_a_straight_down_photo():
    cam = camera(height=1.4, pitch_deg=90, f=1400)  # looking straight down: a similarity, no perspective
    tape = np.array([[0.2, 0.1], [0.2, 1.1]])  # 1 m of tape
    hole = HOLE - [0.8, 2.6]  # under the camera
    ref = measure.reference("ruler", length_cm=100)
    r = measure.measure((W, H), ref, cam(tape), outline=cam(hole))
    area, per, w, l = truth(hole)
    assert r["area_m2"] == pytest.approx(area, rel=0.01)
    assert r["width_m"] == pytest.approx(w, rel=0.01) and r["length_m"] == pytest.approx(l, rel=0.01)
    assert any("straight down" in x for x in r["warnings"])  # always says when it is valid
    with pytest.raises(measure.MeasureError):
        measure.measure((W, H), ref, cam(tape)[:1], outline=cam(hole))


def test_range_contains_the_truth_for_slightly_off_taps():
    cam = camera(pitch_deg=45)
    ref_img = cam(rect(0.25, 2.55, 0.210, 0.297, 10))
    hole_img = cam(HOLE)
    area, _, w, l = truth(HOLE)
    rng = np.random.default_rng(7)
    inside = 0
    for _ in range(10):
        r = measure.measure((W, H), A4, ref_img + rng.uniform(-1.5, 1.5, ref_img.shape),
                            outline=hole_img + rng.uniform(-1.5, 1.5, hole_img.shape), tol_px=3)
        lo, hi = r["ranges"]["area_m2"]
        assert lo < r["area_m2"] < hi
        inside += lo <= area <= hi and r["ranges"]["width_m"][0] <= w <= r["ranges"]["width_m"][1] \
            and r["ranges"]["length_m"][0] <= l <= r["ranges"]["length_m"][1]
    assert inside >= 9
    # the range is reproducible (fixed seed) and grows with the tap tolerance
    a = measure.measure((W, H), A4, ref_img, outline=hole_img)
    b = measure.measure((W, H), A4, ref_img, outline=hole_img)
    c = measure.measure((W, H), A4, ref_img, outline=hole_img, tol_px=8)
    assert a["ranges"] == b["ranges"]
    assert np.ptp(c["ranges"]["area_m2"]) > np.ptp(a["ranges"]["area_m2"])
    assert 0 < a["pct"]["area_m2"] < 60
    # a bigger reference in the picture, seen more from above, pins the size down much better
    top = camera(pitch_deg=75)
    a3 = measure.measure((W, H), measure.reference("a3"), top(rect(0.25, 2.55, 0.297, 0.420, 10)), outline=top(HOLE))
    assert a3["pct"]["area_m2"] < a["pct"]["area_m2"] / 2


def test_warnings_far_from_reference_and_tiny_reference():
    cam = camera(pitch_deg=40)
    far_hole = HOLE + [0, 2.5]
    r = measure.measure((W, H), A4, cam(rect(0.25, 2.55, 0.210, 0.297, 0)), outline=cam(far_hole))
    assert any("from the reference" in x for x in r["warnings"])
    small = camera(pitch_deg=40, f=300)  # wide lens: the A4 sheet is only a few dozen pixels
    r = measure.measure((W, H), A4, small(rect(0.25, 2.55, 0.210, 0.297, 0)), outline=small(HOLE))
    assert r["ref_px"] < 40 and any("pixels" in x for x in r["warnings"])


def test_bad_inputs_raise_clear_errors():
    cam = camera()
    good = cam(rect(0.25, 2.55, 0.210, 0.297, 0))
    with pytest.raises(measure.MeasureError, match="line"):
        measure.measure((W, H), A4, [[100, 100], [200, 200], [300, 300], [400, 100]], outline=cam(HOLE))
    with pytest.raises(measure.MeasureError, match="4 corners"):
        measure.measure((W, H), A4, good[:3], outline=cam(HOLE))
    with pytest.raises(measure.MeasureError, match="line"):  # a flat outline has no area
        measure.measure((W, H), A4, good, outline=[[500, 700], [600, 700], [700, 700]])
    with pytest.raises(measure.MeasureError, match="3 points"):
        measure.measure((W, H), A4, good, outline=[[500, 700], [600, 700]])
    # a camera looking ahead (horizon in the picture): points above the horizon are not on the road
    level = camera(pitch_deg=10)
    with pytest.raises(measure.MeasureError, match="road"):
        measure.measure((W, H), A4, level(rect(0.25, 5.0, 0.210, 0.297, 0)), outline=[[800, 100], [1000, 100], [900, 50]])
    with pytest.raises(measure.MeasureError, match="road"):  # just below the horizon: hundreds of metres away
        measure.measure((W, H), A4, level(rect(0.25, 5.0, 0.210, 0.297, 0)), outline=[[800, 278], [1000, 278], [900, 279]])
    with pytest.raises(measure.MeasureError, match="crosses"):
        hole = cam(HOLE)
        measure.measure((W, H), A4, good, outline=hole[[0, 2, 1, 3, 4, 5]])
    with pytest.raises(measure.MeasureError, match="outline"):
        measure.measure((W, H), A4, good)


def test_depth_typed_or_rescaled_from_3d_never_invented():
    cam = camera()
    r = measure.measure((W, H), A4, cam(rect(0.25, 2.55, 0.210, 0.297, 0)), outline=cam(HOLE))
    m = measure.finding_metrics(r)
    assert "depth_max_m" not in m and "volume_m3" not in m and m["area_m2"] == r["area_m2"]
    m = measure.finding_metrics(r, depth_cm=6)
    assert m["depth_max_m"] == 0.06 and m["volume_m3"] == pytest.approx(r["area_m2"] * 0.06, rel=1e-3)
    # 3D had the right shape at 0.8x scale: area 0.64x, depth 0.8x of the truth
    three = {"area_m2": r["area_m2"] * 0.64, "depth_max_m": 0.04, "volume_m3": 0.004}
    d = measure.rescale_depth(r, three)
    assert d["k"] == pytest.approx(1.25, rel=1e-3) and d["depth_m"] == pytest.approx(0.05, rel=1e-3)
    assert d["volume_m3"] == pytest.approx(0.004 * 1.25 ** 3, rel=1e-3)
    m = measure.finding_metrics(r, rescale=d)
    assert m["depth_max_m"] == pytest.approx(0.05, abs=1e-3)
    with pytest.raises(measure.MeasureError, match="0.2"):
        measure.rescale_depth(r, {"area_m2": r["area_m2"] * 100, "depth_max_m": 0.04})
    with pytest.raises(measure.MeasureError, match="3D"):
        measure.rescale_depth(r, {"area_m2": 0.3})
    # median depth is used when the deepest point could not be measured
    d = measure.rescale_depth(r, {"area_m2": r["area_m2"], "depth_max_m": None, "depth_median_m": 0.03})
    assert d["depth_m"] == pytest.approx(0.03, rel=1e-3) and d["depth_key"] == "depth_median_m"

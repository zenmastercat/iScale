"""Measure a pothole in a photo from a reference object of known size lying on the road.

Pure numpy/OpenCV; the HTTP routes are in civil/measure_api.py.

Reference rectangle (A4, A3, ID-1 card, or a custom W x L): its 4 corners in the image and its
real size give the homography from the image to the road plane (the same 4-point method as
civil/video/perspective.py, with cv2.getPerspectiveTransform). Every point of the pothole outline,
or the 4 corners of the detector box, is mapped onto the road in metres, and then

  area        shoelace formula
  perimeter   sum of the edges
  W x L       cv2.minAreaRect of the outline in metres (W the short side)
  longest     largest distance between two outline points
  distance    reference centre to outline centre

Which image edge is the reference's long side: perspective can make the long side look shorter,
so the side lengths in pixels do not decide it. Both ways round give a homography; only one of
them is a real camera (square pixels, principal point near the image centre). For each, the
focal length is scanned over 0.3-3 x the image size and the best match of the two rotation
columns (orthogonal, equal length) is kept; the better way round wins. People can swap it.

2-point ruler: two ends of a known length give a scale (similarity, no perspective). That is only
right when the photo looks straight down at the hole, and the result always says so.

Uncertainty: every tapped point is moved by up to +-tol_px (uniform, 200 draws, fixed seed) and
the 10th-90th percentiles of area, width, length and perimeter are reported. Warnings when the
hole is more than 4 x the reference's size away from it, or the reference's shortest side is
under 40 pixels: perspective error grows in both cases.
"""

from __future__ import annotations

import json
import math

import cv2
import numpy as np

from .config import CONFIG_DIR

TOL_PX = 3.0
DRAWS = 200
SEED = 20261119
FAR_FACTOR = 4.0          # warn when the hole is further than this many reference sizes away
MIN_REF_PX = 40.0          # warn when the reference's shortest side is shorter than this on screen
MAX_EXTENT_M = 50.0        # an outline point further than this from the reference is not on the road
K_RANGE = (0.2, 5.0)       # accepted scale factor when rescaling a 3D depth
WIDE_PCT = 20.0            # warn when the area's p10-p90 half-range is wider than this, in %
MIN_CORNER_SIN = math.sin(math.radians(4))


class MeasureError(ValueError):
    """Bad measuring input; the message is shown to the person measuring."""


# --- reference objects -------------------------------------------------------------------------------
def presets() -> dict:
    return json.loads((CONFIG_DIR / "measure_refs.json").read_text())


def reference(ref_type: str, width_cm: float | None = None, length_cm: float | None = None) -> dict:
    """The reference object: preset sizes are fixed; custom rectangles and the ruler take typed sizes in cm."""
    refs = {r["id"]: r for r in presets()["refs"]}
    r = refs.get(ref_type)
    if r is None:
        raise MeasureError(f"Unknown reference object {ref_type!r}.")
    out = {"type": r["id"], "label": r["label"], "kind": r["kind"]}
    if r["kind"] == "line":
        if not length_cm or not 1 <= float(length_cm) <= 10000:
            raise MeasureError("Type the length between the two marks of the ruler or tape, in cm (1 to 10,000).")
        return {**out, "width_m": None, "length_m": round(float(length_cm) / 100, 5), "note": r.get("note", "")}
    if r.get("custom"):
        if not width_cm or not length_cm or not (0.5 <= float(width_cm) <= 5000 and 0.5 <= float(length_cm) <= 5000):
            raise MeasureError("Type the width and length of your rectangle in cm (0.5 to 5,000).")
        a, b = sorted((float(width_cm) / 100, float(length_cm) / 100))
        return {**out, "width_m": round(a, 5), "length_m": round(b, 5)}
    return {**out, "width_m": float(r["width_m"]), "length_m": float(r["length_m"])}


# --- geometry ------------------------------------------------------------------------------------------
def _pts(p, what: str) -> np.ndarray:
    try:
        a = np.asarray(p, dtype=np.float64).reshape(-1, 2)
    except (TypeError, ValueError):
        raise MeasureError(f"The {what} points must be pairs of numbers.") from None
    if not np.isfinite(a).all():
        raise MeasureError(f"The {what} points must be finite numbers.")
    return a


def order_quad(pts) -> np.ndarray:
    """4 corners in any order -> one convex order around the shape, starting at the top-left corner."""
    p = _pts(pts, "reference")
    if p.shape != (4, 2):
        raise MeasureError("Tap the 4 corners of the reference rectangle.")
    c = p.mean(0)
    q = p[np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))]
    q = np.roll(q, -int(np.argmin(q.sum(1))), axis=0)
    e = np.roll(q, -1, axis=0) - q
    n = np.linalg.norm(e, axis=1)
    if n.min() < 2.0:
        raise MeasureError("Two corners of the reference are on top of each other. Tap the 4 corners again.")
    cross = e[:, 0] * np.roll(e, -1, axis=0)[:, 1] - e[:, 1] * np.roll(e, -1, axis=0)[:, 0]
    sin = cross / (n * np.roll(n, -1))
    if np.abs(sin).min() < MIN_CORNER_SIN:
        raise MeasureError("Three of the reference corners are on one line. Tap the 4 corners of the rectangle again.")
    if not ((sin > 0).all() or (sin < 0).all()):
        raise MeasureError("The 4 reference corners do not outline a rectangle (one is inside the others). Tap them again.")
    return q


def _plane_rect(a: float, b: float) -> np.ndarray:
    return np.array([[0, 0], [a, 0], [a, b], [0, b]], dtype=np.float64)


def _camera_misfit(h_plane2img: np.ndarray, size: tuple[float, float]) -> float:
    """How far this plane->image homography is from a real camera (0 = a perfect fit)."""
    cx, cy = size[0] / 2, size[1] / 2
    g = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], dtype=np.float64) @ h_plane2img
    g1, g2 = g[:, 0], g[:, 1]
    best = math.inf
    for f in max(size) * np.geomspace(0.3, 3.0, 90):
        v1 = np.array([g1[0] / f, g1[1] / f, g1[2]])
        v2 = np.array([g2[0] / f, g2[1] / f, g2[2]])
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-12 or n2 < 1e-12:
            continue
        best = min(best, (v1 @ v2 / (n1 * n2)) ** 2 + math.log(n1 / n2) ** 2)
    return best


def _homography(q: np.ndarray, a: float, b: float) -> np.ndarray:
    """Image -> road plane (metres) for corners q (ordered) and a rectangle a (first edge) x b."""
    return cv2.getPerspectiveTransform(q.astype(np.float32), _plane_rect(a, b).astype(np.float32)).astype(np.float64)


def _to_plane(h: np.ndarray, pts: np.ndarray, sign: float) -> tuple[np.ndarray, np.ndarray]:
    ph = np.c_[pts, np.ones(len(pts))] @ h.T
    w = ph[:, 2] * sign
    ok = w > 1e-12
    out = np.full((len(pts), 2), np.nan)
    out[ok] = ph[ok, :2] / ph[ok, 2:3]
    return out, ok


def _poly(P: np.ndarray) -> dict:
    x, y = P[:, 0], P[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a2 = float(cross.sum())
    area = abs(a2) / 2
    per = float(np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1).sum())
    (_, _), (rw, rl), _ = cv2.minAreaRect((P * 1000).astype(np.float32))
    d = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    if abs(a2) > 1e-12:
        cxy = np.array([((x + np.roll(x, -1)) * cross).sum(), ((y + np.roll(y, -1)) * cross).sum()]) / (3 * a2)
    else:
        cxy = P.mean(0)
    return {"area_m2": area, "perimeter_m": per, "width_m": min(rw, rl) / 1000, "length_m": max(rw, rl) / 1000,
            "longest_m": float(d.max()), "centre": cxy}


def _crosses_itself(P: np.ndarray) -> bool:
    n = len(P)

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or j == (i + 1) % n:
                continue  # neighbouring edges share a point
            c, d = P[j], P[(j + 1) % n]
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                return True
    return False


def _outline(outline, box) -> tuple[np.ndarray, str]:
    if outline is not None and len(outline):
        o = _pts(outline, "outline")
        if len(o) < 3:
            raise MeasureError("Trace the pothole outline with at least 3 points, or use the detector box.")
        if len(o) > 200:
            raise MeasureError("Use at most 200 outline points.")
        return o, "points"
    if box is not None:
        b = _pts(box, "box").ravel()
        if len(b) != 4 or b[2] - b[0] < 1 or b[3] - b[1] < 1:
            raise MeasureError("The detector box must be [x0, y0, x1, y1] with x1 > x0 and y1 > y0.")
        return np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]), "box"
    raise MeasureError("Trace the pothole outline (at least 3 points) or use the detector box.")


class _Frame:
    """Image -> road plane for one set of reference points (fixed corner order and side assignment)."""

    def __init__(self, ref: dict, rp: np.ndarray, first_edge: str):
        self.ref = ref
        if ref["kind"] == "line":
            d = float(np.linalg.norm(rp[1] - rp[0]))
            if d < 2.0:
                raise MeasureError("The two ends of the ruler are on top of each other. Tap both ends of the known length.")
            self.s, self.o = ref["length_m"] / d, rp[0]
            self.centre = (rp[1] - rp[0]) * self.s / 2   # the ruler's midpoint, in the same frame as plane()
            self.px = d
        else:
            a, b = (ref["width_m"], ref["length_m"]) if first_edge == "width" else (ref["length_m"], ref["width_m"])
            self.h = _homography(rp, a, b)
            ph = np.c_[rp, np.ones(4)] @ self.h.T
            self.sign = float(np.sign(ph[0, 2])) or 1.0
            self.centre = np.array([a / 2, b / 2])
            self.px = float(np.linalg.norm(np.roll(rp, -1, axis=0) - rp, axis=1).min())

    def plane(self, pts: np.ndarray) -> np.ndarray:
        if self.ref["kind"] == "line":
            return (pts - self.o) * self.s
        P, ok = _to_plane(self.h, pts, self.sign)
        if not ok.all():
            i = int(np.flatnonzero(~ok)[0]) + 1
            raise MeasureError(f"Outline point {i} is at or above the horizon of the road plane, so it is not on the road. "
                               "Trace the hole on the road surface, and check the reference corners: a small or "
                               "imprecisely tapped reference tilts the plane.")
        far = np.linalg.norm(P - self.centre, axis=1)
        if far.max() > MAX_EXTENT_M:
            i = int(np.argmax(far)) + 1
            raise MeasureError(f"Outline point {i} would be {far.max():.0f} m from the reference, so it is not on the "
                               "same road plane. Trace the hole next to the reference.")
        return P


def _shape(frame: _Frame, o: np.ndarray, check: bool = True) -> dict:
    P = frame.plane(o)
    m = _poly(P)
    if check:
        if m["area_m2"] < 1e-4 * max(m["perimeter_m"], 1e-6) ** 2 or m["area_m2"] < 1e-6:
            raise MeasureError("The outline points are on one line, so they enclose no area. Tap around the hole's edge.")
        if _crosses_itself(P):
            raise MeasureError("The outline crosses itself. Drag the points so the edges go round the hole once.")
    m["P"] = P
    return m


def measure(image_size, ref: dict, ref_points, outline=None, box=None, tol_px: float = TOL_PX,
            draws: int = DRAWS, seed: int = SEED, first_edge: str | None = None) -> dict:
    """Size of the pothole on the road plane. `first_edge` (rect only): which real side the edge from the
    first ordered corner (top-left) to the next one is, 'width' or 'length'; None = decide automatically."""
    try:
        size = (float(image_size[0]), float(image_size[1]))
    except (TypeError, ValueError, IndexError):
        raise MeasureError("The image size must be [width, height] in pixels.") from None
    if not (1 <= size[0] <= 30000 and 1 <= size[1] <= 30000):
        raise MeasureError("The image size must be [width, height] in pixels.")
    tol = float(tol_px)
    if not 0 <= tol <= 50:
        raise MeasureError("The tap tolerance must be 0 to 50 pixels.")
    o, src = _outline(outline, box)
    warnings: list[str] = []
    auto, ambiguous = first_edge is None, False
    if ref["kind"] == "line":
        rp = _pts(ref_points, "ruler")
        if rp.shape != (2, 2):
            raise MeasureError("Tap the two ends of the known length on the ruler or tape.")
        first_edge = "length"
    else:
        rp = order_quad(ref_points)
        if first_edge not in (None, "width", "length"):
            raise MeasureError("first_edge must be 'width' or 'length'.")
        if first_edge is None:
            if abs(ref["width_m"] - ref["length_m"]) < 1e-9:
                first_edge = "width"
            else:
                pw = cv2.getPerspectiveTransform(_plane_rect(ref["width_m"], ref["length_m"]).astype(np.float32), rp.astype(np.float32))
                pl = cv2.getPerspectiveTransform(_plane_rect(ref["length_m"], ref["width_m"]).astype(np.float32), rp.astype(np.float32))
                sw, sl = _camera_misfit(pw, size), _camera_misfit(pl, size)
                first_edge = "width" if sw <= sl else "length"
                ambiguous = min(sw, sl) > 0.25 * max(sw, sl) - 1e-12 and max(sw, sl) < 0.05
    frame = _Frame(ref, rp, first_edge)
    m = _shape(frame, o)

    # Monte Carlo: every tapped point moved by up to +-tol px, same corner order and side assignment
    rng = np.random.default_rng(seed)
    keys = ("area_m2", "width_m", "length_m", "perimeter_m")
    samples = {k: [] for k in keys}
    for _ in range(int(draws) if tol > 0 else 0):
        rj = rp + rng.uniform(-tol, tol, rp.shape)
        oj = o + rng.uniform(-tol, tol, o.shape)
        try:
            mj = _shape(_Frame(ref, rj, first_edge), oj, check=False)
        except (MeasureError, cv2.error, np.linalg.LinAlgError):
            continue
        for k in keys:
            samples[k].append(mj[k])
    ranges, pct = {}, {}
    for k in keys:
        v = np.array(samples[k]) if samples[k] else np.array([m[k]])
        lo, hi = (float(x) for x in np.percentile(v, [10, 90]))
        lo, hi = min(lo, m[k]), max(hi, m[k])
        ranges[k] = [round(lo, 4), round(hi, 4)]
        pct[k] = round(100 * (hi - lo) / 2 / m[k], 1) if m[k] > 0 else None

    ref_size = ref["length_m"] if ref["kind"] == "line" else max(ref["width_m"], ref["length_m"])
    dist = float(np.linalg.norm(m["centre"] - frame.centre))
    if ref["kind"] == "line":
        warnings.append("Ruler mode is only valid for a photo taken straight down at the hole; at an angle the size is wrong.")
    if dist > FAR_FACTOR * ref_size:
        warnings.append(f"The hole is {dist:.2f} m from the reference, more than {FAR_FACTOR:g} times the reference's "
                        "size: perspective errors grow with distance. Put the reference right next to the hole.")
    if frame.px < MIN_REF_PX:
        warnings.append(f"The reference is only {frame.px:.0f} pixels across on its shortest side (under "
                        f"{MIN_REF_PX:.0f} pixels): move closer or use a bigger reference.")
    if (pct["area_m2"] or 0) > WIDE_PCT:
        warnings.append(f"The size is uncertain (area ±{pct['area_m2']:.0f} %): tap the corners precisely with the "
                        "magnifier, make the reference bigger in the photo, or take the photo more from above.")
    if tol > 0 and len(samples["area_m2"]) < 0.9 * int(draws):
        warnings.append("The measurement is unstable: small tap errors on the reference would put the hole beyond the "
                        "horizon. Use a bigger reference, closer to the hole, or a photo taken more from above.")
    if ambiguous:
        warnings.append("Check which side of the reference is the long one: the photo does not show it clearly. Use Swap if it is wrong.")
    return {
        "area_m2": round(m["area_m2"], 4), "perimeter_m": round(m["perimeter_m"], 3),
        "width_m": round(m["width_m"], 3), "length_m": round(m["length_m"], 3),
        "longest_m": round(m["longest_m"], 3), "distance_m": round(dist, 2),
        "ranges": ranges, "pct": pct, "warnings": warnings, "tol_px": tol,
        "ref": {**ref, "first_edge": first_edge, "auto": auto, "points": np.round(rp, 2).tolist()},
        "ref_px": round(frame.px, 1), "outline_from": src, "outline_px": np.round(o, 2).tolist(),
        "outline_m": np.round(m["P"] - frame.centre, 4).tolist(), "draws": len(samples["area_m2"]),
    }


# --- depth -------------------------------------------------------------------------------------------------
def rescale_depth(r: dict, m3d: dict) -> dict:
    """The 3D depth corrected by the reference: k = sqrt(measured area / 3D area), depth x k.

    A 3D reconstruction with the wrong scale gets lengths (and depth) wrong by the same factor and the
    area by its square, so the ratio of the two areas gives the factor."""
    m3d = m3d or {}
    a3 = m3d.get("area_m2")
    key = "depth_max_m" if m3d.get("depth_max_m") is not None else "depth_median_m"
    d3 = m3d.get(key)
    if not a3 or d3 is None or float(d3) <= 0:
        raise MeasureError("This pothole has no 3D depth and area to rescale. Type the depth measured on site.")
    a3, d3 = float(a3), float(d3)
    k = math.sqrt(r["area_m2"] / a3)
    if not K_RANGE[0] <= k <= K_RANGE[1]:
        raise MeasureError(f"The scale factor k = {k:.2f} is outside {K_RANGE[0]:g}-{K_RANGE[1]:g}: the outline you traced "
                           "and the 3D outline are probably not the same hole. Type the depth measured on site instead.")
    lo, hi = r["ranges"]["area_m2"]
    vol = m3d.get("volume_m3")
    return {"k": round(k, 3), "depth_m": round(d3 * k, 4), "depth_3d_m": d3, "depth_key": key, "area_3d_m2": a3,
            "depth_range": [round(d3 * math.sqrt(lo / a3), 4), round(d3 * math.sqrt(hi / a3), 4)],
            "volume_m3": round(float(vol) * k ** 3, 5) if vol else None}


def finding_metrics(r: dict, depth_cm: float | None = None, rescale: dict | None = None) -> dict:
    """Metrics in the form the rest of the app reads (materials.bill, job card, plans, exports).

    Depth comes only from a typed value or a rescaled 3D depth; without either there is no depth,
    and the materials estimate stays unavailable."""
    m = {k: r[k] for k in ("area_m2", "width_m", "length_m", "perimeter_m")}
    m["diameter_m"] = r["longest_m"]
    if depth_cm is not None:
        d = float(depth_cm)
        if not 0.1 <= d <= 200:
            raise MeasureError("The depth must be 0.1 to 200 cm.")
        m["depth_max_m"] = round(d / 100, 4)
        m["volume_m3"] = round(r["area_m2"] * m["depth_max_m"], 5)
    elif rescale:
        m["depth_max_m"] = rescale["depth_m"]
        m["volume_m3"] = rescale["volume_m3"] if rescale.get("volume_m3") else round(r["area_m2"] * rescale["depth_m"], 5)
    return m

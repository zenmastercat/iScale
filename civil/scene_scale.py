"""Scale a monocular 3D clip from objects of known size seen in its frames ("scene references").

LingBot-Map rebuilds a clip up to an unknown scale. Without GPS, civil/align.py guesses it from the
camera height, which can be far off. Here a person taps the two ends of something whose real length
is known (lane width, a licence plate, a manhole cover, a typed tape measurement) in one of the
clip's stored frames, and

  1  a ray is cast from that frame's camera through each tapped pixel
     (pixel of the stored frame -> LingBot model-image pixel -> camera ray -> world, using the
     saved per-frame intrinsics and the recon's camera-to-world pose);
  2  each ray is intersected with the point cloud: the points within a narrow cone around the ray
     (1.5 to 12 model pixels wide), the nearest dense layer along it (floaters in front are skipped),
     and a plane fitted to that layer; the ray meets the plane (median depth when the fit is poor);
  3  the two 3D points give the length in model units d3 (for a height such as a kerb or a cone, only the
     vertical part: the cloud is z-up), and the scale s = known / d3.

Uncertainty of one reference: Monte Carlo over the taps (every tap moved by up to +-tol_px, uniform,
like civil/measure.py) and the plane fit's standard error along the ray, combined with the
object's own tolerance (rel_error from the catalog; treated as one standard deviation).
Several references are combined in log space: a weighted median finds the centre, references more
than 3 sigma from it are flagged as outliers (only when a majority of at least two others agree), the
rest are averaged with inverse-variance weights (generalised least squares: references of the same
standard object share that object's size error, which more taps cannot average away), and the error
is widened when they scatter more than their own errors allow (Birge ratio). The +- reported is one
sigma; the range is the 10th-90th percentile.

Pure numpy; HTTP routes and the survey rescale are in civil/scene_scale_api.py.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import CONFIG_DIR

TOL_PX = 3.0            # tap tolerance in pixels of the stored frame (same as the photo measuring tool)
DRAWS = 120
SEED = 20261119
CONES_PX = (1.5, 3.0, 6.0, 12.0)   # cone radius around the ray, in model-image pixels, tried in turn
MIN_SUPPORT = 8         # points needed on the surface the ray meets
GOOD_SUPPORT = 30       # widen the cone until this many, if the cloud allows
Z_OUT = 3.0             # outlier threshold, in sigma
P10 = 1.2815515655446004
MIN_REL = 0.002         # no reference is better than 0.2 %
GRAZING_WARN_DEG = 4.0  # a ray meeting the surface flatter than this: depth is very uncertain
K_RANGE = (0.05, 20.0)  # accepted rescale factor in one step


class ScaleError(ValueError):
    """Bad scene-scale input; the message is shown to the person tapping."""


# --- cameras --------------------------------------------------------------------------------------------
def frame_to_model(uv, geo: dict | None) -> np.ndarray:
    """A pixel of the stored clip frame -> the LingBot model-image pixel (the inverse of jobcard._box_to_frame).

    The frame files are already cut to the band (civil/video/frames.extract_clip), so there is no y0 here."""
    u, v = float(uv[0]), float(uv[1])
    if not geo:
        return np.array([u, v])
    return np.array([u * float(geo["sx"]), v * float(geo["sy"]) - float(geo.get("crop_top", 0))])


@dataclass
class Camera:
    c2w: np.ndarray       # 4x4 camera-to-world, OpenCV axes (x right, y down, z forward)
    K: np.ndarray         # 3x3 intrinsics in model-image pixels
    geo: dict | None      # stored frame -> model image (frames.model_geometry); None = the same pixels

    @property
    def f(self) -> float:
        return float(0.5 * (self.K[0, 0] + self.K[1, 1]))

    def ray(self, uv_frame) -> tuple[np.ndarray, np.ndarray]:
        u, v = frame_to_model(uv_frame, self.geo)
        d = np.array([(u - self.K[0, 2]) / self.K[0, 0], (v - self.K[1, 2]) / self.K[1, 1], 1.0])
        r = np.asarray(self.c2w, dtype=np.float64)[:3, :3]
        dw = r @ d
        n = float(np.linalg.norm(dw))
        if n < 1e-12:
            raise ScaleError("This frame's camera pose is broken (zero rotation).")
        return np.asarray(self.c2w, dtype=np.float64)[:3, 3].copy(), dw / n


def cameras_from_rec(rec, intrinsics=None, geo=None) -> list[Camera]:
    """One Camera per clip frame from the recon's poses and the saved intrinsics (rec.meta or given)."""
    if rec.poses is None or not len(rec.poses):
        raise ScaleError("This 3D model has no camera poses, so taps in the frames cannot be placed in 3D.")
    ks = intrinsics if intrinsics is not None else rec.meta.get("intrinsics")
    if ks is None:
        raise ScaleError("This clip was built before the camera intrinsics were saved. Choose Try again on the clip "
                         "to rebuild it, then fix the scale.")
    ks = np.asarray(ks, dtype=np.float64)
    if ks.shape == (3, 3):
        ks = np.repeat(ks[None], len(rec.poses), axis=0)
    if ks.ndim != 3 or ks.shape[1:] != (3, 3) or len(ks) != len(rec.poses):
        raise ScaleError(f"The saved intrinsics ({len(ks)}) do not match the camera poses ({len(rec.poses)}).")
    g = geo if geo is not None else rec.meta.get("frame_geometry")
    return [Camera(c2w=np.asarray(p, dtype=np.float64), K=k, geo=g) for p, k in zip(rec.poses, ks)]


def rescale(rec, k: float, pivot=None) -> np.ndarray:
    """Multiply the recon's lengths by k about `pivot` (default: under the first camera, on the ground z = 0,
    so the clip stays where it is on the map and the ground stays at z = 0). Mutates rec; returns the pivot."""
    k = float(k)
    if not (math.isfinite(k) and k > 0):
        raise ScaleError("The scale factor must be a positive number.")
    if pivot is None:
        traj = rec.trajectory()
        pivot = np.array([traj[0, 0], traj[0, 1], 0.0]) if traj is not None and len(traj) else np.zeros(3)
    pivot = np.asarray(pivot, dtype=np.float64)
    rec.points = (pivot + k * (rec.points.astype(np.float64) - pivot)).astype(np.float32)
    if rec.poses is not None:
        p = np.array(rec.poses, dtype=np.float64)
        p[:, :3, 3] = pivot + k * (p[:, :3, 3] - pivot)
        rec.poses = p
    return pivot


# --- ray / cloud ------------------------------------------------------------------------------------------
def _cone_subset(points: np.ndarray, o: np.ndarray, d: np.ndarray, tan_cone: float) -> tuple[np.ndarray, np.ndarray]:
    """Points in front of the camera within the cone (float64 copies) and their indices."""
    v = points.astype(np.float32) - o.astype(np.float32)
    t = v @ d.astype(np.float32)
    ok = t > 0
    if not ok.any():
        return np.zeros((0, 3)), np.zeros(0, np.int64)
    idx = np.flatnonzero(ok)
    vv = v[idx]
    tt = t[idx]
    perp2 = np.einsum("ij,ij->i", vv, vv) - tt * tt
    keep = perp2 <= (tan_cone * tt) ** 2 * 1.05 + 1e-12
    idx = idx[keep]
    return points[idx].astype(np.float64), idx


def _surface(P: np.ndarray, o: np.ndarray, d: np.ndarray, tan_cone: float, min_support: int) -> dict | None:
    """The nearest dense layer of P along the ray, and where the ray meets it.

    Monocular depth is noisy along each source camera's view, so the road is a layer some centimetres
    thick. Start at the first dense spot along the ray (sparse floaters in front are skipped), then
    move a window to the middle of that layer (median within +-2.5 robust sigma, at most +-20 % of
    the depth, so a surface far behind is not swallowed). A plane fitted to the layer gives the hit
    when the layer is thin and the fit is clear; otherwise the layer's median depth does."""
    if len(P) < min_support:
        return None
    v = P - o
    t = v @ d
    perp = np.linalg.norm(v - t[:, None] * d, axis=1)
    m = (t > 0) & (perp <= tan_cone * t + 1e-12)
    if m.sum() < min_support:
        return None
    P, t = P[m], t[m]
    order = np.argsort(t)
    P, t = P[order], t[order]
    w = max(0.03, 3.0 * tan_cone)
    hi = np.searchsorted(t, t * (1 + w), side="right")
    dense = np.flatnonzero(hi - np.arange(len(t)) >= min_support)
    if not len(dense):
        return None
    t0 = t[dense[0]]
    c, b = t0 * (1 + w / 2), t0 * w / 2
    for _ in range(30):
        sel = np.abs(t - c) <= b
        if sel.sum() < min_support:
            break
        tc = float(np.median(t[sel]))
        rs = 1.4826 * float(np.median(np.abs(t[sel] - tc)))
        nb = float(np.clip(2.5 * rs, w * tc / 2, 0.2 * tc))
        done = abs(tc - c) < 1e-4 * tc and abs(nb - b) < 1e-3 * tc
        c, b = tc, nb
        if done:
            break
    sel = np.abs(t - c) <= b
    if sel.sum() < min_support:
        return None
    Q, tq = P[sel], t[sel]
    hit, method, grazing = None, "median", None
    med = float(np.median(tq))
    rs = 1.4826 * float(np.median(np.abs(tq - med)))
    n_used = len(Q)
    sigma_t = rs / math.sqrt(min(n_used, 25))   # depth errors of nearby pixels are correlated: no credit past ~25 points
    spread = rs / med if med > 0 else 0.0
    if len(Q) >= max(6, min_support):
        cq = Q.mean(0)
        _, sv, vt = np.linalg.svd(Q - cq, full_matrices=False)
        n = vt[-1]
        res = (Q - cq) @ n
        denom = float(n @ d)
        if len(sv) == 3 and sv[1] > 3 * sv[2] and abs(denom) > 0.05:
            grazing = math.degrees(math.asin(min(1.0, abs(denom))))
            th = float(n @ (cq - o)) / denom
            sd = float(np.std(res))
            if abs(th - c) <= b and sd / abs(denom) < rs * 1.5 + 1e-12:
                hit, method = th, "plane"
                sigma_t = sd / abs(denom) / math.sqrt(min(n_used, 25))
                spread = sd / abs(denom) / th
    if hit is None:
        hit = med
    return {"t": hit, "point": o + hit * d, "support": int(n_used), "method": method, "sigma_t": sigma_t,
            "spread": spread, "grazing_deg": grazing}


def intersect(points: np.ndarray, o: np.ndarray, d: np.ndarray, f_px: float, cones_px=CONES_PX,
              min_support: int = MIN_SUPPORT) -> dict:
    """Where the ray o + t d (d unit) meets the cloud. Raises ScaleError when no cone finds a surface."""
    d = np.asarray(d, dtype=np.float64)
    o = np.asarray(o, dtype=np.float64)
    P, _ = _cone_subset(points, o, d, max(cones_px) / f_px)
    best = None
    for c in cones_px:   # the narrowest cone with enough points; a wider one only when the cloud is sparse there
        s = _surface(P, o, d, c / f_px, min_support)
        if s is not None:
            s["cone_px"] = c
            best = s
            if s["support"] >= GOOD_SUPPORT:
                break
    if best is not None:
        return best
    raise ScaleError(f"no surface within {max(cones_px):g} model pixels of the ray ({len(P)} points near it)")


# --- one reference ------------------------------------------------------------------------------------------
def _taps(ref: dict, n_frames: int) -> list[tuple[int, np.ndarray]]:
    pts = ref.get("points") or []
    if len(pts) != 2:
        raise ScaleError("Tap the two ends of the reference: exactly 2 points.")
    out = []
    for k, p in enumerate(pts):
        try:
            fr = int(p["frame"])
            xy = np.asarray(p["xy"], dtype=np.float64).reshape(2)
        except (KeyError, TypeError, ValueError):
            raise ScaleError(f"Point {k + 1} needs a frame number and x, y pixels.") from None
        if not np.isfinite(xy).all():
            raise ScaleError(f"Point {k + 1} must have finite x, y pixels.")
        if not 0 <= fr < n_frames:
            raise ScaleError(f"There is no frame {fr} in this clip (it has {n_frames} frames).")
        out.append((fr, xy))
    if out[0][0] == out[1][0] and np.linalg.norm(out[0][1] - out[1][1]) < 2.0:
        raise ScaleError("The two ends are on the same spot. Tap both ends of the object.")
    return out


def measure_ref(points: np.ndarray, cams: list[Camera], ref: dict, tol_px: float = TOL_PX, draws: int = DRAWS,
                seed: int = SEED) -> dict:
    """One reference: {"points": [{"frame", "xy"}, {"frame", "xy"}], "known_m", "rel_error"} ->
    3D end points (model units), d3, implied scale, its uncertainty and warnings."""
    known = float(ref.get("known_m") or 0)
    if not (known > 0 and math.isfinite(known)):
        raise ScaleError("The real length of the reference must be a positive number of metres.")
    rel_ref = float(ref.get("rel_error") or 0.0)
    if not (0 <= rel_ref < 1):
        raise ScaleError("The reference's relative error must be between 0 and 1.")
    taps = _taps(ref, len(cams))
    hits, subsets = [], []
    for k, (fr, xy) in enumerate(taps):
        cam = cams[fr]
        o, d = cam.ray(xy)
        reach = (max(CONES_PX) + 1.5 * tol_px * max(1.0, float((cam.geo or {}).get("sx", 1.0)))) / cam.f
        P, _ = _cone_subset(points, o, d, reach)
        try:
            h = intersect(P, o, d, cam.f)
        except ScaleError as e:
            raise ScaleError(f"The tap for point {k + 1} (frame {fr}) does not hit the 3D model: {e}. Tap on the road or "
                             "an object the 3D shows, not the sky or a blank area.") from None
        hits.append(h)
        subsets.append((cam, P))
    p1, p2 = hits[0]["point"], hits[1]["point"]
    vertical = bool(ref.get("vertical"))
    # a height (kerb, cone, tyre): only the vertical part counts. Near a small upright face the two rays often
    # meet the cloud at slightly different depths (the top tap on the surface behind the edge, the foot in the
    # gutter), which would add a horizontal part to a straight-line distance; the cloud is z-up here.
    dist = (lambda a, b: abs(float(a[2] - b[2]))) if vertical else (lambda a, b: float(np.linalg.norm(a - b)))
    d3 = dist(p1, p2)
    if d3 < 1e-3 * max(hits[0]["t"], hits[1]["t"]):
        raise ScaleError("The two ends are on the same spot in 3D. Tap both ends of the object.")
    scale = known / d3

    # Monte Carlo: taps moved by up to +-tol px, the surface position by its standard error along the ray
    rng = np.random.default_rng(seed)
    logs = []
    fails = 0
    for _ in range(int(draws) if tol_px > 0 else 0):
        q = []
        for (fr, xy), (cam, P), h in zip(taps, subsets, hits):
            xj = xy + rng.uniform(-tol_px, tol_px, 2)
            o, d = cam.ray(xj)
            try:
                hj = intersect(P, o, d, cam.f, cones_px=tuple(c for c in CONES_PX if c >= h["cone_px"]))
            except ScaleError:
                q = None
                break
            q.append(o + (hj["t"] + rng.normal(0, h["sigma_t"])) * d)
        if q is None:
            fails += 1
            continue
        dj = dist(q[0], q[1])
        if dj > 0:
            logs.append(math.log(known / dj))
    if len(logs) >= 10:
        lo, hi = np.percentile(logs, [10, 90])
        rel_meas = float(hi - lo) / (2 * P10)
    else:  # no tap tolerance: the fit errors only
        rel_meas = math.hypot(hits[0]["sigma_t"], hits[1]["sigma_t"]) / d3
    rel_sigma = max(MIN_REL, math.hypot(rel_meas, rel_ref))
    warnings = []
    for k, h in enumerate(hits):
        if h["grazing_deg"] is not None and h["grazing_deg"] < GRAZING_WARN_DEG:
            warnings.append(f"Point {k + 1} is far away: its ray meets the surface at only {h['grazing_deg']:.1f}°, so "
                            "its depth is uncertain. Choose a frame where the object is closer.")
        if h["support"] < 2 * MIN_SUPPORT:
            warnings.append(f"Point {k + 1} has only {h['support']} 3D points around it.")
    if vertical and float(np.linalg.norm((p1 - p2)[:2])) > 1.5 * d3:
        warnings.append("The two ends are far apart sideways for a height: tap the foot and the top on one vertical line.")
    if draws and fails > 0.1 * draws:
        warnings.append("Small tap errors make the ray miss the 3D model: tap precisely, with the magnifier.")
    return {
        "known_m": known, "d3": d3, "scale": scale, "rel_sigma": rel_sigma, "rel_meas": rel_meas, "rel_ref": rel_ref,
        "pct": round(100 * rel_sigma, 1),
        "range": [scale * math.exp(-P10 * rel_sigma), scale * math.exp(P10 * rel_sigma)],
        "points_3d": [h["point"].tolist() for h in hits], "depth": [h["t"] for h in hits],
        "support": [h["support"] for h in hits], "method": [h["method"] for h in hits],
        "spread": [h["spread"] for h in hits], "cone_px": [h["cone_px"] for h in hits],
        "taps": [{"frame": fr, "xy": [round(float(xy[0]), 2), round(float(xy[1]), 2)]} for fr, xy in taps],
        "tol_px": tol_px, "draws": len(logs), "warnings": warnings,
    }


# --- several references ----------------------------------------------------------------------------------
def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, 0.5 * cw[-1])])


def _covariance(items: list[dict], sig: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Covariance of the log scales, split as (shared, own): C = shared + diag(own).

    The size error of a standard object (rel_ref) is the same for every reference that uses that object:
    three taps on kerbs of one assumed height all share its ±, so they must not shrink it by sqrt(3). Only
    the measurement part (taps, depth noise) is independent. References with no "key" (typed custom
    distances, each measured on its own) and objects used once are independent altogether."""
    n = len(items)
    keys = [i.get("key") for i in items]
    rr = np.array([min(float(i.get("rel_ref") or 0.0), float(s_)) for i, s_ in zip(items, sig)])
    shared = np.zeros((n, n))
    own = sig ** 2
    for a in range(n):
        mates = [b for b in range(n) if b != a and keys[a] is not None and keys[a] == keys[b]]
        if mates:
            shared[a, a] = rr[a] ** 2
            own[a] = sig[a] ** 2 - rr[a] ** 2
            for b in mates:
                shared[a, b] = rr[a] * rr[b]
    return shared, own


def combine(items: list[dict]) -> dict:
    """items: [{"scale", "rel_sigma", optional "rel_ref" and "key"}] -> combined scale, 1-sigma relative error,
    p10-p90 range, outlier flags.

    The centre is the generalised least-squares mean of the log scales: with independent references (different
    objects) that is the inverse-variance weighted mean; references of the same object share its size error
    (see _covariance)."""
    if not items:
        raise ScaleError("Add at least one reference.")
    x = np.array([math.log(float(i["scale"])) for i in items])
    sig = np.maximum(np.array([float(i["rel_sigma"]) for i in items]), MIN_REL)
    w = 1 / sig**2
    n = len(x)
    out = np.zeros(n, bool)
    z = np.zeros(n)
    warnings: list[str] = []
    if n >= 3:
        c = _wmedian(x, w)
        sh, ow = _covariance(items, sig)
        cov = sh + np.diag(ow)
        for i in range(n):
            # i against the others' GLS mean: var(x_i - m) = C_ii + V_m - 2 cov(x_i, m). A shared object size
            # cancels here, so one bad tap among several kerbs is still caught.
            o = [j for j in range(n) if j != i]
            co = np.linalg.inv(cov[np.ix_(o, o)])
            g = co @ np.ones(n - 1) / float(np.ones(n - 1) @ co @ np.ones(n - 1))
            var = cov[i, i] + float(g @ cov[np.ix_(o, o)] @ g) - 2 * float(g @ cov[o, i])
            z[i] = abs(x[i] - c) / math.sqrt(max(var, MIN_REL ** 2))
        cand = z > Z_OUT
        if cand.any() and (n - cand.sum()) >= max(2, math.ceil(n / 2)):
            out = cand
        elif cand.any():
            warnings.append("The references disagree with each other and no majority agrees: check the objects and the taps.")
    keep = ~out
    kept = [it for it, k in zip(items, keep) if k]
    xk = x[keep]
    shared, own = _covariance(kept, sig[keep])

    def gls(cv):
        ci = np.linalg.inv(cv)
        one = np.ones(len(xk))
        info = float(one @ ci @ one)
        return float(one @ ci @ xk) / info, 1 / math.sqrt(info), ci

    mean, s, ci = gls(shared + np.diag(own))
    chi2_dof = None
    if keep.sum() >= 2:
        r = xk - mean
        chi2_dof = float(r @ ci @ r) / (keep.sum() - 1)
        if chi2_dof > 1:
            # more scatter than the errors allow (Birge ratio): the independent part (taps, depth noise) was
            # underestimated. Scale only that part; a shared object size does not show in the scatter at all.
            mean, s, _ = gls(shared + np.diag(own * chi2_dof))
        if chi2_dof > 9 and not warnings:
            warnings.append("The references disagree more than their ± allows; the ± has been widened to cover them.")
    if out.any():
        warnings.append(f"{int(out.sum())} reference{'s' if out.sum() > 1 else ''} left out: more than {Z_OUT:g}σ from the others.")
    if len({i.get("key") for i in kept}) == 1 and kept[0].get("key") is not None and len(kept) > 1:
        warnings.append("All references are the same kind of object, so they share its size error: add a different "
                        "object or a tape measurement to make the ± smaller.")
    scale = math.exp(mean)
    return {"scale": scale, "rel_sigma": s, "pct": round(100 * s, 1),
            "range": [scale * math.exp(-P10 * s), scale * math.exp(P10 * s)],
            "outliers": [bool(v) for v in out], "z": [round(float(v), 2) for v in z], "used": int(keep.sum()),
            "chi2_dof": chi2_dof, "warnings": warnings}


def estimate(points: np.ndarray, cams: list[Camera], refs: list[dict], tol_px: float = TOL_PX, draws: int = DRAWS,
             strict: bool = False) -> dict:
    """Every reference measured; the combination of those that worked. strict: any failure raises."""
    results = []
    for i, r in enumerate(refs):
        try:
            key = None if (r.get("ref_id") in (None, "custom")) else r["ref_id"]   # same standard object: shared size error
            results.append({**measure_ref(points, cams, r, tol_px=tol_px, draws=draws), "index": i, "key": key})
        except ScaleError as e:
            if strict:
                raise ScaleError(f"Reference {i + 1}: {e}") from None
            results.append({"index": i, "error": str(e)})
    ok = [r for r in results if "error" not in r]
    if not ok:
        raise ScaleError(results[0]["error"] if results else "Add at least one reference.")
    comb = combine(ok)
    for r, flag, zz in zip(ok, comb["outliers"], comb["z"]):
        r["outlier"], r["z"] = flag, zz
    return {"refs": results, "combined": comb}


def describe_parts(refs: list[dict], used: list[int] | None = None) -> str:
    """'lane width ×2, plate width ×1': which objects, how many times."""
    idx = used if used is not None else list(range(len(refs)))
    counts: dict[str, int] = {}
    for i in idx:
        lab = str(refs[i].get("label") or refs[i].get("ref_id") or "reference")
        counts[lab] = counts.get(lab, 0) + 1
    return ", ".join(f"{k} ×{v}" for k, v in counts.items())


def describe(refs: list[dict], used: list[int] | None = None) -> str:
    """'3 scene references (lane width ×2, plate width ×1)' for the survey notes."""
    n = len(used if used is not None else refs)
    return f"{n} scene reference{'s' if n != 1 else ''} ({describe_parts(refs, used)})"


# --- the catalog of standard objects ------------------------------------------------------------------
CUSTOM = {"id": "custom", "name_en": "Custom known distance", "name_th": "ระยะที่รู้ค่า (กำหนดเอง)",
          "dimension_name": "distance you measured or know", "value_m": None, "rel_error": None, "group": "custom",
          "custom": True, "plane": "any", "notes": "Measure it on site with a tape, or type a length you know for certain."}
GROUPS = ("road_markings", "vehicles", "street_furniture", "custom")
_GROUP_RE = [
    ("road_markings", re.compile(r"lane|line|marking|crosswalk|zebra|arrow|stop.?bar|chevron|edge|kerb.?paint|stripe|dash", re.I)),
    ("vehicles", re.compile(r"plate|car|vehicle|wheel|tyre|tire|bus|truck|motorcycle|bike|van|tuk", re.I)),
]


def catalog_path() -> Path:
    env = os.environ.get("CIVIL_SCENE_REFS")
    return Path(env) if env else CONFIG_DIR / "scene_refs.json"


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _normalise(e: dict) -> dict | None:
    """A research-catalog entry -> what the app uses; None when it has no usable size."""
    if not isinstance(e, dict) or not e.get("id"):
        return None
    if e.get("custom") or e.get("id") == "custom":
        return None   # the custom entry is always the app's own (CUSTOM)
    value = _num(e.get("value_m"))
    if value is None or not 0.01 <= value <= 100:
        return None
    rel = _num(e.get("rel_error"))
    if rel is not None and rel > 1:     # given in percent
        rel = rel / 100
    rel_from = "rel_error" if rel is not None else None
    if rel is None:
        tol = _num(e.get("tolerance_m"))
        sp = e.get("spread")
        if tol is not None:
            rel, rel_from = abs(tol) / value, "tolerance_m"
        elif isinstance(sp, (list, tuple)) and len(sp) == 2 and _num(sp[0]) is not None and _num(sp[1]) is not None:
            rel, rel_from = abs(_num(sp[1]) - _num(sp[0])) / 2 / value, "spread"
        elif _num(sp) is not None:
            rel, rel_from = abs(_num(sp)) / value, "spread"
    unknown = rel is None
    if unknown:
        rel = 0.10   # the source gives no tolerance: be cautious, and say so in the UI
    text = " ".join(str(e.get(k) or "") for k in ("id", "name_en", "dimension_name"))
    group = e.get("group") or e.get("category")
    if group not in GROUPS:
        group = next((g for g, rx in _GROUP_RE if rx.search(text)), "street_furniture")
    urls = [str(u) for u in (e.get("source_urls") or []) if u][:6]
    # a size without a source is never shown as a standard: it is provisional, whatever the file says
    provisional = bool(e.get("provisional")) or not urls
    return {"id": str(e["id"])[:60], "name_en": e.get("name_en") or str(e["id"]), "name_th": e.get("name_th"),
            "provisional": provisional, "source_note": e.get("source_note"),
            "dimension_name": e.get("dimension_name"), "value_m": value, "rel_error": round(float(rel), 5),
            "rel_from": rel_from, "rel_unknown": unknown, "tolerance_m": _num(e.get("tolerance_m")),
            "spread": e.get("spread"), "plane": e.get("plane"), "visibility": e.get("visibility"),
            "region": e.get("region"), "source_urls": urls,
            "source_dates": list(e.get("source_dates") or [])[:6] if isinstance(e.get("source_dates"), list)
            else ([e["source_dates"]] if e.get("source_dates") else []),
            "notes": e.get("notes"), "group": group, "custom": False, "vertical": bool(e.get("vertical"))}


def load_catalog() -> dict:
    """The standard-size objects (config/scene_refs.json, from the research catalog), plus the custom entry."""
    p = catalog_path()
    raw, meta = [], {}
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except ValueError:
            data = []
        if isinstance(data, dict):
            meta = {k: v for k, v in data.items() if not isinstance(v, list) or k in ("sources",)}
            raw = next((v for k, v in data.items() if isinstance(v, list) and k in ("objects", "refs", "references", "items", "entries")),
                       next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), []))
        elif isinstance(data, list):
            raw = data
    objs, seen = [], set()
    for e in raw:
        n = _normalise(e)
        if n and n["id"] not in seen:
            seen.add(n["id"])
            objs.append(n)
    objs.append(dict(CUSTOM))
    return {"objects": objs, "groups": list(GROUPS), "source": p.name if p.is_file() else None,
            "note": meta.get("_note") or meta.get("note") or meta.get("description")}


def resolve(spec: dict, catalog: dict | None = None) -> dict:
    """A reference choice {ref_id, known_m?, tol_m?} -> {id, label, known_m, rel_error, rel_unknown}."""
    cat = catalog or load_catalog()
    rid = str(spec.get("ref_id") or "custom")
    obj = next((o for o in cat["objects"] if o["id"] == rid), None)
    if obj is None:
        raise ScaleError(f"Unknown reference object {rid!r}.")
    if obj.get("custom"):
        known = _num(spec.get("known_m"))
        if known is None or not 0.05 <= known <= 200:
            raise ScaleError("Type the known distance in metres (0.05 to 200 m).")
        tol = _num(spec.get("tol_m"))
        if tol is not None and not 0 <= tol < known:
            raise ScaleError("The ± of the known distance must be smaller than the distance.")
        rel = (tol / known) if tol else 0.01
        return {"id": "custom", "label": f"{known:g} m (custom)", "known_m": known, "rel_error": rel,
                "rel_unknown": tol is None, "group": "custom"}
    return {"id": obj["id"], "label": obj["name_en"], "known_m": obj["value_m"], "rel_error": obj["rel_error"],
            "rel_unknown": obj["rel_unknown"], "group": obj["group"], "provisional": obj.get("provisional", False),
            "vertical": obj.get("vertical", False)}

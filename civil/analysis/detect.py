"""Rule-based (non-learned) detection of road defects and roadside assets.

Every finding carries the measurements that triggered it and a plain-language
"evidence" string, so a reviewer can see why it was flagged.  Geometry cannot tell
apart everything a trained model could (e.g. crack types); those are left to manual
tagging or to labels supplied by an external decoder.
"""

from __future__ import annotations

import math

import numpy as np

from .raster import design, fill_holes, grid_stats, grow, label_components, perimeter, robust_surface, windowed_residual


def _severity_pothole(depth: float, dia: float) -> str:
    if depth >= 0.05 and dia >= 0.45:
        return "high"
    if depth >= 0.05 or dia >= 0.45:
        return "medium"
    return "low"


def _bbox(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> list[float]:
    return [float(x.min()), float(y.min()), float(z.min()), float(x.max()), float(y.max()), float(z.max())]


class SegmentSurface:
    """Rasterised road and sidewalk surfaces of one segment, in (station, offset) space."""

    def __init__(self, s: np.ndarray, o: np.ndarray, z: np.ndarray, s0: float, s1: float, p: dict):
        self.p = p
        self.cell = c = float(p["raster_m"])
        self.s0 = s0
        self.o0 = -14.0
        self.nu = max(1, int(math.ceil((s1 - s0) / c)))
        self.nv = int(28.0 / c)
        self.g = grid_stats(s, o, z, c, self.s0, self.o0, self.nu, self.nv)
        self.offsets = self.o0 + (np.arange(self.nv) + 0.5) * c
        self.stations = self.s0 + (np.arange(self.nu) + 0.5) * c

    def road_mask(self) -> np.ndarray:
        """Drivable surface: cells connected to the vehicle path without a curb-sized step.

        Grows from the cells under the path; a neighbour joins when its height differs by
        less than 5 cm (a curb is ~15 cm).  Holes (potholes with steep walls) are filled,
        then the edge is eroded by 0.3 m so curb faces never count as pavement.
        """
        med = self.g["median"].copy()
        for _ in range(2):  # fill sparse empty cells from their neighbours
            pad = np.pad(med, 1, constant_values=np.nan)
            win = np.lib.stride_tricks.sliding_window_view(pad, (3, 3)).reshape(self.nu, self.nv, 9)
            with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
                __import__("warnings").simplefilter("ignore", RuntimeWarning)
                fill = np.nanmedian(win, axis=2)
            med = np.where(np.isfinite(med), med, fill)
        # a cell is a barrier when its 0.3 m neighbourhood spans a curb-sized height range;
        # mixed cells on a curb line form a continuous wall this way
        pad = np.pad(med, 1, constant_values=np.nan)
        win = np.lib.stride_tricks.sliding_window_view(pad, (3, 3)).reshape(self.nu, self.nv, 9)
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            rng_ = np.nanmax(win, axis=2) - np.nanmin(win, axis=2)
        ok = np.isfinite(med) & (np.abs(self.offsets) < 12.0)[None, :] & (np.nan_to_num(rng_, nan=1.0) < 0.06)
        mask = grow(ok & (np.abs(self.offsets) < 0.8)[None, :], ok)
        # fill holes: non-road cells not connected to the raster border
        border = np.zeros_like(mask)
        border[[0, -1], :] = True
        border[:, [0, -1]] = True
        outside = grow(border & ~mask, ~mask)
        mask = mask | (~outside)
        self.road_full = mask.copy()
        k = max(1, int(round(0.3 / self.cell)))
        for _ in range(k):
            e = mask.copy()
            e[1:, :] &= mask[:-1, :]
            e[:-1, :] &= mask[1:, :]
            e[:, 1:] &= mask[:, :-1]
            e[:, :-1] &= mask[:, 1:]
            mask = e
        return mask

    def edges(self, full: np.ndarray) -> tuple[float, float]:
        """Median right (min) and left (max) offset of the drivable surface over the segment."""
        rights, lefts = [], []
        for row in full:
            idx = np.flatnonzero(row)
            if len(idx):
                rights.append(self.offsets[idx[0]])
                lefts.append(self.offsets[idx[-1]])
        if not rights:
            return 0.0, 0.0
        return float(np.median(rights)), float(np.median(lefts))

    def residual(self, cells: np.ndarray, quad: bool = True) -> np.ndarray:
        """Robust surface fitted to the masked cells. Returns the residual grid (NaN outside)."""
        med = self.g["median"]
        uu, vv = np.meshgrid(self.stations - self.s0, self.offsets, indexing="ij")
        r = windowed_residual(uu, vv, med, cells, float(self.p.get("surface_window_m") or 0), quad=quad)
        self.surface = r.surface
        return np.asarray(r)

    def to_enu(self, si: np.ndarray, oi: np.ndarray, path: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
        st = self.stations[si]
        off = self.offsets[oi]
        k = np.clip((st / step).astype(int), 0, len(path) - 2)
        fwd = path[k + 1] - path[k]
        fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-12
        base = path[k] + fwd * (st - k * step)[:, None]
        left = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
        xy = base + left * off[:, None]
        return xy[:, 0], xy[:, 1]


def detect_surface(seg: dict, surf: SegmentSurface, path: np.ndarray, step: float, p: dict) -> tuple[list[dict], dict]:
    """Pavement and sidewalk defects for one segment. Returns (findings, segment metrics)."""
    out: list[dict] = []
    c = surf.cell
    cell_area = c * c
    road = surf.road_mask()
    right, left = surf.edges(surf.road_full)
    res = surf.residual(road)
    road_width = max(0.0, left - right)
    metrics = {"road_left_m": round(left, 2), "road_right_m": round(right, 2), "road_width_m": round(road_width, 2)}
    if not np.isfinite(res).any():
        metrics["coverage"] = 0.0
        return out, metrics
    expected = (surf.offsets > right + 0.3) & (surf.offsets < left - 0.3)
    metrics["coverage"] = round(float(min(1.0, np.isfinite(res).sum() / max(1, expected.sum() * surf.nu))), 3)
    lo, hi = right + 0.3, left - 0.3
    mn = surf.g["low"]  # robust floor, see grid_stats
    surface = surf.surface

    def emit(kind: str, cells: np.ndarray, severity: str | None, metrics_: dict, evidence: str) -> None:
        x, y = surf.to_enu(cells[:, 0], cells[:, 1], path, step)
        zc = surface[cells[:, 0], cells[:, 1]] + np.nan_to_num(res[cells[:, 0], cells[:, 1]])
        out.append({"type": kind, "severity": severity, "source": "geometry",
                    "x": float(x.mean()), "y": float(y.mean()), "z": float(np.nanmean(zc)),
                    "bbox": _bbox(x, y, zc), "metrics": metrics_, "evidence": evidence, "segment_id": seg["id"]})

    # --- depressions: potholes, sunken covers, settlements ---------------------
    dmin = float(p["pothole_min_depth_m"])
    seeds = np.nan_to_num(res, nan=0) < -dmin
    region = grow(seeds, np.nan_to_num(res, nan=0) < -0.01)
    used = np.zeros_like(region)
    for cells in label_components(region):
        area = len(cells) * cell_area
        if area < float(p["pothole_min_area_m2"]):
            continue
        r = res[cells[:, 0], cells[:, 1]]
        deep = surface[cells[:, 0], cells[:, 1]] - mn[cells[:, 0], cells[:, 1]]
        # deepest point, robustly: a few stray cells must not set it (90th percentile once there are 10 cells)
        depth = float(np.nanmax(deep)) if len(cells) < 10 else float(np.nanpercentile(deep, 90))
        depth_med = float(-np.nanmedian(r))
        # deeper than a road can be: in video this is water or a reflection inside the hole, not depth
        unreliable = depth > float(p.get("pothole_max_depth_m", 0.4))
        volume = float(-np.nansum(r) * cell_area)
        per = perimeter(cells) * c
        area_f = len(fill_holes(cells)) * cell_area
        per *= math.pi / 4  # 4-connected staircase perimeter overestimates a smooth outline
        circ = float(min(1.0, 4 * math.pi * area_f / (per * per))) if per > 0 else 0.0
        # share of the area within 25% of the median depth: ~1 for a flat recess, ~0.5 for a bowl
        flat = float(np.mean(np.abs(-r - depth_med) <= 0.25 * depth_med)) if depth_med > 0 else 0.0
        # floor shape: fit depth = c0 + c2 * (rho/R)^2 over all cells. A recessed cover has a
        # flat floor (c2 ~ 0); a pothole bowl gets deeper towards its middle (c2 << 0).
        ci = cells[:, 0].astype(float) - cells[:, 0].mean()
        cj = cells[:, 1].astype(float) - cells[:, 1].mean()
        rho2 = (ci * ci + cj * cj) * c * c / max(area / math.pi, 1e-6)
        ok_r = np.isfinite(r)
        bowl = 1.0
        if ok_r.sum() >= 8 and depth_med > 0:
            a_ = np.stack([np.ones(ok_r.sum()), rho2[ok_r]], 1)
            (c0, c2), *_ = np.linalg.lstsq(a_, -r[ok_r], rcond=None)
            bowl = float(-c2 / c0) if c0 > 0 else 1.0
        dia = 2 * math.sqrt(area / math.pi)
        used[cells[:, 0], cells[:, 1]] = True
        m = {"area_m2": round(area, 3), "depth_max_m": None if unreliable else round(depth, 3),
             "depth_median_m": round(depth_med, 3), "volume_m3": round(volume, 4), "diameter_m": round(dia, 2),
             "circularity": round(circ, 2), "flat_share": round(flat, 2), "bowl": round(bowl, 2)}
        if unreliable:
            m["depth_unreliable"] = True
        if bowl < 0.25 and flat > 0.7 and circ > 0.7 and 0.15 <= area <= 0.8 and depth_med < 0.06:
            sev = "high" if depth_med >= 0.05 else "medium" if depth_med >= 0.03 else "low"
            emit("manhole_sunken", cells, sev, m,
                 f"flat-floored round recess {depth_med * 100:.1f} cm below the road surface, {dia:.2f} m across (likely a sunken cover; confirm on site)")
        elif area > 3.0:
            sev = "high" if depth_med >= 0.05 else "medium" if depth_med >= 0.03 else "low"
            emit("depression", cells, sev, m, f"broad depression {area:.1f} m2, median {depth_med * 100:.1f} cm deep")
        elif unreliable:
            emit("pothole", cells, _severity_pothole(depth_med, dia), m,
                 f"depression {dia:.2f} m across, median {depth_med * 100:.1f} cm deep; its deepest point could not be "
                 "measured (the 3D shows it far below the road, most likely water or a reflection in the hole): measure on site")
        else:
            emit("pothole", cells, _severity_pothole(depth, dia), m,
                 f"depression {depth * 100:.1f} cm deep, {dia:.2f} m across, {volume * 1000:.1f} L missing material")

    # --- heaves / bumps (but not vehicles or debris standing on the road) -------
    hmin = float(p["heave_min_height_m"])
    edge_ok = (surf.offsets > lo + 0.4) & (surf.offsets < hi - 0.4)
    rr = np.nan_to_num(res, nan=0)
    hseed = (rr > hmin) & edge_ok[None, :]
    hreg = grow(hseed, (rr > 0.01) & edge_ok[None, :])
    for cells in label_components(hreg):
        area = len(cells) * cell_area
        h = float(rr[cells[:, 0], cells[:, 1]].max())
        if area < 0.1 or h > 0.15:
            continue
        used[cells[:, 0], cells[:, 1]] = True
        sev = "high" if h >= 0.05 else "medium" if h >= 0.035 else "low"
        emit("heave", cells, sev, {"area_m2": round(area, 3), "height_max_m": round(h, 3)},
             f"raised area {h * 100:.1f} cm above the road surface, {area:.2f} m2")

    # --- roughness (proxy for cracking / ravelling that geometry can't classify) -
    t = max(1, int(round(1.0 / c)))
    nu_t, nv_t = surf.nu // t, surf.nv // t
    rough = np.zeros((nu_t, nv_t), bool)
    stds = np.full((nu_t, nv_t), np.nan)
    for i in range(nu_t):
        for j in range(nv_t):
            blk = res[i * t:(i + 1) * t, j * t:(j + 1) * t]
            u = used[i * t:(i + 1) * t, j * t:(j + 1) * t]
            vals = blk[np.isfinite(blk) & ~u]
            if len(vals) >= 0.5 * t * t:
                stds[i, j] = np.std(vals)
    lim = float(p["roughness_std_m"])
    rough = np.nan_to_num(stds, nan=0) > lim
    all_std = res[np.isfinite(res) & ~used]
    metrics["surface_std_mm"] = round(float(np.std(all_std)) * 1000, 2) if len(all_std) else None
    for tiles in label_components(rough, 8):
        area = len(tiles) * 1.0 * (t * c) ** 2
        if area < float(p["roughness_min_area_m2"]):
            continue
        sd = float(np.nanmean(stds[tiles[:, 0], tiles[:, 1]]))
        if sd > 0.03:
            continue  # a curb edge or an object, not pavement texture
        cells = np.concatenate([np.stack(np.meshgrid(np.arange(i * t, (i + 1) * t), np.arange(j * t, (j + 1) * t), indexing="ij"), -1).reshape(-1, 2) for i, j in tiles])
        sev = "high" if sd > 0.012 else "medium" if sd > 0.009 else "low"
        emit("surface_roughness", cells, sev, {"area_m2": round(area, 2), "texture_std_mm": round(sd * 1000, 1)},
             f"surface texture deviation {sd * 1000:.1f} mm over {area:.0f} m2 (possible cracking or ravelling; confirm on site)")

    # --- sidewalk trip hazards: raised or sunk slabs ----------------------------
    b0, b1 = p["sidewalk_band_m"]
    step_min = float(p["trip_hazard_step_m"])
    for side, edge in ((1, left), (-1, right)):
        lo_s, hi_s = sorted((edge + side * b0, edge + side * b1))
        band = ((surf.offsets > lo_s) & (surf.offsets < hi_s))[None, :] & ~surf.road_full
        sres = surf.residual(band, quad=False)
        if not np.isfinite(sres).any():
            continue
        sr = np.nan_to_num(sres, nan=0)
        for sign in (1, -1):
            reg = grow(sign * sr > step_min, sign * sr > step_min * 0.5)
            for cells in label_components(reg):
                area = len(cells) * cell_area
                if area < 0.2:
                    continue
                stepv = float(np.median(np.abs(sr[cells[:, 0], cells[:, 1]])))
                if stepv > 0.12:  # an object on the sidewalk, not a slab
                    continue
                sev = "high" if stepv >= 0.025 else "medium" if stepv >= 0.013 else "low"
                x, y = surf.to_enu(cells[:, 0], cells[:, 1], path, step)
                zc = surf.surface[cells[:, 0], cells[:, 1]] + sr[cells[:, 0], cells[:, 1]]
                out.append({"type": "sidewalk_trip_hazard", "severity": sev, "source": "geometry",
                            "x": float(x.mean()), "y": float(y.mean()), "z": float(zc.mean()),
                            "bbox": _bbox(x, y, zc), "segment_id": seg["id"],
                            "metrics": {"step_m": round(stepv, 3), "area_m2": round(area, 2),
                                        "direction": "raised" if sign > 0 else "sunken"},
                            "evidence": f"sidewalk slab {'raised' if sign > 0 else 'sunk'} {stepv * 100:.1f} cm relative to its neighbours"})
    return out, metrics


# ---------------------------------------------------------------------------
# Roadside objects
# ---------------------------------------------------------------------------
def _classify_color(rgb: np.ndarray) -> str:
    if rgb is None or len(rgb) == 0:
        return "other"
    r, g, b = np.median(rgb.astype(float), axis=0)
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / (mx + 1e-6)
    if sat < 0.25:
        return "regulatory" if mx > 170 else "other"
    if r >= g and r >= b:
        return "warning" if g > 0.6 * r else "stop"
    if g >= r and g >= b:
        return "guide"
    return "other"


def detect_objects(xyz: np.ndarray, rgb: np.ndarray | None, ground_fn, p: dict) -> list[dict]:
    """Poles, signs, streetlights, trees, hydrants from above-ground point clusters.

    Objects are seeded from thin "trunks" (points 0.5-1.8 m above ground), then
    measured in rings around the trunk so a neighbour's canopy can't change the class:
      core   (<0.6 m)  height of the object itself
      arm    (<2.0 m)  horizontal reach at the top (streetlight arm, sign plate)
      canopy (<3.5 m)  foliage centred on this trunk
    """
    hag = xyz[:, 2] - ground_fn(xyz[:, 0], xyz[:, 1])
    m = hag > float(p["object_min_height_m"])
    pts, h = xyz[m], hag[m]
    cols = rgb[m] if rgb is not None else None
    if len(pts) == 0:
        return []
    cell = 0.2
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    iu = ((pts[:, 0] - x0) / cell).astype(int)
    iv = ((pts[:, 1] - y0) / cell).astype(int)
    occ = np.zeros((iu.max() + 1, iv.max() + 1), bool)
    trunk = (h > 0.5) & (h < 1.8)
    occ[iu[trunk], iv[trunk]] = True
    out = []
    for cells in label_components(occ, 8):
        foot = round(float(max(np.ptp(cells[:, 0]), np.ptp(cells[:, 1])) + 1) * cell, 3)
        if foot > 1.2:
            continue  # walls, fences, parked vehicles: not inventoried
        cx = float(x0 + (cells[:, 0].mean() + 0.5) * cell)
        cy = float(y0 + (cells[:, 1].mean() + 0.5) * cell)
        d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        core = d < max(0.6, foot)
        if core.sum() < 30:
            continue
        height = float(np.percentile(h[core], 99.5))
        arm = (d < 2.0) & (h > height - 0.9) & (h < height + 0.5)
        top = pts[arm]
        tspan = float(2 * np.percentile(d[arm], 95)) if arm.sum() > 10 else 0.0
        can = (d < 3.5) & (h > 2.5)
        cspan, coff = 0.0, 99.0
        if can.sum() > 200:
            cp = pts[can]
            coff = float(np.hypot(cp[:, 0].mean() - cx, cp[:, 1].mean() - cy))
            cspan = float(max(np.ptp(cp[:, 0]), np.ptp(cp[:, 1])))
        z_ground = float(ground_fn(np.array([cx]), np.array([cy]))[0])
        ev_base = f"vertical object {height:.1f} m tall, trunk {foot:.2f} m wide"
        metrics = {"height_m": round(height, 2), "trunk_width_m": round(foot, 2), "top_span_m": round(tspan, 2)}
        kind = None
        if cspan > 2.5 and coff < 1.0 and height > 3.0:
            kind, ev = "tree", f"{ev_base}, canopy {cspan:.1f} m wide centred on the trunk"
            height = max(height, float(np.percentile(h[can], 99)))
            metrics["height_m"] = round(height, 2)
            metrics["canopy_m"] = round(cspan, 1)
        elif height >= 8.8 and foot <= 0.6:
            kind, ev = "utility_pole", f"{ev_base}, no arm"
        elif 4.5 <= height < 8.8 and foot <= 0.6:
            if tspan > 1.5:
                kind, ev = "streetlight", f"{ev_base}, arm reaching {tspan / 2:.1f} m"
            else:
                kind, ev = "utility_pole", ev_base
        elif 1.8 <= height < 4.5 and foot <= 0.4:
            plate = (d < 0.8) & (h > height - 0.9)
            pc = cols[plate] if cols is not None else None
            kind = "sign_" + _classify_color(pc)
            ev = f"post {height:.1f} m with a plate {min(tspan, 1.6):.2f} m wide; plate colour suggests '{kind[5:]}'"
            metrics["plate_points"] = int(plate.sum())
        elif 0.4 <= height < 1.5 and foot <= 0.5 and tspan <= 1.0:
            # an isolated short post; a wide top means a bank or verge edge, not an object
            kind, ev = "fire_hydrant", f"short post {height:.2f} m tall"
        if kind is None:
            continue
        obj = core | (arm & (d < 2.0)) | (can if kind == "tree" else np.zeros_like(can))
        op = pts[obj]
        out.append({"type": kind, "severity": None, "source": "geometry", "x": cx, "y": cy,
                    "z": z_ground, "bbox": [float(op[:, 0].min()), float(op[:, 1].min()), z_ground,
                                            float(op[:, 0].max()), float(op[:, 1].max()), z_ground + height],
                    "metrics": metrics, "evidence": ev})
    return out


def decoder_labels(xyz: np.ndarray, labels: np.ndarray, names: dict[int, str]) -> list[dict]:
    """Turn per-point labels from an external decoder into findings (one per 2-D cluster)."""
    out = []
    for lid, code in names.items():
        m = labels == lid
        if m.sum() < 10:
            continue
        p = xyz[m]
        cell = 0.25
        x0, y0 = p[:, 0].min(), p[:, 1].min()
        iu = ((p[:, 0] - x0) / cell).astype(int)
        iv = ((p[:, 1] - y0) / cell).astype(int)
        occ = np.zeros((iu.max() + 1, iv.max() + 1), bool)
        occ[iu, iv] = True
        for cells in label_components(occ, 8):
            sel = np.isin(iu * occ.shape[1] + iv, cells[:, 0] * occ.shape[1] + cells[:, 1])
            q = p[sel]
            if len(q) < 10:
                continue
            out.append({"type": code, "severity": "medium" if code not in ("tree",) else None, "source": "decoder",
                        "x": float(q[:, 0].mean()), "y": float(q[:, 1].mean()), "z": float(q[:, 2].min()),
                        "bbox": _bbox(q[:, 0], q[:, 1], q[:, 2]), "metrics": {"points": int(len(q))},
                        "evidence": f"labelled '{code}' by the decoder ({len(q)} points)"})
    return out

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
        self.s = s
        self.o = o
        self.z = z
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


def _fill_interior_nans(grid: np.ndarray, min_neighbors: int = 4) -> np.ndarray:
    """Fill isolated single-cell NaN gaps that are bracketed on opposite sides by valid cells
    (so gaps inside a depression close without ever dilating the depression outward into empty space)."""
    out = grid.copy()
    nan_m = ~np.isfinite(out)
    if not nan_m.any() or out.shape[0] < 3 or out.shape[1] < 3:
        return out
    pad = np.pad(out, 1, constant_values=np.nan)
    win = np.lib.stride_tricks.sliding_window_view(pad, (3, 3))
    fin = np.isfinite(win)
    valid_cnt = fin.sum(axis=(2, 3))
    bracketed = (fin[:, :, 0, 1] & fin[:, :, 2, 1]) | (fin[:, :, 1, 0] & fin[:, :, 1, 2])
    fill_ok = nan_m & bracketed & (valid_cnt >= min_neighbors)
    if fill_ok.any():
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(win.reshape(out.shape[0], out.shape[1], 9), axis=2)
        out[fill_ok] = med[fill_ok]
    return out


def _refine_depression(
    surf: SegmentSurface,
    s_lo: float,
    s_hi: float,
    o_lo: float,
    o_hi: float,
    z_surf_c: float,
    dmin: float,
    max_depth_lim: float,
) -> dict | None:
    """Refine a detected depression's depth, area, and volume on a local density-adapted fine grid
    referenced to an IRLS road plane fitted on the intact annular ring around the hole."""
    sc = 0.5 * (s_lo + s_hi)
    oc = 0.5 * (o_lo + o_hi)
    span_s = max(s_hi - s_lo, surf.cell)
    span_o = max(o_hi - o_lo, surf.cell)
    dia0 = max(span_s, span_o)
    if dia0 > 2.8:
        return None  # broad road settlement: coarse grid already has hundreds of cells

    pad = max(0.35, 0.70 * dia0)
    hs = 0.5 * span_s + pad
    ho = 0.5 * span_o + pad
    sel = (np.abs(surf.s - sc) <= hs) & (np.abs(surf.o - oc) <= ho)
    if int(sel.sum()) < 40:
        return None
    ps = surf.s[sel]
    po = surf.o[sel]
    pz = surf.z[sel]

    # Points outside the coarse depression box (with small margin) form the intact reference ring
    margin = max(0.05, 0.15 * dia0)
    in_coarse = (ps >= s_lo - margin) & (ps <= s_hi + margin) & (po >= o_lo - margin) & (po <= o_hi + margin)
    ring_pts = (~in_coarse) & (np.abs(pz - z_surf_c) < 0.20)
    if int(ring_pts.sum()) < 25:
        return None

    # Choose local fine cell from actual point density of the depressed points (not diluted by coarse 10 cm box)
    coarse_area = max((span_s + 2 * margin) * (span_o + 2 * margin), 0.01)
    ring_area = max(4.0 * hs * ho - coarse_area, 0.05)
    rho_ring = float(ring_pts.sum()) / ring_area
    dep_pts = in_coarse & (pz < z_surf_c - max(0.008, 0.5 * dmin))
    if int(dep_pts.sum()) >= 20:
        dep_area = max(float(np.ptp(ps[dep_pts])) * float(np.ptp(po[dep_pts])), 1e-4)
        rho_in = float(dep_pts.sum()) / dep_area
    else:
        in_pts = in_coarse & (pz < z_surf_c + 0.20)
        rho_in = float(in_pts.sum()) / coarse_area
    rho_eff = max(rho_in, rho_ring)
    fc_rho = math.sqrt(2.0 / max(rho_eff, 1.0))
    fc = float(np.clip(fc_rho, 0.003, surf.cell))
    nu_f = max(5, int(math.ceil(2.0 * hs / fc)))
    nv_f = max(5, int(math.ceil(2.0 * ho / fc)))
    if nu_f * nv_f > 40_000:
        fc = math.sqrt(4.0 * hs * ho / 40_000.0)
        nu_f = max(5, int(math.ceil(2.0 * hs / fc)))
        nv_f = max(5, int(math.ceil(2.0 * ho / fc)))

    s0_f, o0_f = sc - hs, oc - ho
    # Exclude overhead objects (>0.25 m above road) from the fine surface raster, keep below-road for reflection check
    near_z = pz < z_surf_c + 0.25
    gf = grid_stats(ps[near_z], po[near_z], pz[near_z], fc, s0_f, o0_f, nu_f, nv_f)
    med = gf["median"]
    low = gf["low"]
    cnt = gf["count"]

    st_f = s0_f + (np.arange(nu_f) + 0.5) * fc
    of_f = o0_f + (np.arange(nv_f) + 0.5) * fc
    uu, vv = np.meshgrid(st_f - sc, of_f - oc, indexing="ij")

    coarse_box = (
        (st_f[:, None] >= s_lo - margin) & (st_f[:, None] <= s_hi + margin)
        & (of_f[None, :] >= o_lo - margin) & (of_f[None, :] <= o_hi + margin)
    )
    ring_cells = (~coarse_box) & np.isfinite(med) & (np.abs(med - z_surf_c) < 0.18)
    if int(ring_cells.sum()) < 20:
        return None

    use_quad = dia0 > 0.45
    coef = robust_surface(uu[ring_cells], vv[ring_cells], med[ring_cells], quad=use_quad, c=0.02, iters=6)
    z_ref = (design(uu.ravel(), vv.ravel(), use_quad) @ coef).reshape(nu_f, nv_f)
    r_raw = med - z_ref

    # Estimate intact road surface noise (robust MAD on ring cells)
    ring_res = r_raw[ring_cells]
    sigma_ring = 1.4826 * float(np.median(np.abs(ring_res - np.median(ring_res))))

    # Suppress isolated 1-cell stray-point spikes (count < 3 and >6 cm below local 3x3 median)
    r_clean = r_raw.copy()
    if nu_f >= 3 and nv_f >= 3:
        pad_r = np.pad(r_raw, 1, constant_values=np.nan)
        win_r = np.lib.stride_tricks.sliding_window_view(pad_r, (3, 3)).reshape(nu_f, nv_f, 9)
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            nbr_med = np.nanmedian(win_r, axis=2)
        spike = (cnt < 3) & np.isfinite(r_raw) & np.isfinite(nbr_med) & ((nbr_med - r_raw) > 0.06)
        r_clean[spike] = nbr_med[spike]

    r_fill = _fill_interior_nans(r_clean, min_neighbors=4)
    # Noise-calibrated rim threshold: 3 mm on smooth scans, scales with 2.2x intact asphalt MAD on rough roads
    rim_t = float(np.clip(max(0.003, 2.2 * sigma_ring), 0.003, 0.010))
    inside_seed_box = (
        (st_f[:, None] >= s_lo - fc) & (st_f[:, None] <= s_hi + fc)
        & (of_f[None, :] >= o_lo - fc) & (of_f[None, :] <= o_hi + fc)
    )
    rr = np.nan_to_num(r_fill, nan=0.0)
    seed = inside_seed_box & (rr < -max(0.6 * dmin, rim_t * 1.5))
    if not seed.any():
        return None

    # Grow region; if noise causes bleed to crop border, tighten rim_t up to 0.012 m
    reg = None
    used_rt = rim_t
    for rt in (rim_t, max(rim_t, 0.006), max(rim_t, 0.010), 0.012):
        cand = grow(seed, rr < -rt)
        touches_border = bool(cand[0, :].any() or cand[-1, :].any() or cand[:, 0].any() or cand[:, -1].any())
        if not touches_border:
            reg = cand
            used_rt = rt
            break
    if reg is None or not reg.any():
        return None

    # One-cell sloped-rim step: recover outer sloped wall touching reg without leaking into stone texture (<2.5 mm)
    dil = reg.copy()
    dil[1:, :] |= reg[:-1, :]
    dil[:-1, :] |= reg[1:, :]
    dil[:, 1:] |= reg[:, :-1]
    dil[:, :-1] |= reg[:, 1:]
    rim_add = dil & (~reg) & np.isfinite(r_fill) & (r_fill < -max(0.0025, 0.55 * used_rt))
    reg = reg | rim_add

    # Keep the connected component(s) overlapping the seed (if fragmented by a ridge, keep all seeded comps)
    comps = label_components(reg)
    kept = [comp for comp in comps if seed[comp[:, 0], comp[:, 1]].any()]
    if not kept:
        return None
    fine_cells = np.vstack(kept)
    filled = fill_holes(fine_cells)
    fi, fj = filled[:, 0], filled[:, 1]
    cell_a = fc * fc
    area = float(len(filled)) * cell_a

    # Smoothly interpolate any remaining empty cells strictly inside `filled` via 4-neighbor harmonic relaxation
    r_interp = r_fill.copy()
    filled_mask = np.zeros_like(reg)
    filled_mask[fi, fj] = True
    for _ in range(8):
        miss = filled_mask & (~np.isfinite(r_interp))
        if not miss.any():
            break
        pad_i = np.pad(r_interp, 1, constant_values=np.nan)
        nbrs = np.stack([pad_i[:-2, 1:-1], pad_i[2:, 1:-1], pad_i[1:-1, :-2], pad_i[1:-1, 2:]], axis=-1)
        has_n = np.isfinite(nbrs).any(axis=-1)
        upd = miss & has_n
        if not upd.any():
            break
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            r_interp[upd] = np.nanmean(nbrs[upd], axis=-1)
    rf_vals = r_interp[fi, fj].copy()
    valid_rf = np.isfinite(rf_vals)
    if not valid_rf.any():
        return None
    if not valid_rf.all():
        rf_vals[~valid_rf] = float(np.nanmedian(rf_vals[valid_rf]))
    depths = np.maximum(0.0, -rf_vals)

    # Check water/sky reflection via cell low (25th percentile) on original fine cells
    ci_raw, cj_raw = fine_cells[:, 0], fine_cells[:, 1]
    deep_low = z_ref[ci_raw, cj_raw] - low[ci_raw, cj_raw]
    low_depth = float(np.nanmax(deep_low)) if len(fine_cells) < 10 else float(np.nanpercentile(deep_low, 90))
    unreliable = low_depth > max_depth_lim

    # Unbiased peak depth from cleaned cell medians (avoids both p90 bowl underestimation & p25 noise bias)
    d_valid = depths[valid_rf]
    depth = float(np.nanmax(d_valid)) if len(d_valid) < 15 else float(np.nanpercentile(d_valid, 98))
    depth_med = float(np.median(depths))
    if not unreliable and (depth < dmin or depth_med < 0.25 * dmin):
        return None
    volume = float(np.sum(depths) * cell_a)
    per = perimeter(fine_cells) * fc * (math.pi / 4.0)
    circ = float(min(1.0, 4.0 * math.pi * area / (per * per))) if per > 0 else 0.0
    flat = float(np.mean(np.abs(depths - depth_med) <= 0.25 * depth_med)) if depth_med > 0 else 0.0

    # Bowl shape check on fine cells
    ci_c = fi.astype(float) - fi.mean()
    cj_c = fj.astype(float) - fj.mean()
    rho2 = (ci_c * ci_c + cj_c * cj_c) * fc * fc / max(area / math.pi, 1e-6)
    bowl = 1.0
    if len(depths) >= 8 and depth_med > 0:
        a_ = np.stack([np.ones(len(depths)), rho2], 1)
        (c0, c2), *_ = np.linalg.lstsq(a_, depths, rcond=None)
        bowl = float(-c2 / c0) if c0 > 0 else 1.0

    return {
        "area_m2": area,
        "depth_max_m": depth,
        "depth_median_m": depth_med,
        "volume_m3": volume,
        "unreliable": unreliable,
        "circularity": circ,
        "flat_share": flat,
        "bowl": bowl,
        "s_coords": st_f[fi],
        "o_coords": of_f[fj],
        "z_coords": z_ref[fi, fj] - depths,
        "fine_cell_m": fc,
    }


def _detect_depressions_subgrid(
    surf: SegmentSurface, road: np.ndarray, dmin: float, min_area: float
) -> list[tuple[float, float, float, float, float]]:
    """When `pothole_min_area_m2` is smaller than 2x raster_m (close-range dense scans),
    seed depressions on a Nyquist-matched road sub-grid so small potholes aren't diluted by 10 cm cells.
    Returns list of (s_lo, s_hi, o_lo, o_hi, z_surf_c) boxes."""
    if not road.any():
        return []
    c = surf.cell
    ri, rj = np.nonzero(road)
    s0_sub = surf.s0 + int(ri.min()) * c
    s1_sub = surf.s0 + (int(ri.max()) + 1) * c
    o0_sub = surf.o0 + int(rj.min()) * c
    o1_sub = surf.o0 + (int(rj.max()) + 1) * c
    sel = (surf.s >= s0_sub) & (surf.s < s1_sub) & (surf.o >= o0_sub) & (surf.o < o1_sub)
    if int(sel.sum()) < 200:
        return []
    road_area = float(road.sum()) * c * c
    rho = float(sel.sum()) / max(road_area, 0.1)
    min_diam = 2.0 * math.sqrt(max(min_area, 1e-6) / math.pi)
    dc = float(np.clip(max(math.sqrt(4.0 / max(rho, 1.0)), min_diam / 3.0), 0.012, c))
    if dc >= 0.75 * c:
        return []
    nu_d = max(3, int(math.ceil((s1_sub - s0_sub) / dc)))
    nv_d = max(3, int(math.ceil((o1_sub - o0_sub) / dc)))
    if nu_d * nv_d > 500_000:
        dc = math.sqrt((s1_sub - s0_sub) * (o1_sub - o0_sub) / 500_000.0)
        nu_d = max(3, int(math.ceil((s1_sub - s0_sub) / dc)))
        nv_d = max(3, int(math.ceil((o1_sub - o0_sub) / dc)))

    gd = grid_stats(surf.s[sel], surf.o[sel], surf.z[sel], dc, s0_sub, o0_sub, nu_d, nv_d)
    st_d = s0_sub + (np.arange(nu_d) + 0.5) * dc
    of_d = o0_sub + (np.arange(nv_d) + 0.5) * dc
    # Map coarse road mask & coarse fitted surface onto sub-grid
    ci = np.clip(np.floor((st_d - surf.s0) / c).astype(int), 0, surf.nu - 1)
    cj = np.clip(np.floor((of_d - surf.o0) / c).astype(int), 0, surf.nv - 1)
    road_d = road[ci[:, None], cj[None, :]]
    # Bilinear interpolation of smooth coarse surface onto sub-grid
    fs = np.clip((st_d - surf.stations[0]) / c, 0.0, surf.nu - 1.0001)
    fo = np.clip((of_d - surf.offsets[0]) / c, 0.0, surf.nv - 1.0001)
    i0 = fs.astype(int)
    j0 = fo.astype(int)
    ds = (fs - i0)[:, None]
    do = (fo - j0)[None, :]
    S = surf.surface
    surf_d = (
        (1 - ds) * (1 - do) * S[i0[:, None], j0[None, :]]
        + ds * (1 - do) * S[np.minimum(i0 + 1, surf.nu - 1)[:, None], j0[None, :]]
        + (1 - ds) * do * S[i0[:, None], np.minimum(j0 + 1, surf.nv - 1)[None, :]]
        + ds * do * S[np.minimum(i0 + 1, surf.nu - 1)[:, None], np.minimum(j0 + 1, surf.nv - 1)[None, :]]
    )
    res_d = np.where(road_d & np.isfinite(gd["median"]), gd["median"] - surf_d, np.nan)
    rr = np.nan_to_num(res_d, nan=0.0)
    reg = grow(rr < -dmin, rr < -min(0.008, 0.5 * dmin))
    boxes: list[tuple[float, float, float, float, float]] = []
    for comp in label_components(reg):
        if len(comp) * dc * dc < 0.4 * min_area:
            continue
        s_lo = float(st_d[comp[:, 0].min()] - 0.5 * dc)
        s_hi = float(st_d[comp[:, 0].max()] + 0.5 * dc)
        o_lo = float(of_d[comp[:, 1].min()] - 0.5 * dc)
        o_hi = float(of_d[comp[:, 1].max()] + 0.5 * dc)
        z_c = float(np.nanmedian(surf_d[comp[:, 0], comp[:, 1]]))
        boxes.append((s_lo, s_hi, o_lo, o_hi, z_c))
    return boxes


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

    def _so_to_enu(st: np.ndarray, off: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        k = np.clip((st / step).astype(int), 0, len(path) - 2)
        fwd = path[k + 1] - path[k]
        fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-12
        base = path[k] + fwd * (st - k * step)[:, None]
        left_v = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
        xy = base + left_v * off[:, None]
        return xy[:, 0], xy[:, 1]

    def emit(kind: str, cells: np.ndarray, severity: str | None, metrics_: dict, evidence: str,
             so_coords: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None) -> None:
        if so_coords is not None:
            x, y = _so_to_enu(so_coords[0], so_coords[1])
            zc = so_coords[2]
        else:
            x, y = surf.to_enu(cells[:, 0], cells[:, 1], path, step)
            zc = surface[cells[:, 0], cells[:, 1]] + np.nan_to_num(res[cells[:, 0], cells[:, 1]])
        out.append({"type": kind, "severity": severity, "source": "geometry",
                    "x": float(x.mean()), "y": float(y.mean()), "z": float(np.nanmean(zc)),
                    "bbox": _bbox(x, y, zc), "metrics": metrics_, "evidence": evidence, "segment_id": seg["id"]})

    # --- depressions: potholes, sunken covers, settlements ---------------------
    dmin = float(p["pothole_min_depth_m"])
    min_area = float(p["pothole_min_area_m2"])
    max_depth_lim = float(p.get("pothole_max_depth_m", 0.4))
    min_diam = 2.0 * math.sqrt(max(min_area, 1e-6) / math.pi)
    seeds = np.nan_to_num(res, nan=0) < -dmin
    region = grow(seeds, np.nan_to_num(res, nan=0) < -0.01)
    used = np.zeros_like(region)

    def _emit_depression(cells: np.ndarray, area: float, depth: float, depth_med: float, volume: float,
                         unreliable: bool, circ: float, flat: float, bowl: float,
                         so_coords: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None) -> None:
        dia = 2 * math.sqrt(area / math.pi)
        m = {"area_m2": round(area, 5), "depth_max_m": None if unreliable else round(depth, 4),
             "depth_median_m": round(depth_med, 4), "volume_m3": round(volume, 6), "diameter_m": round(dia, 3),
             "circularity": round(circ, 2), "flat_share": round(flat, 2), "bowl": round(bowl, 2)}
        if unreliable:
            m["depth_unreliable"] = True
        if bowl < 0.25 and flat > 0.7 and circ > 0.7 and 0.15 <= area <= 0.8 and depth_med < 0.06:
            sev = "high" if depth_med >= 0.05 else "medium" if depth_med >= 0.03 else "low"
            emit("manhole_sunken", cells, sev, m,
                 f"flat-floored round recess {depth_med * 100:.1f} cm below the road surface, {dia:.2f} m across (likely a sunken cover; confirm on site)",
                 so_coords=so_coords)
        elif area > 3.0:
            sev = "high" if depth_med >= 0.05 else "medium" if depth_med >= 0.03 else "low"
            emit("depression", cells, sev, m, f"broad depression {area:.1f} m2, median {depth_med * 100:.1f} cm deep",
                 so_coords=so_coords)
        elif unreliable:
            emit("pothole", cells, _severity_pothole(depth_med, dia), m,
                 f"depression {dia:.2f} m across, median {depth_med * 100:.1f} cm deep; its deepest point could not be "
                 "measured (the 3D shows it far below the road, most likely water or a reflection in the hole): measure on site",
                 so_coords=so_coords)
        else:
            emit("pothole", cells, _severity_pothole(depth, dia), m,
                 f"depression {depth * 100:.1f} cm deep, {dia:.2f} m across, {volume * 1000:.1f} L missing material",
                 so_coords=so_coords)

    coarse_boxes_seen: list[tuple[float, float, float, float]] = []
    for cells in label_components(region):
        area_c = len(cells) * cell_area
        if area_c < 0.4 * min_area:
            continue
        s_lo = float(surf.stations[cells[:, 0].min()] - 0.5 * c)
        s_hi = float(surf.stations[cells[:, 0].max()] + 0.5 * c)
        o_lo = float(surf.offsets[cells[:, 1].min()] - 0.5 * c)
        o_hi = float(surf.offsets[cells[:, 1].max()] + 0.5 * c)
        z_surf_c = float(np.nanmedian(surface[cells[:, 0], cells[:, 1]]))
        ref = _refine_depression(surf, s_lo, s_hi, o_lo, o_hi, z_surf_c, dmin, max_depth_lim)
        if ref is not None:
            if ref["area_m2"] < min_area:
                continue
            used[cells[:, 0], cells[:, 1]] = True
            coarse_boxes_seen.append((s_lo, s_hi, o_lo, o_hi))
            _emit_depression(
                cells, ref["area_m2"], ref["depth_max_m"], ref["depth_median_m"], ref["volume_m3"],
                ref["unreliable"], ref["circularity"], ref["flat_share"], ref["bowl"],
                so_coords=(ref["s_coords"], ref["o_coords"], ref["z_coords"]),
            )
            continue

        if area_c < min_area:
            continue
        r = res[cells[:, 0], cells[:, 1]]
        deep = surface[cells[:, 0], cells[:, 1]] - mn[cells[:, 0], cells[:, 1]]
        depth = float(np.nanmax(deep)) if len(cells) < 10 else float(np.nanpercentile(deep, 90))
        depth_med = float(-np.nanmedian(r))
        unreliable = depth > max_depth_lim
        filled_c = fill_holes(cells)
        area_f = len(filled_c) * cell_area
        volume = float(-np.nansum(r) * cell_area)
        per = perimeter(cells) * c * (math.pi / 4)
        circ = float(min(1.0, 4 * math.pi * area_f / (per * per))) if per > 0 else 0.0
        flat = float(np.mean(np.abs(-r - depth_med) <= 0.25 * depth_med)) if depth_med > 0 else 0.0
        ci = cells[:, 0].astype(float) - cells[:, 0].mean()
        cj = cells[:, 1].astype(float) - cells[:, 1].mean()
        rho2 = (ci * ci + cj * cj) * c * c / max(area_c / math.pi, 1e-6)
        ok_r = np.isfinite(r)
        bowl = 1.0
        if ok_r.sum() >= 8 and depth_med > 0:
            a_ = np.stack([np.ones(ok_r.sum()), rho2[ok_r]], 1)
            (c0, c2), *_ = np.linalg.lstsq(a_, -r[ok_r], rcond=None)
            bowl = float(-c2 / c0) if c0 > 0 else 1.0
        used[cells[:, 0], cells[:, 1]] = True
        coarse_boxes_seen.append((s_lo, s_hi, o_lo, o_hi))
        _emit_depression(cells, area_c, depth, depth_med, volume, unreliable, circ, flat, bowl)

    # Sub-grid seeding when requested minimum pothole diameter is below 2x the coarse raster cell
    if min_diam < 2.0 * c:
        for s_lo, s_hi, o_lo, o_hi, z_c in _detect_depressions_subgrid(surf, road, dmin, min_area):
            if any(s_lo <= b[1] and b[0] <= s_hi and o_lo <= b[3] and b[2] <= o_hi for b in coarse_boxes_seen):
                continue
            ref = _refine_depression(surf, s_lo, s_hi, o_lo, o_hi, z_c, dmin, max_depth_lim)
            if ref is None or ref["area_m2"] < min_area:
                continue
            # Mark coarse cells overlapping refined pothole as used so roughness doesn't double-count it
            ci_u = np.clip(np.floor((ref["s_coords"] - surf.s0) / c).astype(int), 0, surf.nu - 1)
            cj_u = np.clip(np.floor((ref["o_coords"] - surf.o0) / c).astype(int), 0, surf.nv - 1)
            used[ci_u, cj_u] = True
            coarse_boxes_seen.append((s_lo, s_hi, o_lo, o_hi))
            dummy_cells = np.column_stack([ci_u, cj_u])
            _emit_depression(
                dummy_cells, ref["area_m2"], ref["depth_max_m"], ref["depth_median_m"], ref["volume_m3"],
                ref["unreliable"], ref["circularity"], ref["flat_share"], ref["bowl"],
                so_coords=(ref["s_coords"], ref["o_coords"], ref["z_coords"]),
            )

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

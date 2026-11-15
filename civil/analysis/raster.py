"""Small numpy-only raster helpers (no SciPy needed)."""

from __future__ import annotations

from collections import deque

import numpy as np


def grid_stats(u: np.ndarray, v: np.ndarray, z: np.ndarray, cell: float,
               u0: float, v0: float, nu: int, nv: int) -> dict[str, np.ndarray]:
    """Per-cell count, min, mean and median of z on a (nu, nv) grid. Empty cells are NaN."""
    iu = np.floor((u - u0) / cell).astype(np.int64)
    iv = np.floor((v - v0) / cell).astype(np.int64)
    ok = (iu >= 0) & (iu < nu) & (iv >= 0) & (iv < nv)
    iu, iv, z = iu[ok], iv[ok], z[ok]
    flat = iu * nv + iv
    order = np.lexsort((z, flat))
    flat, z = flat[order], z[order]
    count = np.bincount(flat, minlength=nu * nv)
    out = {"count": count.reshape(nu, nv)}
    mn = np.full(nu * nv, np.nan)
    md = np.full(nu * nv, np.nan)
    me = np.full(nu * nv, np.nan)
    if len(flat):
        starts = np.r_[0, np.flatnonzero(np.diff(flat)) + 1]
        keys = flat[starts]
        ends = np.r_[starts[1:], len(flat)]
        mn[keys] = z[starts]
        mid = (starts + ends - 1) / 2.0
        md[keys] = (z[np.floor(mid).astype(int)] + z[np.ceil(mid).astype(int)]) / 2
        sums = np.add.reduceat(z, starts)
        me[keys] = sums / (ends - starts)
    out["min"] = mn.reshape(nu, nv)
    out["median"] = md.reshape(nu, nv)
    out["mean"] = me.reshape(nu, nv)
    return out


def label_components(mask: np.ndarray, connectivity: int = 4) -> list[np.ndarray]:
    """Connected components of a boolean 2-D mask -> list of (k,2) index arrays."""
    seen = np.zeros_like(mask, dtype=bool)
    comps: list[np.ndarray] = []
    nu, nv = mask.shape
    if connectivity == 8:
        nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        q = deque([(i0, j0)])
        seen[i0, j0] = True
        cells = []
        while q:
            i, j = q.popleft()
            cells.append((i, j))
            for di, dj in nbrs:
                a, b = i + di, j + dj
                if 0 <= a < nu and 0 <= b < nv and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    q.append((a, b))
        comps.append(np.array(cells))
    return comps


def grow(seed: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """Hysteresis: cells of `allowed` connected (4-neighbour) to `seed`."""
    out = seed & allowed
    while True:
        nxt = out.copy()
        nxt[1:, :] |= out[:-1, :]
        nxt[:-1, :] |= out[1:, :]
        nxt[:, 1:] |= out[:, :-1]
        nxt[:, :-1] |= out[:, 1:]
        nxt &= allowed
        if (nxt == out).all():
            return out
        out = nxt


def fill_holes(cells: np.ndarray) -> np.ndarray:
    """Cells of a component plus any empty cells it fully encloses."""
    i0, j0 = cells.min(0) - 1
    h, w = np.ptp(cells, axis=0) + 3
    m = np.zeros((h, w), bool)
    m[cells[:, 0] - i0, cells[:, 1] - j0] = True
    border = np.zeros_like(m)
    border[[0, -1], :] = True
    border[:, [0, -1]] = True
    outside = grow(border & ~m, ~m)
    filled = np.argwhere(~outside)
    return filled + [i0, j0]


def perimeter(cells: np.ndarray) -> int:
    s = {tuple(c) for c in fill_holes(cells)}
    p = 0
    for i, j in s:
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if (i + di, j + dj) not in s:
                p += 1
    return p


def robust_surface(u: np.ndarray, v: np.ndarray, z: np.ndarray, quad: bool = True,
                   c: float = 0.03, iters: int = 6) -> np.ndarray:
    """IRLS fit (Tukey biweight) of z = f(u, v). Quadratic handles road crown and grade.

    Returns coefficients for design(u, v, quad).
    """
    a = design(u, v, quad)
    w = np.ones(len(z))
    coef = np.zeros(a.shape[1])
    for _ in range(iters):
        sw = np.sqrt(w)
        coef, *_ = np.linalg.lstsq(a * sw[:, None], z * sw, rcond=None)
        r = z - a @ coef
        x = np.clip(np.abs(r) / c, 0, 1)
        w = (1 - x**2) ** 2 + 1e-6
    return coef


def design(u: np.ndarray, v: np.ndarray, quad: bool = True) -> np.ndarray:
    cols = [np.ones_like(u), u, v]
    if quad:
        cols += [u * u, v * v, u * v]
    return np.stack(cols, 1)


def windowed_residual(uu: np.ndarray, vv: np.ndarray, z: np.ndarray, mask: np.ndarray,
                      window_m: float = 0.0, quad: bool = True, min_cells: int = 30) -> tuple:
    """Residual of z against a robust road surface, on a (station, offset) grid.

    window_m = 0: one robust fit over the whole grid (a 25 m segment).
    window_m > 0: robust fits in windows of window_m along the station, half-overlapping,
    blended with triangular weights. Video reconstructions drift (the road can appear to
    bend tens of centimetres over a few metres); a single fit turns that bend into fake
    potholes and heaves, the windowed fit follows it while short dips stay outliers.
    Returns the residual grid (NaN outside the mask); .surface holds the fitted surface.
    """
    res = np.full(z.shape, np.nan)
    m = mask & np.isfinite(z)
    surf = np.zeros(z.shape)
    if m.sum() < min_cells:
        return _with_surface(res, surf)
    s0, s1 = float(uu[m].min()), float(uu[m].max())
    if window_m <= 0 or s1 - s0 <= window_m * 1.25:
        coef = robust_surface(uu[m], vv[m], z[m], quad=quad)
        surf = (design(uu.ravel(), vv.ravel(), quad) @ coef).reshape(z.shape)
    else:
        half = window_m / 2
        n = int(np.ceil((s1 - s0) / half))
        centres = np.linspace(s0 + half, s1 - half, max(2, n))
        acc = np.zeros(z.shape)
        wsum = np.zeros(z.shape)
        for c in centres:
            win = m & (np.abs(uu - c) <= half)
            if win.sum() < min_cells:
                continue
            coef = robust_surface(uu[win] - c, vv[win], z[win], quad=quad)
            w = np.clip(1 - np.abs(uu - c) / half, 0, None) + 1e-9 * (np.abs(uu - c) <= half)
            acc += w * (design((uu - c).ravel(), vv.ravel(), quad) @ coef).reshape(z.shape)
            wsum += w
        ok = wsum > 0
        surf[ok] = acc[ok] / wsum[ok]
        if not ok.all():  # no window covered these cells: fall back to one fit
            coef = robust_surface(uu[m], vv[m], z[m], quad=quad)
            surf[~ok] = (design(uu[~ok], vv[~ok], quad) @ coef)
    res[m] = z[m] - surf[m]
    return _with_surface(res, surf)


class _Residual(np.ndarray):
    surface: np.ndarray


def _with_surface(res: np.ndarray, surf: np.ndarray) -> np.ndarray:
    out = res.view(_Residual)
    out.surface = surf
    return out

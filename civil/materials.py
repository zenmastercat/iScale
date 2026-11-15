"""Materials-only bill of materials for a pothole repair, from its measured size and depth.

No labour, equipment hire, transport, overheads or VAT: only what goes into the hole.
Server defaults are in config/materials.json (sources: Research Desk, 15 Nov 2026,
Shared/Project_CIVIL/research/repair-cost-sources.md); a company admin can override the
prices and the bag size in Settings (stored per company, see `company_overrides`).

Method, after the DOH Road Maintenance Manual (2006) section 2.5-2.6:
  cut a rectangle with vertical edges at least 30 cm into sound pavement on every side,
  down to the bottom of the damage; clean; tack coat the floor and sides (or prime coat
  a new base); place the mix slightly high in layers of at most 5 cm; compact.

Method by depth (thresholds are app settings; DOH gives no number for "reaches the base"):
  small_patch    depth <= max_layer_m        cold mix in one layer
  layered_patch  depth <= base_threshold_m   cold mix in layers of at most max_layer_m
  full_depth     deeper                      crushed-rock base, prime coat, then surface_layer_m of cold mix

Quantities:
  cut          (W + 2 x cut_edge) x (L + 2 x cut_edge), W x L = the measured area
  cold mix     cut area x asphalt depth x 1,944 kg/m3 x (1 + allowance)
  bags         ceil(cold mix / bag weight)
  tack coat    0.30 L/m2 x (cut area + perimeter x asphalt depth)   floor and sides
  prime coat   1.0 L/m2 x cut area                                   full depth only
  base         cut area x (depth - surface layer) x (1 + allowance)  full depth only

Factor F (Thai government overhead, interest, profit and VAT) is deliberately not offered:
it is built to multiply the full direct cost including labour and equipment, so
"materials x Factor F" is not a valid figure (CGD circular ว 481, June 2026).
"""

from __future__ import annotations

import copy
import json
import math

from . import db
from .config import CONFIG_DIR

METHODS = {
    "small_patch": "Small patch, cold mix in one layer",
    "layered_patch": "Patch, cold mix in layers",
    "full_depth": "Deep patch: new base, then cold mix",
}
# what an admin may change from Settings; everything else stays as in the config file
EDITABLE = {"cold_mix": ("price", "bag_kg"), "tack_coat": ("price",), "prime_coat": ("price",), "base": ("price",)}


def defaults() -> dict:
    return json.loads((CONFIG_DIR / "materials.json").read_text())


def company_overrides(company_id: str | None) -> dict:
    return (db.get_setting(company_id, "materials", {}) or {}) if company_id else {}


def config(company_id: str | None = None) -> dict:
    cfg = copy.deepcopy(defaults())
    ov = company_overrides(company_id)
    for key, fields in EDITABLE.items():
        for f in fields:
            v = (ov.get("materials") or {}).get(key, {}).get(f)
            if v is not None:
                cfg["materials"][key][f] = v
                cfg["materials"][key]["source"] = "set by your admin"
    return cfg


def _depth(m: dict) -> float | None:
    d = m.get("depth_max_m")
    if d is None:
        d = m.get("depth_median_m")
    return float(d) if d is not None else None


def _dims(area: float, bbox: list | None) -> tuple[float, float]:
    """Width x length of the damage with the measured area, keeping the defect's own aspect ratio when known."""
    if bbox and len(bbox) == 6:
        w, l = abs(bbox[3] - bbox[0]), abs(bbox[4] - bbox[1])
        if w > 0.05 and l > 0.05:
            k = math.sqrt(area / (w * l))
            return w * k, l * k
    s = math.sqrt(area)
    return s, s


def _ceil(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 4)


def _line(m: dict, qty: float, unit: str, detail: str) -> dict:
    p = m.get("price")
    return {"code": m["code"], "label": m["label"], "label_th": m.get("label_th", ""), "qty": qty, "unit": unit,
            "unit_price": p, "amount": round(qty * float(p), 2) if p else None, "detail": detail, "source": m.get("source", "")}


def bill(metrics: dict | None, cfg: dict | None = None, bbox: list | None = None) -> dict:
    """Bill of materials for one pothole. Returns {"available": False, "reason": ...} without a size."""
    cfg = cfg or defaults()
    m = metrics or {}
    area, depth = m.get("area_m2"), _depth(m)
    if not area or depth is None:
        return {"available": False, "reason": "No size or depth measured yet. Add them to estimate materials.",
                "currency": cfg["currency"], "symbol": cfg["symbol"]}
    area = float(area)
    depth = max(float(depth), float(cfg["min_depth_m"]))
    max_layer, base_thr = float(cfg["max_layer_m"]), float(cfg["base_threshold_m"])
    method = "small_patch" if depth <= max_layer else ("layered_patch" if depth <= base_thr else "full_depth")
    asphalt_d = min(depth, float(cfg["surface_layer_m"])) if method == "full_depth" else depth
    base_d = depth - asphalt_d if method == "full_depth" else 0.0
    edge = float(cfg["cut_edge_m"])
    dw, dl = _dims(area, bbox)
    w, l = dw + 2 * edge, dl + 2 * edge
    cut_area = w * l
    mats = cfg["materials"]

    cm, tc = mats["cold_mix"], mats["tack_coat"]
    mix_kg = cut_area * asphalt_d * float(cm["density_kg_m3"]) * (1 + float(cm["compaction_allowance"]))
    bags = max(1, math.ceil(mix_kg / float(cm["bag_kg"]) - 1e-9))
    tack_area = (0 if method == "full_depth" else cut_area) + 2 * (w + l) * asphalt_d   # deep patch: base is primed instead
    tack_l = max(0.1, _ceil(tack_area * float(tc["rate_l_m2"]), 0.1))
    lines = [
        {"key": "cold_mix", **_line(cm, bags, "bags", f"{bags} × {cm['bag_kg']:g} kg = {bags * cm['bag_kg']:g} kg"
                                    + (f" (needs {mix_kg:.0f} kg)" if bags * cm["bag_kg"] - mix_kg >= 1 else ""))},
        {"key": "tack_coat", **_line(tc, round(tack_l, 1), "L",
                                     f"{tc['rate_l_m2']:g} L/m² on {'the cut sides' if method == 'full_depth' else 'the floor and cut sides'}, {tack_area:.2f} m²")},
    ]
    base_m3 = prime_l = 0.0
    if method == "full_depth":
        pc, bs = mats["prime_coat"], mats["base"]
        prime_l = max(0.1, _ceil(cut_area * float(pc["rate_l_m2"]), 0.1))
        base_m3 = _ceil(cut_area * base_d * (1 + float(bs["compaction_allowance"])), 0.01)
        lines.append({"key": "base", **_line(bs, base_m3, "m³", f"{base_d * 100:.0f} cm under the cold mix")})
        lines.append({"key": "prime_coat", **_line(pc, round(prime_l, 1), "L", f"{pc['rate_l_m2']:g} L/m² on the new base")})
    missing = [ln["label"] for ln in lines if ln["amount"] is None]
    subtotal = round(sum(ln["amount"] or 0 for ln in lines), 2)
    return {
        "available": True, "currency": cfg["currency"], "symbol": cfg["symbol"],
        "method": method, "method_label": METHODS[method],
        "depth_m": round(depth, 3), "area_m2": round(area, 3), "cut_area_m2": round(cut_area, 2),
        "cut_w_m": round(w, 2), "cut_l_m": round(l, 2), "cut_edge_m": edge,
        "asphalt_depth_m": round(asphalt_d, 3), "base_depth_m": round(base_d, 3),
        "layers": max(1, math.ceil(asphalt_d / max_layer - 1e-9)),
        "mix_kg": round(mix_kg, 1), "bags": bags, "tack_l": round(tack_l, 1), "prime_l": round(prime_l, 1), "base_m3": base_m3,
        "lines": lines, "subtotal": subtotal, "materials_cost": subtotal,
        "missing_prices": missing,
        "tools": cfg["tools"][method],
        "excludes": "Labour, equipment hire, transport, overheads and VAT are not included.",
    }


def steps(b: dict, cones_m: int = 30) -> list[str]:
    """Repair steps for this method (DOH manual 2.5-2.6), with this pothole's quantities in them."""
    if not b.get("available"):
        return []
    lay = b["layers"]
    s = [f"Put out signs and traffic cones at least {cones_m} m before the work area.",
         f"Cut a rectangle with vertical edges at least {b['cut_edge_m'] * 100:.0f} cm into sound pavement on every side, "
         f"about {b['cut_w_m']:.1f} × {b['cut_l_m']:.1f} m, down to the bottom of the damage (about {b['depth_m'] * 100:.0f} cm).",
         "Remove loose material and standing water; sweep the hole clean and let it dry."]
    if b["method"] == "full_depth":
        s.append(f"Lay and compact the crushed-rock base ({b['base_m3']:.2f} m³) up to "
                 f"{b['asphalt_depth_m'] * 100:.0f} cm below the road surface.")
        s.append(f"Spray prime coat on the new base ({b['prime_l']:.1f} L) and tack coat on the cut sides ({b['tack_l']:.1f} L).")
    else:
        s.append(f"Spray tack coat ({b['tack_l']:.1f} L) on the floor and the cut sides.")
    s.append(f"Place the cold mix ({b['mix_kg']:.0f} kg, {b['bags']} bags)"
             + (f" in {lay} layers of at most 5 cm, compacting each layer." if lay > 1 else " and compact it."))
    s.append("Leave it slightly above the surrounding road so traffic presses it level; check with a straightedge, "
             "and spread stone dust (2-4 kg/m²) over the cold mix.")
    s.append("Sweep up, take photos for the record, and remove the cones.")
    return s


def save_overrides(company_id: str, body: dict) -> dict:
    ov: dict = {"materials": {}}
    for key, fields in EDITABLE.items():
        for f in fields:
            v = (body.get("materials") or {}).get(key, {}).get(f)
            if v is None:
                continue
            v = float(v)
            if not (0 <= v <= 1_000_000) or (f == "bag_kg" and v <= 0):
                raise ValueError(f"{key}.{f} is out of range")
            ov["materials"].setdefault(key, {})[f] = v
    db.set_setting(company_id, "materials", ov)
    return config(company_id)

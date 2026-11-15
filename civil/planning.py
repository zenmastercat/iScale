"""Repair planning: spot repairs per finding and treatments per segment, with costs.

All rates come from config/unit_costs.json (placeholders until you set real ones).
"""

from __future__ import annotations

import math

from . import catalog
from .config import unit_costs
from .pins import maps_url

SAFETY = {"pothole": 1.6, "sidewalk_trip_hazard": 1.6, "manhole_sunken": 1.3, "heave": 1.2, "depression": 1.1}
OPEN_STATES = {"open", "not_fixed"}


def quantity(f: dict, unit: str, margin: float = 1.3) -> float:
    m = f.get("metrics", {})
    if unit == "m2":
        area = float(m.get("area_m2") or 0.25)
        return area * margin  # saw-cut square around the defect
    if unit == "m":
        if "length_m" in m:
            return float(m["length_m"])
        b = f.get("bbox")
        return float(max(b[3] - b[0], b[4] - b[1])) if b else 1.0
    return 1.0


def price_finding(f: dict, costs: dict | None = None, traffic: dict | None = None) -> dict | None:
    costs = costs or unit_costs()
    it = catalog.CATALOG.get(f["type"])
    if it is None or it.kind != "defect":
        return None
    act = costs["actions"].get(it.action)
    if act is None or act["rate"] == 0:
        return None
    qty = max(quantity(f, act["unit"]), float(act.get("min_qty", 0)))
    cost = qty * float(act["rate"])
    sev = f.get("severity") or "low"
    tf = float((traffic or {}).get("factor") or 1.0)
    priority = catalog.SEVERITY_WEIGHT[sev] * SAFETY.get(f["type"], 1.0) * tf
    return {"finding_id": f["id"], "type": f["type"], "label": it.label, "severity": sev,
            "segment_id": f.get("segment_id"), "action": it.action, "action_label": act["label"],
            "unit": act["unit"], "quantity": round(qty, 2), "rate": act["rate"], "cost": round(cost, 2),
            "priority": round(priority, 2), "traffic_factor": tf, "road": (traffic or {}).get("highway"),
            "lat": f.get("lat"), "lon": f.get("lon"), "maps_url": maps_url(f["lat"], f["lon"]) if f.get("lat") is not None else None}


def spot_plan(findings: list[dict], budget: float | None = None, types: list[str] | None = None,
              ids: list[str] | None = None, traffic_by_segment: dict[str, dict] | None = None) -> dict:
    costs = unit_costs()
    items = []
    for f in findings:
        if f.get("status", "open") not in OPEN_STATES:
            continue
        if types and f["type"] not in types:
            continue
        if ids and f["id"] not in ids:
            continue
        it = price_finding(f, costs, (traffic_by_segment or {}).get(f.get("segment_id")))
        if it:
            items.append(it)
    # highest priority first; cheaper first among equals (more fixes per dollar)
    items.sort(key=lambda i: (-i["priority"], i["cost"]))
    mob = float(costs.get("mobilization_per_order", 0))
    selected, deferred, spent, segs = [], [], 0.0, set()
    for it in items:
        extra = it["cost"] + (mob if it["segment_id"] not in segs else 0.0)
        if budget is None or spent + extra <= budget:
            selected.append(it)
            spent += extra
            segs.add(it["segment_id"])
        else:
            deferred.append(it)
    by_action: dict[str, dict] = {}
    for it in selected:
        a = by_action.setdefault(it["action"], {"action": it["action"], "label": it["action_label"], "unit": it["unit"],
                                                "quantity": 0.0, "cost": 0.0, "count": 0})
        a["quantity"] = round(a["quantity"] + it["quantity"], 2)
        a["cost"] = round(a["cost"] + it["cost"], 2)
        a["count"] += 1
    return {"mode": "spot", "currency": costs.get("currency", "USD"), "budget": budget,
            "items": selected, "deferred": deferred, "by_action": list(by_action.values()),
            "mobilization": round(mob * len(segs), 2), "total": round(spent, 2),
            "note": costs.get("_note", "")}


def segment_plan(segments: list[dict], budget: float | None = None) -> dict:
    costs = unit_costs()
    tr = sorted(((k, v) for k, v in costs["segment_treatments"].items() if not k.startswith("_")),
                key=lambda kv: -kv[1]["min_index"])
    items = []
    for s in segments:
        idx = s.get("condition")
        if idx is None:
            continue
        key, t = next(((k, v) for k, v in tr if idx >= v["min_index"]), tr[-1])
        area = float(s.get("area_m2") or 0)
        cost = area * float(t["rate"])
        # worst first, but preventive work on good roads is cheap and high value per dollar
        tf = float((s.get("traffic") or {}).get("factor") or 1.0)
        urgency = (100 - idx) / 100 * tf
        items.append({"segment_id": s["id"], "condition": idx, "rating": s.get("rating"), "treatment": key,
                      "label": t["label"], "area_m2": round(area, 1), "rate": t["rate"], "cost": round(cost, 2),
                      "urgency": round(urgency, 3), "traffic_factor": tf, "road": (s.get("traffic") or {}).get("highway")})
    items.sort(key=lambda i: -i["urgency"])
    selected, deferred, spent = [], [], 0.0
    for it in items:
        if budget is None or spent + it["cost"] <= budget:
            selected.append(it)
            spent += it["cost"]
        else:
            deferred.append(it)
    return {"mode": "segment", "currency": costs.get("currency", "USD"), "budget": budget,
            "items": selected, "deferred": deferred, "total": round(spent, 2), "note": costs.get("_note", "")}


def round_money(x: float) -> str:
    if x >= 1e6:
        return f"{x / 1e6:.2f}M"
    if x >= 1e4:
        return f"{x / 1e3:.1f}k"
    return f"{math.ceil(x):,}"

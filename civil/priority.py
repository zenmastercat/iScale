"""Routes: traffic for survey segments and pins, and the combined "fix first" ranking."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, catalog, db, jobcard, materials, pins, planning, store, traffic

router = APIRouter(prefix="/api")


class AadtIn(BaseModel):
    aadt: float | None = Field(default=None, ge=0, le=500_000)


def _seg_points(an: dict) -> list[tuple[float, float]]:
    pts = []
    for s in an["segments"]:
        c = s.get("coords") or []
        mid = c[len(c) // 2] if c else None
        pts.append((mid[1], mid[0]) if mid else None)
    return pts


def survey_traffic(pid: str, sid: str, company_id: str) -> dict:
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        pts = _seg_points(an)
        idx = [i for i, p in enumerate(pts) if p]
        aadt = [(an["segments"][i].get("traffic") or {}).get("aadt") for i in idx]
        infos, notes = traffic.assess_points([pts[i] for i in idx], company_id, aadt)
        for i, info in zip(idx, infos):
            an["segments"][i]["traffic"] = traffic.for_storage(info)
        an["traffic_notes"] = notes
        an["traffic_updated"] = time.time()
        store.save_analysis(pid, sid, an)
    return {"segments": {an["segments"][i]["id"]: info for i, info in zip(idx, infos)}, "notes": notes}


@router.post("/projects/{pid}/surveys/{sid}/traffic")
def refresh_survey_traffic(pid: str, sid: str, request: Request):
    me = auth.require(request)
    return survey_traffic(pid, sid, me["company_id"])


@router.patch("/projects/{pid}/surveys/{sid}/segments/{seg}/traffic")
def set_aadt(pid: str, sid: str, seg: str, body: AadtIn, request: Request):
    auth.require(request)
    with store.lock(pid):
        an = store.get_analysis(pid, sid)
        s = next((x for x in an["segments"] if x["id"] == seg), None)
        if s is None:
            raise HTTPException(404, "no such segment")
        t = dict(s.get("traffic") or {"highway": None, "ratio": None})
        t["aadt"] = body.aadt or None
        t["factor"] = traffic.factor(t.get("highway"), t.get("ratio"), t["aadt"])
        t["source"] = "vehicles/day you entered" if t["aadt"] else ("OpenStreetMap road class" if t.get("highway") else "default")
        s["traffic"] = t
        store.save_analysis(pid, sid, an)
    return t


def pin_traffic(pin_ids: list[str], company_id: str) -> None:
    pins.ensure_schema()
    rows = [db.one("SELECT * FROM pins WHERE id=?", i) for i in pin_ids]
    rows = [r for r in rows if r]
    infos, _ = traffic.assess_points([(r["lat"], r["lon"]) for r in rows], company_id)
    for r, info in zip(rows, infos):
        db.run("UPDATE pins SET traffic=? WHERE id=?", json.dumps(traffic.for_storage(info)), r["id"])


@router.post("/pins/traffic")
def refresh_pin_traffic(request: Request):
    me = auth.require(request)
    pin_traffic([p["id"] for p in pins.list_pins("open")], me["company_id"])
    return {"ok": True}


def pin_item(p: dict, cfg: dict | None = None) -> dict:
    t = traffic.live_info(p["lat"], p["lon"], p.get("traffic"))
    tf = float(t.get("factor") or 1.0)
    conf = 1 + 0.25 * min(8, len(p["confirmations"]))  # each "I see it too" adds weight, capped
    prio = catalog.SEVERITY_WEIGHT[p["severity"]] * planning.SAFETY.get(p["type"], 1.0) * tf * conf
    return {"kind": "pin", "id": p["id"], "label": p["label"], "severity": p["severity"], "priority": round(prio, 2),
            "traffic_factor": tf, "road": t.get("highway"), "road_name": t.get("road_name"), "lat": p["lat"], "lon": p["lon"],
            "maps_url": p["maps_url"], "reporter": p["reporter_name"], "confirmations": len(p["confirmations"]),
            "note": p["note"], "created": p["created"],
            "materials": jobcard.cost_summary({"type": p["type"], "metrics": p.get("metrics") or {}}, cfg) if cfg else None}


@router.get("/priority")
def ranking(request: Request, project: str | None = None, survey: str | None = None, limit: int = 100):
    """Which potholes and defects to fix first: survey defects and shared pins in one list."""
    me = auth.require(request)
    items = []
    bbox = None
    cfg = materials.config(me["company_id"])
    if project and survey:
        proj = store.get_project(project)
        if proj.get("company_id") != me["company_id"]:
            raise HTTPException(404, "not found")
        an = store.get_analysis(project, survey)
        pts = dict(zip([s["id"] for s in an["segments"]], _seg_points(an)))
        tbs = {s["id"]: (traffic.live_info(*pts[s["id"]], s["traffic"]) if pts.get(s["id"]) else s["traffic"])
               for s in an["segments"] if s.get("traffic")}
        plan = planning.spot_plan(an["findings"], None, traffic_by_segment=tbs)
        by_id = {f["id"]: f for f in an["findings"]}
        for it in plan["items"] + plan["deferred"]:
            items.append({"kind": "finding", "id": it["finding_id"], "label": it["label"], "severity": it["severity"],
                          "priority": it["priority"], "traffic_factor": it["traffic_factor"], "road": it["road"],
                          "segment_id": it["segment_id"], "lat": it["lat"], "lon": it["lon"], "maps_url": it["maps_url"],
                          "cost": it["cost"], "action": it["action_label"],
                          "materials": jobcard.cost_summary(by_id[it["finding_id"]], cfg)})
        lats = [f["lat"] for f in an["findings"]]
        lons = [f["lon"] for f in an["findings"]]
        if lats:
            bbox = (min(lats) - 0.002, min(lons) - 0.002, max(lats) + 0.002, max(lons) + 0.002)
    for p in pins.list_pins("open", bbox):
        if catalog.CATALOG.get(p["type"]) and catalog.CATALOG[p["type"]].kind == "defect":
            items.append(pin_item(p, cfg))
    items.sort(key=lambda i: -i["priority"])
    for rank, it in enumerate(items, 1):
        it["rank"] = rank
    return {"items": items[:max(1, min(limit, 500))], "formula": "severity x safety x traffic (x confirmations for pins)"}

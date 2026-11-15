"""Traffic weight for deciding which pothole to fix first.

priority = severity weight x safety factor x traffic factor (x confirmations for shared pins)

traffic factor = road weight x congestion
  road weight   from vehicles/day an engineer entered for the segment, else the
                OpenStreetMap road class (motorway 5 ... residential 1.5), else 1
  congestion    Google Maps live travel time / free-flow travel time along the road
                (Routes API, TRAFFIC_AWARE), when a Google Maps key is set; else 1

Outside calls, both optional: OpenStreetMap Overpass (map area of the survey or pin;
cached for a week) and Google Routes (start and end points of each road piece). No chat
data or user data is sent. Admins can switch either off in Settings.

Google's terms don't allow storing Routes results. So congestion is never written to disk:
it is held in this server process's memory for LIVE_TTL seconds (to avoid paying twice for
one refresh) and applied when the "fix first" list is built. What is saved with surveys and
pins is only the OpenStreetMap road class and any vehicles/day an engineer typed in.
Pricing (Nov 2026, Compute Routes Pro): 5,000 requests free per month, then US$10 per 1,000.
"""

from __future__ import annotations

import json
import math
import re
import time

import httpx

from . import db, secrets

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Public mirrors, tried in order when the main server is busy (it often takes 30-40 s).
OVERPASS_MIRRORS = (OVERPASS_URL, "https://overpass.private.coffee/api/interpreter",
                    "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
USER_AGENT = "civil-scan/0.2 (street inspection; self-hosted)"
OSM_TTL = 7 * 86400
LIVE_TTL = 5 * 60
_route_memo: dict[str, tuple[float, dict | None]] = {}   # memory only, never persisted
_live_ratio: dict[tuple[float, float], tuple[float, float]] = {}

ROAD_WEIGHT = {
    "motorway": 5.0, "motorway_link": 4.0, "trunk": 4.5, "trunk_link": 3.5, "primary": 4.0, "primary_link": 3.0,
    "secondary": 3.0, "secondary_link": 2.5, "tertiary": 2.5, "tertiary_link": 2.0, "unclassified": 1.5,
    "residential": 1.5, "living_street": 1.0, "service": 1.0, "busway": 3.0,
    "footway": 1.0, "pedestrian": 1.2, "cycleway": 1.0, "path": 0.8, "track": 0.6,
}


def settings(company_id: str) -> dict:
    s = db.get_setting(company_id, "traffic", {}) or {}
    return {"osm": s.get("osm", True), "google": s.get("google", True)}


def google_key(company_id: str) -> str | None:
    return secrets.get(company_id, "GOOGLE_MAPS_API_KEY")


def _cache_get(key: str, ttl: float):
    r = db.one("SELECT value, fetched FROM traffic_cache WHERE key=?", key)
    if r and time.time() - r["fetched"] < ttl:
        return json.loads(r["value"])
    return None


def _cache_put(key: str, value) -> None:
    db.run("INSERT OR REPLACE INTO traffic_cache(key,value,fetched) VALUES(?,?,?)", key, json.dumps(value), time.time())


def _m(lat1, lon1, lat2, lon2) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * k)


def _seg_dist(p, a, b) -> float:
    """Metres from point p to segment a-b (all (lat, lon))."""
    k = math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * 111_320 * k, (a[0] - p[0]) * 111_320
    bx, by = (b[1] - p[1]) * 111_320 * k, (b[0] - p[0]) * 111_320
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


# --- OpenStreetMap road class -----------------------------------------------------------------
def osm_ways(bbox: tuple[float, float, float, float], client: httpx.Client | None = None) -> list[dict]:
    """Highway ways in (south, west, north, east), with geometry. Cached for a week."""
    s, w, n, e = (round(v, 4) for v in bbox)
    key = f"osm:{s},{w},{n},{e}"
    hit = _cache_get(key, OSM_TTL)
    if hit is not None:
        return hit
    q = f'[out:json][timeout:25];way["highway"]({s},{w},{n},{e});out tags geom;'
    c = client or httpx.Client(timeout=httpx.Timeout(60, connect=10), headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for url in OVERPASS_MIRRORS:
        try:
            r = c.post(url, data={"data": q})
            r.raise_for_status()
            r.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            last = e
    else:
        raise last  # type: ignore[misc]
    ways = [{"id": el["id"], "highway": el.get("tags", {}).get("highway"), "name": el.get("tags", {}).get("name"),
             "geom": [(g["lat"], g["lon"]) for g in el.get("geometry", [])]}
            for el in r.json().get("elements", []) if el.get("type") == "way"]
    _cache_put(key, ways)
    return ways


def nearest_way(lat: float, lon: float, ways: list[dict], max_m: float = 25.0) -> tuple[dict | None, float]:
    best, bd = None, 1e18
    for w in ways:
        g = w["geom"]
        for a, b in zip(g, g[1:]):
            d = _seg_dist((lat, lon), a, b)
            if d < bd:
                best, bd = w, d
    return (best, bd) if bd <= max_m else (None, bd)


def along_way(way: dict, lat: float, lon: float, metres: float = 100.0) -> tuple[tuple, tuple]:
    """Points ~`metres` before and after (lat, lon) along the way (for a Routes request)."""
    g = way["geom"]
    i = min(range(len(g)), key=lambda k: _m(lat, lon, *g[k]))
    a, b, acc = i, i, 0.0
    while a > 0 and acc < metres:
        acc += _m(*g[a - 1], *g[a])
        a -= 1
    acc = 0.0
    while b < len(g) - 1 and acc < metres:
        acc += _m(*g[b], *g[b + 1])
        b += 1
    return g[a], g[b]


# --- Google Maps live congestion --------------------------------------------------------------------
def _secs(v) -> float | None:
    if isinstance(v, str) and re.fullmatch(r"[0-9.]+s", v):
        return float(v[:-1])
    return None


def congestion(origin: tuple, dest: tuple, key: str, client: httpx.Client | None = None) -> dict | None:
    """Live travel time / free-flow travel time between two points, by car (Routes API)."""
    ck = f"routes:{origin[0]:.5f},{origin[1]:.5f}>{dest[0]:.5f},{dest[1]:.5f}"
    hit = _route_memo.get(ck)
    if hit and time.time() - hit[0] < LIVE_TTL:
        return hit[1]
    body = {"origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
            "destination": {"location": {"latLng": {"latitude": dest[0], "longitude": dest[1]}}},
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE"}
    c = client or httpx.Client(timeout=20)
    r = c.post(ROUTES_URL, json=body, headers={"X-Goog-Api-Key": key,
                                                "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters"})
    if r.status_code != 200:
        raise RuntimeError(f"Google Routes API: HTTP {r.status_code}: {r.text[:200]}")
    routes = r.json().get("routes") or []
    if not routes:
        return None
    dur, static = _secs(routes[0].get("duration")), _secs(routes[0].get("staticDuration"))
    if not dur or not static:
        return None
    out = {"ratio": round(dur / static, 3), "duration_s": dur, "static_s": static,
           "distance_m": routes[0].get("distanceMeters"), "fetched": time.time()}
    _route_memo[ck] = (time.time(), out)
    return out


def _pt(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 5), round(lon, 5))


def live_ratio(lat: float, lon: float) -> float | None:
    hit = _live_ratio.get(_pt(lat, lon))
    return hit[1] if hit and time.time() - hit[0] < LIVE_TTL else None


def live_info(lat: float, lon: float, stored: dict | None) -> dict:
    """Stored road info plus Google congestion if it was fetched in the last LIVE_TTL seconds."""
    t = dict(stored or {})
    r = live_ratio(lat, lon)
    t["ratio"] = r
    t["factor"] = factor(t.get("highway"), r, t.get("aadt"))
    if r:
        t["source"] = (t.get("source") or "default") + " + Google live traffic"
    return t


def for_storage(info: dict) -> dict:
    """What may be saved: road class and engineer-entered volume, never Google results."""
    keep = {k: info.get(k) for k in ("highway", "road_name", "aadt")}
    keep["factor"] = factor(keep["highway"], None, keep["aadt"])
    keep["source"] = "vehicles/day you entered" if keep["aadt"] else ("OpenStreetMap road class" if keep["highway"] else "default")
    return keep


# --- combined ---------------------------------------------------------------------------------------------
def road_weight(highway: str | None, aadt: float | None = None) -> float:
    if aadt:
        return round(max(1.0, min(5.0, math.log10(max(aadt, 10.0)))), 2)  # 1,000/day = 3, 100,000/day = 5
    return ROAD_WEIGHT.get(highway or "", 1.0)


def factor(highway: str | None, ratio: float | None, aadt: float | None = None) -> float:
    c = min(3.0, max(1.0, ratio)) if ratio else 1.0
    return round(road_weight(highway, aadt) * (1 + 0.5 * (c - 1)), 2)


def assess_points(points: list[tuple[float, float]], company_id: str, aadt: list[float | None] | None = None) -> tuple[list[dict], list[str]]:
    """Traffic info for each (lat, lon). Returns (infos, notes)."""
    st = settings(company_id)
    notes: list[str] = []
    infos = [{"highway": None, "road_name": None, "ratio": None, "aadt": (aadt or [None] * len(points))[i]} for i in range(len(points))]
    if not points:
        return infos, notes
    ways: list[dict] = []
    if st["osm"]:
        lats, lons = [p[0] for p in points], [p[1] for p in points]
        pad = 0.0006
        try:
            ways = osm_ways((min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad))
        except (httpx.HTTPError, ValueError) as e:
            why = f"HTTP {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else type(e).__name__
            notes.append(f"OpenStreetMap road classes unavailable ({why}; the public Overpass servers are busy, try again later); using equal road weights")
    else:
        notes.append("OpenStreetMap lookup is off in Settings")
    key = google_key(company_id) if st["google"] else None
    if not key:
        notes.append("No Google Maps key: live congestion not included" if st["google"] else "Google traffic is off in Settings")
    gerr = None
    with httpx.Client(timeout=20) as gc:
        for (lat, lon), info in zip(points, infos):
            w, d = nearest_way(lat, lon, ways) if ways else (None, None)
            if w:
                info["highway"], info["road_name"] = w["highway"], w["name"]
            if key and w and len(w["geom"]) >= 2 and gerr is None:
                try:
                    o, t = along_way(w, lat, lon)
                    if _m(*o, *t) >= 40:
                        cg = congestion(o, t, key, gc)
                        if cg:
                            info["ratio"] = cg["ratio"]
                            _live_ratio[_pt(lat, lon)] = (time.time(), cg["ratio"])
                except (httpx.HTTPError, RuntimeError) as e:
                    gerr = str(e)[:200]
    if gerr:
        notes.append(f"Google traffic failed: {gerr}")
    elif key:
        notes.append(f"Google live traffic is used for {LIVE_TTL // 60} minutes and never saved (Google's terms)")
    for info in infos:
        info["factor"] = factor(info["highway"], info["ratio"], info["aadt"])
        info["source"] = "vehicles/day you entered" if info["aadt"] else ("OpenStreetMap road class" if info["highway"] else "default")
        if info["ratio"]:
            info["source"] += " + Google live traffic"
    return infos, notes

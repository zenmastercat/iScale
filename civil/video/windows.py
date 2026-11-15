"""Detection events -> time windows for 3D reconstruction."""

from __future__ import annotations

import math


def events(hit_times: list[float], min_hits: int = 2, hit_gap_s: float = 1.0) -> list[dict]:
    """Group sampled positive times into events; keep events with >= min_hits samples.

    Two hits belong to the same event when they are at most hit_gap_s apart.
    Returns [{t0, t1, t (first confirmed time), hits}].
    """
    ts = sorted(set(round(t, 3) for t in hit_times))
    groups: list[list[float]] = []
    for t in ts:
        if groups and t - groups[-1][-1] <= hit_gap_s:
            groups[-1].append(t)
        else:
            groups.append([t])
    return [{"t0": g[0], "t1": g[-1], "t": g[0], "hits": len(g)} for g in groups if len(g) >= min_hits]


def _split(w: dict, max_s: float) -> list[dict]:
    """Cut a window longer than max_s into pieces of at most max_s, in the gaps between events.

    A road with potholes all along merges into one long window, but LingBot-Map takes a bounded
    number of frames (256 here, 51 s at 5 fps). Each piece becomes its own 3D clip. A cut goes
    midway between the last event that fits and the next one, so no pothole is split; a stretch
    that still doesn't fit (one long run of hits) is cut into equal pieces.
    """
    if w["end"] - w["start"] <= max_s:
        return [w]
    pieces, start, cur = [], w["start"], []
    for e in sorted(w["events"], key=lambda e: e["t0"]):
        if cur and e["t1"] - start > max_s:
            prev = cur[-1]["t1"]
            cut = min((prev + e["t0"]) / 2 if e["t0"] > prev else prev, start + max_s)
            pieces.append({"start": start, "end": cut, "events": cur})
            start, cur = cut, []
        cur.append(e)
    pieces.append({"start": start, "end": w["end"], "events": cur})
    out = []
    for pc in pieces:
        n = math.ceil((pc["end"] - pc["start"]) / max_s - 1e-9)
        if n <= 1:
            out.append(pc)
            continue
        step = (pc["end"] - pc["start"]) / n
        for k in range(n):
            a = pc["start"] + k * step
            b = pc["end"] if k == n - 1 else a + step
            out.append({"start": a, "end": b,
                        "events": [e for e in pc["events"] if (a <= e["t0"] < b) or (k == n - 1 and e["t0"] >= b)]})
    return out


def windows(evts: list[dict], duration: float, before_s: float = 10, after_s: float = 10,
            merge_gap_s: float = 0, max_s: float = 0) -> list[dict]:
    """[event.t0 - before, event.t1 + after], clamped to the video, overlapping ones merged,
    then (max_s > 0) cut so no window is longer than max_s seconds."""
    raw = sorted((max(0.0, e["t0"] - before_s), min(duration, e["t1"] + after_s), e) for e in evts)
    out: list[dict] = []
    for a, b, e in raw:
        if out and a <= out[-1]["end"] + merge_gap_s:
            out[-1]["end"] = max(out[-1]["end"], b)
            out[-1]["events"].append(e)
        else:
            out.append({"start": a, "end": b, "events": [e]})
    if max_s and max_s > 0:
        out = [piece for w in out for piece in _split(w, max_s)]
    for i, w in enumerate(out):
        w["index"] = i
        w["start"] = round(w["start"], 3)
        w["end"] = round(w["end"], 3)
    return out

"""Detection events -> time windows for 3D reconstruction."""

from __future__ import annotations


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


def windows(evts: list[dict], duration: float, before_s: float = 10, after_s: float = 10,
            merge_gap_s: float = 0) -> list[dict]:
    """[event.t0 - before, event.t1 + after], clamped to the video, overlapping ones merged."""
    raw = sorted((max(0.0, e["t0"] - before_s), min(duration, e["t1"] + after_s), e) for e in evts)
    out: list[dict] = []
    for a, b, e in raw:
        if out and a <= out[-1]["end"] + merge_gap_s:
            out[-1]["end"] = max(out[-1]["end"], b)
            out[-1]["events"].append(e)
        else:
            out.append({"start": a, "end": b, "events": [e]})
    for i, w in enumerate(out):
        w["index"] = i
        w["start"] = round(w["start"], 3)
        w["end"] = round(w["end"], 3)
    return out

"""Decode -> align -> analyse one survey, updating its status as it goes."""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import store
from .align import align
from .analysis import analyze
from .decoders import DecoderError, get_decoder
from .pointcloud import Reconstruction, enu_to_latlon

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="survey")


def submit(pid: str, sid: str):
    return _executor.submit(run_survey, pid, sid)


def _finalize_findings(findings: list[dict], lat0: float, lon0: float, prefix: str) -> None:
    for i, f in enumerate(findings):
        f["id"] = f"{prefix}{i + 1:04d}"
        lat, lon = enu_to_latlon(np.array([f["x"]]), np.array([f["y"]]), lat0, lon0)
        f["lat"], f["lon"] = float(lat[0]), float(lon[0])
        f.setdefault("status", "open")
        f.setdefault("history", [])


def _segments_to_geo(segs: list[dict], lat0: float, lon0: float) -> None:
    for s in segs:
        line = np.array(s["line"])
        lat, lon = enu_to_latlon(line[:, 0], line[:, 1], lat0, lon0)
        s["coords"] = [[float(a), float(b)] for a, b in zip(lon, lat)]


def run_survey(pid: str, sid: str) -> None:
    try:
        proj = store.get_project(pid)
        sv = store.update_survey(pid, sid, status="running", stage="decoding", error=None)
        d = store.survey_dir(pid, sid)
        if sv["decoder"] == "pothole_video":
            from .video.job import run_video_job

            store.update_survey(pid, sid, stage="detecting")
            stats = run_video_job(pid, sid, lambda msg: store.update_survey(pid, sid, stage=msg))
            store.update_survey(pid, sid, status="done", stage="", stats=stats, kind="video")
            return
        from .worker import WAITING, takes

        if takes(sv["decoder"]):  # this server hands 3D work to a GPU worker (civil/worker.py)
            store.update_survey(pid, sid, status="queued", stage=WAITING, error=None)
            return
        dec = get_decoder(sv["decoder"])
        params = dict(sv.get("params") or {})
        params.setdefault("origin_lat", proj["origin_lat"])
        params.setdefault("origin_lon", proj["origin_lon"])
        rec: Reconstruction = dec.decode(d / "input", d / "work", params)
        store.update_survey(pid, sid, stage="aligning")
        notes = align(rec, proj["origin_lat"], proj["origin_lon"], params)
        rec.save(store.recon_path(pid, sid))
        store.update_survey(pid, sid, stage="analysing", notes=notes)
        an = analyze(rec, params.get("analysis"))
        prefix = "F" + sid[:3].upper() + "-"
        _finalize_findings(an["findings"], proj["origin_lat"], proj["origin_lon"], prefix)
        _segments_to_geo(an["segments"], proj["origin_lat"], proj["origin_lon"])
        an["survey_id"] = sid
        store.save_analysis(pid, sid, an)
        stats = {"points": rec.n, "findings": len(an["findings"]), "segments": len(an["segments"]),
                 "length_m": round(sum(s["length_m"] for s in an["segments"]), 1),
                 "analysis_s": an["seconds"]}
        with store.lock(pid):
            proj = store.get_project(pid)
            if not proj.get("baseline") or store.get_survey(pid, proj["baseline"]).get("kind") == "video":
                proj["baseline"] = sid
                store.save_project(proj)
        store.update_survey(pid, sid, status="done", stage="", stats=stats)
    except (DecoderError, ValueError, KeyError, OSError) as e:
        store.update_survey(pid, sid, status="error", stage="", error=str(e))
    except Exception as e:  # keep the worker alive, record the failure
        store.update_survey(pid, sid, status="error", stage="", error=f"{type(e).__name__}: {e}",
                            trace=traceback.format_exc()[-4000:])

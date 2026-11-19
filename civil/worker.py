"""Remote 3D worker: the web server queues the heavy 3D work, a GPU computer does it.

When iScale runs on a small always-on box (for example a CasaOS home server) and LingBot-Map
needs a GPU elsewhere, set CIVIL_3D=remote and CIVIL_WORKER_TOKEN on the server. Then:

  server  a lingbot_clip survey (or any decoder in REMOTE_DECODERS) is not decoded locally; it
          waits with stage "waiting for the 3D worker". Pothole detection on the drive video
          still runs on the server (it calls Roboflow's servers, so it is light).
  worker  `civil worker --server URL --token-file FILE` on the GPU computer asks for the next
          job, downloads its input (clip frames, the detector's boxes, gps.csv), runs the normal
          pipeline locally (LingBot-Map -> align -> analyse) in its own data folder with the same
          project and survey ids, and uploads recon.npz and analysis.json back.

A job the worker claimed but did not finish within LEASE_S goes back to the queue, so a worker
that crashes or is switched off loses nothing. Only outbound requests come from the worker, so the
GPU computer needs no open ports. The token travels as a bearer header; use HTTPS (or the home
network) between the two.
"""

from __future__ import annotations

import hmac
import io
import json
import os
import shutil
import tarfile
import threading
import time

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from . import store

router = APIRouter(prefix="/api/worker")

REMOTE_DECODERS = {"lingbot_clip"}
WAITING = "waiting for the 3D worker"
LEASE_S = 3 * 3600
MAX_RESULT_BYTES = 2 * 1024 ** 3


_doing_job = threading.local()  # set while this process is the worker running a job: then decode here


def remote_enabled() -> bool:
    return os.environ.get("CIVIL_3D", "local").lower() == "remote" and not getattr(_doing_job, "on", False)


def takes(decoder: str) -> bool:
    """True when this server hands surveys with this decoder to a worker instead of decoding them."""
    return remote_enabled() and decoder in REMOTE_DECODERS


def _auth(request: Request) -> None:
    want = os.environ.get("CIVIL_WORKER_TOKEN", "")
    got = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not want or len(want) < 24:
        raise HTTPException(503, "no 3D worker is configured on this server (set CIVIL_WORKER_TOKEN)")
    if not hmac.compare_digest(got.encode(), want.encode()):
        raise HTTPException(401, "bad worker token")


def _all_surveys():
    for p in store.list_projects():
        for sv in store.list_surveys(p["id"]):
            yield p, sv


def _requeue_stale() -> None:
    now = time.time()
    for p, sv in _all_surveys():
        lease = sv.get("lease") or {}
        if sv.get("status") == "running" and lease and now - lease.get("at", 0) > LEASE_S:
            store.update_survey(p["id"], sv["id"], status="queued", stage=WAITING, lease=None)


@router.get("/next")
def next_job(request: Request, worker: str = "worker"):
    """Claim the oldest waiting job, or 204 when there is none."""
    _auth(request)
    _requeue_stale()
    waiting = [(sv["created"], p, sv) for p, sv in _all_surveys()
               if sv.get("status") == "queued" and sv.get("decoder") in REMOTE_DECODERS]
    if not waiting:
        return Response(status_code=204)
    _, p, sv = min(waiting, key=lambda t: t[0])
    with store.lock(p["id"]):
        cur = store.get_survey(p["id"], sv["id"])
        if cur.get("status") != "queued":  # another worker took it a moment ago
            return Response(status_code=204)
        store.update_survey(p["id"], sv["id"], status="running", stage="3D on the worker",
                            lease={"worker": worker[:60], "at": time.time()})
    return {"project": {k: p[k] for k in ("id", "name", "origin_lat", "origin_lon")},
            "survey": {k: sv.get(k) for k in ("id", "name", "decoder", "params", "created")}}


def _claimed(pid: str, sid: str) -> dict:
    sv = store.get_survey(store.check_id(pid), store.check_id(sid))
    if sv.get("status") != "running" or not sv.get("lease"):
        raise HTTPException(409, "this job is not claimed by a worker (it may have been re-queued)")
    return sv


@router.get("/jobs/{pid}/{sid}/input")
def job_input(pid: str, sid: str, request: Request):
    """The survey's input folder as a .tar (frames, boxes.json, gps.csv)."""
    _auth(request)
    _claimed(pid, sid)
    src = store.survey_dir(pid, sid) / "input"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(src, arcname="input")
    return Response(buf.getvalue(), media_type="application/x-tar")


@router.post("/jobs/{pid}/{sid}/stage")
def job_stage(pid: str, sid: str, request: Request, stage: str = Form(..., max_length=200)):
    _auth(request)
    sv = _claimed(pid, sid)
    store.update_survey(pid, sid, stage=f"3D on the worker: {stage}", lease={**sv["lease"], "at": time.time()})
    return {"ok": True}


@router.post("/jobs/{pid}/{sid}/fail")
def job_fail(pid: str, sid: str, request: Request, error: str = Form(..., max_length=4000)):
    _auth(request)
    _claimed(pid, sid)
    store.update_survey(pid, sid, status="error", stage="", error=f"3D worker: {error}", lease=None)
    return {"ok": True}


@router.post("/jobs/{pid}/{sid}/result")
async def job_result(pid: str, sid: str, request: Request, recon: UploadFile = File(...),
                     analysis: UploadFile = File(...), meta: str = Form("{}")):
    """recon.npz + analysis.json from the worker; the survey becomes done on this server."""
    _auth(request)
    _claimed(pid, sid)
    try:
        info = json.loads(meta or "{}")
        an = json.loads((await analysis.read()).decode())
        assert isinstance(an, dict) and isinstance(an.get("findings"), list) and an.get("survey_id") == sid
    except (ValueError, AssertionError):
        raise HTTPException(400, "the analysis is not valid for this survey")
    tmp = store.recon_path(pid, sid).with_suffix(".upload")
    total = 0
    with open(tmp, "wb") as out:
        while chunk := await recon.read(1 << 20):
            total += len(chunk)
            if total > MAX_RESULT_BYTES:
                out.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "point cloud too large")
            out.write(chunk)
    try:
        from .pointcloud import Reconstruction

        Reconstruction.load(tmp)  # refuse a broken file before it replaces anything
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"the point cloud could not be read: {e}")
    tmp.replace(store.recon_path(pid, sid))
    store.save_analysis(pid, sid, an)
    with store.lock(pid):
        proj = store.get_project(pid)
        if not proj.get("baseline") or store.get_survey(pid, proj["baseline"]).get("kind") == "video":
            proj["baseline"] = sid
            store.save_project(proj)
    store.update_survey(pid, sid, status="done", stage="", lease=None,
                        notes=list(info.get("notes") or [])[:50], stats=dict(info.get("stats") or {}))
    return {"ok": True}


# --- the worker loop (runs on the GPU computer) -------------------------------------------------
def run_worker(server: str, token: str, poll_s: float = 15.0, once: bool = False, name: str = "") -> None:
    """Poll the server for 3D jobs and run them here. CIVIL_DATA_DIR should point to a folder
    used only by the worker: jobs are rebuilt there with the server's ids, then uploaded."""
    import httpx

    from . import pipeline
    from .config import DATA_DIR

    name = name or os.uname().nodename
    h = {"Authorization": f"Bearer {token}", "X-Civil-Scan": "1"}
    server = server.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(60.0, read=600.0, write=600.0), headers=h) as c:
        print(f"3D worker {name}: polling {server} every {poll_s:g} s; data in {DATA_DIR}", flush=True)
        while True:
            try:
                r = c.get(f"{server}/api/worker/next", params={"worker": name})
                if r.status_code == 204:
                    if once:
                        return
                    time.sleep(poll_s)
                    continue
                r.raise_for_status()
                job = r.json()
            except httpx.HTTPError as e:
                print(f"server not reachable: {e}", flush=True)
                if once:
                    return
                time.sleep(poll_s)
                continue
            _run_one(c, server, job, pipeline)
            if once:
                return


def _run_one(c, server: str, job: dict, pipeline) -> None:
    p, s = job["project"], job["survey"]
    pid, sid = store.check_id(p["id"]), store.check_id(s["id"])
    base = f"{server}/api/worker/jobs/{pid}/{sid}"
    print(f"job {s['name']} ({pid}/{sid})", flush=True)
    try:
        # rebuild the project and survey here with the server's ids
        pdir = store.project_dir(pid)
        if pdir.exists():
            shutil.rmtree(pdir)
        (pdir / "surveys").mkdir(parents=True)
        store._write_json(pdir / "project.json", {**p, "surveys": [sid], "created": time.time()})
        sdir = store.survey_dir(pid, sid)
        (sdir / "work").mkdir(parents=True)
        store._write_json(sdir / "survey.json", {**s, "project_id": pid, "status": "queued", "stage": "", "error": None,
                                                  "notes": [], "stats": {}})
        r = c.get(f"{base}/input")
        r.raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r") as tar:
            tar.extractall(sdir, filter="data")  # refuses absolute paths and links outside the folder
        c.post(f"{base}/stage", data={"stage": "LingBot-Map 3D"})
        _doing_job.on = True
        try:
            pipeline.run_survey(pid, sid)
        finally:
            _doing_job.on = False
        done = store.get_survey(pid, sid)
        if done["status"] != "done":
            c.post(f"{base}/fail", data={"error": done.get("error") or "unknown error"})
            print(f"  failed: {done.get('error')}", flush=True)
            return
        c.post(f"{base}/stage", data={"stage": "uploading the 3D result"})
        with open(store.recon_path(pid, sid), "rb") as rf, open(sdir / "analysis.json", "rb") as af:
            r = c.post(f"{base}/result", files={"recon": ("recon.npz", rf, "application/octet-stream"),
                                                "analysis": ("analysis.json", af, "application/json")},
                       data={"meta": json.dumps({"notes": done.get("notes"), "stats": done.get("stats")})})
        r.raise_for_status()
        print(f"  done: {done.get('stats')}", flush=True)
    except Exception as e:  # noqa: BLE001 - report and keep the worker alive
        print(f"  error: {type(e).__name__}: {e}", flush=True)
        try:
            c.post(f"{base}/fail", data={"error": f"{type(e).__name__}: {e}"[:3900]})
        except Exception:  # noqa: BLE001
            pass
    finally:
        shutil.rmtree(store.project_dir(pid), ignore_errors=True)  # the server keeps the result


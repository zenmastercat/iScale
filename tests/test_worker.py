"""Remote 3D worker: the server queues 3D jobs, a GPU computer claims, runs and returns them."""

import json
import time

import numpy as np
import pytest

from civil import store, worker
from civil.decoders.demo import DemoDecoder
from civil.pointcloud import write_ply

from helpers import admin

TOKEN = "t" * 40


class ServerSide:
    """The worker's HTTP client, pointed at the in-process server. The server and the worker keep
    separate data folders (as on two computers): every request switches the store to the server's."""

    def __init__(self, client, server_dir, worker_dir, token=TOKEN):
        self.c, self.s, self.w = client, server_dir, worker_dir
        self.h = {"Authorization": f"Bearer {token}", "X-Civil-Scan": "1"}

    def _call(self, method, url, **kw):
        prev, store.DATA_DIR = store.DATA_DIR, self.s
        try:
            return getattr(self.c, method)(url, headers=self.h, **kw)
        finally:
            store.DATA_DIR = prev

    def get(self, url, **kw):
        return self._call("get", url, **kw)

    def post(self, url, **kw):
        return self._call("post", url, **kw)


@pytest.fixture
def remote(monkeypatch, tmp_path):
    monkeypatch.setenv("CIVIL_3D", "remote")
    monkeypatch.setenv("CIVIL_WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(worker, "REMOTE_DECODERS", {"ply_import"})  # stands in for lingbot_clip (needs a GPU)
    server_dir = store.DATA_DIR
    wdir = tmp_path / "worker-data"
    wdir.mkdir()
    yield server_dir, wdir
    store.DATA_DIR = server_dir


def claim(c, sid):
    """Claim jobs until this test's own job comes up (earlier tests may have left theirs queued)."""
    for _ in range(20):
        r = c.get("/api/worker/next", params={"worker": "test-gpu"})
        assert r.status_code == 200, r.status_code
        job = r.json()
        if job["survey"]["id"] == sid:
            return job
        c.post(f"/api/worker/jobs/{job['project']['id']}/{job['survey']['id']}/fail", data={"error": "test cleanup"})
    raise AssertionError("job never came up")


def _queued_survey(tmp_path):
    rec = DemoDecoder().decode(tmp_path, tmp_path, {})
    write_ply(tmp_path / "points.ply", rec.points.astype("f4"), rec.colors)
    (tmp_path / "poses.json").write_text(json.dumps({"poses": rec.poses.tolist(), "times": rec.times.tolist()}))
    a = admin()
    proj = a.post("/api/projects", json={"name": "remote 3D", "origin_lat": 13.8196, "origin_lon": 100.5137}).json()
    files = [("files", (n, open(tmp_path / n, "rb"))) for n in ("points.ply", "poses.json")]
    sv = a.post(f"/api/projects/{proj['id']}/surveys", data={"name": "clip", "decoder": "ply_import",
                "params": json.dumps({"up_axis": "auto", "metric": True})}, files=files).json()
    for _ in range(100):
        st = a.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}").json()
        if st["stage"] == worker.WAITING:
            break
        time.sleep(0.1)
    return a, proj["id"], sv["id"], st


def test_the_server_queues_3d_work_instead_of_doing_it(remote, tmp_path):
    a, pid, sid, st = _queued_survey(tmp_path)
    assert st["status"] == "queued" and st["stage"] == worker.WAITING
    assert not store.recon_path(pid, sid).exists()


def test_a_worker_needs_the_token(remote, tmp_path):
    a = admin()
    assert a.get("/api/worker/next").status_code == 401  # a signed-in person is not a worker
    assert a.get("/api/worker/next", headers={"Authorization": "Bearer wrong" + "x" * 30}).status_code == 401


def test_the_worker_runs_the_job_and_the_server_gets_the_result(remote, tmp_path):
    server_dir, wdir = remote
    a, pid, sid, _ = _queued_survey(tmp_path)
    from fastapi.testclient import TestClient

    from civil import pipeline
    from civil.api import app

    c = ServerSide(TestClient(app), server_dir, wdir)
    job = claim(c, sid)
    assert c.get("/api/worker/next").status_code == 204  # claimed: nobody else gets it
    store.DATA_DIR = wdir
    worker._run_one(c, "", job, pipeline)
    store.DATA_DIR = server_dir
    st = a.get(f"/api/projects/{pid}/surveys/{sid}").json()
    assert st["status"] == "done" and st["stats"]["findings"] > 0, st
    an = a.get(f"/api/projects/{pid}/surveys/{sid}/analysis").json()
    assert sum(f["type"] == "pothole" for f in an["findings"]) == 5  # the demo street's planted potholes
    assert a.get(f"/api/projects/{pid}/surveys/{sid}/points.bin?max_points=10000").status_code == 200
    assert not (wdir / "projects" / pid).exists()  # the worker keeps no copy


def test_a_stale_job_goes_back_to_the_queue(remote, tmp_path, monkeypatch):
    server_dir, wdir = remote
    a, pid, sid, _ = _queued_survey(tmp_path)
    from fastapi.testclient import TestClient

    from civil.api import app

    c = ServerSide(TestClient(app), server_dir, wdir)
    claim(c, sid)
    monkeypatch.setattr(worker, "LEASE_S", -1)  # as if the worker vanished hours ago
    again = c.get("/api/worker/next").json()
    assert again["survey"]["id"] == sid


def test_a_failed_job_is_reported(remote, tmp_path):
    server_dir, wdir = remote
    a, pid, sid, _ = _queued_survey(tmp_path)
    from fastapi.testclient import TestClient

    from civil.api import app

    c = ServerSide(TestClient(app), server_dir, wdir)
    claim(c, sid)
    assert c.post(f"/api/worker/jobs/{pid}/{sid}/fail", data={"error": "CUDA out of memory"}).status_code == 200
    st = a.get(f"/api/projects/{pid}/surveys/{sid}").json()
    assert st["status"] == "error" and "CUDA out of memory" in st["error"]
    # a result for a job that is no longer claimed is refused
    r = c.post(f"/api/worker/jobs/{pid}/{sid}/result", files={"recon": ("r.npz", b"x"), "analysis": ("a.json", b"{}")})
    assert r.status_code == 409


def test_a_server_without_lingbot_accepts_drive_videos_when_a_worker_does_the_3d(monkeypatch):
    """The CasaOS box has no GPU and no LingBot-Map install; with CIVIL_3D=remote it must still take videos."""
    from civil.decoders import lingbot_clip as lc

    cfg = lc._video_cfg()
    cfg["lingbot"] = {**cfg["lingbot"], "python": "/nonexistent/python"}
    monkeypatch.setattr(lc, "_video_cfg", lambda: cfg)
    monkeypatch.setenv(cfg["detector"].get("api_key_env", "ROBOFLOW_API_KEY"), "test-key")
    monkeypatch.setenv("CIVIL_3D", "local")
    assert lc.PotholeVideoDecoder().available()[0] is False   # local 3D: LingBot-Map must be here
    monkeypatch.setenv("CIVIL_3D", "remote")
    assert lc.PotholeVideoDecoder().available() == (True, "")
    assert lc.LingbotClipDecoder().available() == (True, "")
    worker._doing_job.on = True                                # but the worker itself still needs it
    try:
        assert lc.LingbotClipDecoder().available()[0] is False
    finally:
        worker._doing_job.on = False

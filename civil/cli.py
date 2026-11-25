"""iScale command line (the command is still `civil`).

  civil serve [--host 127.0.0.1] [--port 8765]     run the web app
  civil demo                                        build the demo project (no server)
  civil decoders                                    list decoders and whether they can run
  civil worker --server URL --token-file FILE       do a remote server's 3D jobs on this (GPU) computer
  civil calibrate VIDEO [--t 5] [--src x,y x,y x,y x,y] [--width-m 3.5 --length-m 12 --near-m 4] [--save]
        draw the road-plane calibration on a frame and write a bird's-eye preview;
        --src takes the 4 road corners as fractions of the frame (TL BL BR TR);
        --save stores them in config/video.json
"""

from __future__ import annotations

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser(prog="civil", description="Street-scan inspection platform")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1", help="bind address (default: this computer only)")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo")
    sub.add_parser("decoders")
    w = sub.add_parser("worker", help="run 3D jobs for a server that has CIVIL_3D=remote")
    w.add_argument("--server", required=True, help="the iScale server, for example http://192.168.1.135:8765")
    w.add_argument("--token-file", required=True, help="file holding the server's CIVIL_WORKER_TOKEN")
    w.add_argument("--poll", type=float, default=15.0, help="seconds between checks when there is no job")
    w.add_argument("--once", action="store_true", help="do at most one job, then exit")
    c = sub.add_parser("calibrate")
    c.add_argument("video")
    c.add_argument("--t", type=float, default=5.0, help="time of the frame to use (s)")
    c.add_argument("--src", nargs=4, help="4 points x,y as fractions: top-left bottom-left bottom-right top-right")
    c.add_argument("--width-m", type=float)
    c.add_argument("--length-m", type=float)
    c.add_argument("--near-m", type=float)
    c.add_argument("--out", default="calibration")
    c.add_argument("--save", action="store_true")
    fg = sub.add_parser("forge", help="FORGE SLAM pre-flight check, standalone run, or benchmark evaluation")
    fg_sub = fg.add_subparsers(dest="forge_cmd", required=True)
    fg_chk = fg_sub.add_parser("check", help="validate a multi-sensor sequence directory or bag")
    fg_chk.add_argument("input", help="path to FORGE sequence folder or ROS bag")
    fg_run = fg_sub.add_parser("run", help="run FORGE SLAM standalone on an input folder")
    fg_run.add_argument("input", help="path to FORGE sequence folder")
    fg_run.add_argument("--work", required=True, help="working directory for tiles, diagnostics, and recon.npz")
    fg_eval = fg_sub.add_parser("eval", help="synthetic sanity check of loop closure + pose graph (simulated scans on M2DGR GT paths; JSON only)")
    fg_eval.add_argument("--datasets-dir", default="", help="override path to iScale-datasets directory")
    fg_real = fg_sub.add_parser("eval-real", help="evaluate on recorded public data (M2DGR bag and/or STheReO folder)")
    fg_real.add_argument("--m2dgr-bag", default="", help="M2DGR .bag file")
    fg_real.add_argument("--m2dgr-gt", default="", help="matching M2DGR ground truth (TUM, ECEF)")
    fg_real.add_argument("--sthereo", default="", help="STheReO sequence folder (sensor_data/, image/, calibration/)")
    fg_real.add_argument("--out", required=True, help="output folder for reports, trajectories and maps")
    fg_real.add_argument("--figures", default="", help="folder for M2DGR figures (STheReO figures stay in --out)")
    bp = sub.add_parser("bench-potholes", help="benchmark pothole depth/area/volume accuracy on real-GT and synthetic suites")
    bp.add_argument("--suites", nargs="+", default=["synth-forge-dev"], help="suites to run")
    bp.add_argument("--datasets-dir", default="", help="path to pothole datasets directory")
    bp.add_argument("--out", default="", help="optional JSON output file")
    a = ap.parse_args()
    if a.cmd == "serve":
        import uvicorn

        import os

        from . import xmpp

        chat = os.environ.get("CIVIL_XMPP", "on") != "off"
        if chat:
            print(xmpp.start(), flush=True)
            if xmpp.running():
                from . import groups

                print(f"XMPP: {groups.sync_all_rooms()} group rooms in step", flush=True)
        try:
            uvicorn.run("civil.api:app", host=a.host, port=a.port, log_level="info")
        finally:
            if chat:
                xmpp.stop()
    elif a.cmd == "demo":
        from . import pipeline, store
        from .config import DEFAULT_ORIGIN

        proj = store.create_project("Demo district (synthetic)", *DEFAULT_ORIGIN)
        for name, rep in (("Baseline drive", False), ("After repairs", True)):
            sv = store.create_survey(proj["id"], name, "demo", {"repaired": rep})
            pipeline.run_survey(proj["id"], sv["id"])
            print(json.dumps(store.get_survey(proj["id"], sv["id"]), indent=1))
        print("project", proj["id"])
    elif a.cmd == "worker":
        from pathlib import Path

        from .worker import run_worker

        token = Path(a.token_file).read_text().strip()
        run_worker(a.server, token, poll_s=a.poll, once=a.once)
    elif a.cmd == "calibrate":
        calibrate(a)
    elif a.cmd == "decoders":
        from .decoders import registry

        for d in registry().values():
            print(json.dumps(d.describe()))
    elif a.cmd == "forge":
        from pathlib import Path

        if a.forge_cmd == "check":
            from .forge.io import preflight_check

            res = preflight_check(Path(a.input))
            print(json.dumps(res, indent=2))
            if not res["ok"]:
                raise SystemExit(1)
        elif a.forge_cmd == "run":
            from .forge.pipeline import run_forge_slam

            wdir = Path(a.work)
            res = run_forge_slam(Path(a.input), wdir)
            res.reconstruction.save(wdir / "recon.npz")
            print(json.dumps(res.diagnostics, indent=2))
        elif a.forge_cmd == "eval-real":
            from .forge.real_eval import evaluate_m2dgr, evaluate_sthereo

            out = Path(a.out)
            reports = {}
            if a.m2dgr_bag:
                reports["m2dgr"] = evaluate_m2dgr(Path(a.m2dgr_bag), Path(a.m2dgr_gt), out / "m2dgr", Path(a.figures) if a.figures else None)
            if a.sthereo:
                reports["sthereo"] = evaluate_sthereo(Path(a.sthereo), out / "sthereo")
            print(json.dumps({k: {"lio_ate": v["lio_only"]["ate_rmse_m"], "forge_ate": v["forge"]["ate_rmse_m"]} for k, v in reports.items()}))
        elif a.forge_cmd == "eval":
            from .forge.eval import run_synthetic_sanity_check

            ds = Path(a.datasets_dir) if a.datasets_dir else None
            report = run_synthetic_sanity_check(datasets_dir=ds)
            print(json.dumps(report["sequences"], indent=2))
    elif a.cmd == "bench-potholes":
        from pathlib import Path

        from .bench_potholes import run_benchmark

        ds = Path(a.datasets_dir) if a.datasets_dir else None
        res = run_benchmark(a.suites, datasets_dir=ds)
        text = json.dumps(res, indent=2)
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(text)
        print(text)


def calibrate(a) -> None:
    from pathlib import Path

    import cv2

    from .config import CONFIG_DIR
    from .video.frames import sample, video_info
    from .video.perspective import RoadPlane

    path = CONFIG_DIR / "video.json"
    cfg = json.loads(path.read_text())
    pc = dict(cfg["perspective"])
    if a.src:
        pc["src"] = [[float(v) for v in s.split(",")] for s in a.src]
    for k in ("width_m", "length_m", "near_m"):
        if getattr(a, k) is not None:
            pc[k] = getattr(a, k)
    info = video_info(Path(a.video))
    frame = next((img for _, _, img in sample(Path(a.video), 1.0, a.t, a.t + 1.0)), None)
    if frame is None:
        raise SystemExit("no frame at that time")
    plane = RoadPlane(pc, info["width"], info["height"])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "calibrate_overlay.jpg"), plane.overlay(frame))
    cv2.imwrite(str(out / "calibrate_bev.jpg"), plane.bev(frame))
    print(f"wrote {out / 'calibrate_overlay.jpg'} and {out / 'calibrate_bev.jpg'}")
    print("Check: in the bird's-eye image, lane lines must be straight and parallel and the rectangle "
          f"{pc['width_m']} m x {pc['length_m']} m must match the road.")
    if a.save:
        pc["calibrated"] = True
        cfg["perspective"] = pc
        path.write_text(json.dumps(cfg, indent=2))
        print(f"saved to {path}")


if __name__ == "__main__":
    main()

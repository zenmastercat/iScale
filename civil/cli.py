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

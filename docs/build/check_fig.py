"""3D-check figure (f21_check3d.png): the app's own check images for two Route 348 findings.
Run from the project root: .venv/bin/python docs/build/check_fig.py"""
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civil import check3d, store  # noqa: E402

PID, SID = "88d34769ee", "2c77cfa42f"
an = store.get_analysis(PID, SID)
rec = check3d._recon(PID, SID)
rows, facts = [], {}
for fid in ("F2C7-0002", "F2C7-0095"):
    f = next(x for x in an["findings"] if x["id"] == fid)
    ev = check3d._evidence(rec, f)
    v = check3d.verdict(f, ev)
    facts[fid] = {"code": v["code"], "det_points": ev["det_points"], "det_inside": ev["det_inside"],
                  "measured": (f.get("metrics") or {}).get("depth_max_m"), "remeasured": ev["dip_m"], "noise": ev["ring_noise_m"]}
    ims = [cv2.imdecode(np.frombuffer(check3d.render(f, ev, k), np.uint8), 1) for k in check3d.PANELS]
    H = max(i.shape[0] for i in ims)
    ims = [np.vstack([i, np.full((H - i.shape[0], i.shape[1], 3), 255, np.uint8)]) for i in ims]
    gap = np.full((H, 16, 3), 255, np.uint8)
    rows.append(np.hstack([ims[0], gap, ims[1], gap, ims[2]]))
W = max(r.shape[1] for r in rows)
rows = [np.hstack([r, np.full((r.shape[0], W - r.shape[1], 3), 255, np.uint8)]) for r in rows]
out = np.vstack([rows[0], np.full((24, W, 3), 255, np.uint8), rows[1]])
cv2.imwrite(str(Path(__file__).with_name("fig") / "f21_check3d.png"), out)
pots = [f for f in an["findings"] if f["type"] == "pothole"]
facts["sources"] = dict(Counter(f.get("source") for f in pots))
(Path(__file__).with_name("fig") / "check_facts.json").write_text(json.dumps(facts, indent=1, default=float))
print(json.dumps(facts, indent=1, default=float))

"""Security review L4: spreadsheet formula injection in the findings CSV export."""

import csv
import io

from civil import store
from helpers import admin


def test_csv_cells_cannot_start_a_formula_but_numbers_stay_numbers():
    c = admin()
    proj = c.post("/api/projects", json={"name": "csv", "origin_lat": -33.86, "origin_lon": -151.2}).json()
    sv = store.create_survey(proj["id"], "csv", "demo", {})
    evil = ["=HYPERLINK(\"http://x\",\"y\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"]
    an = {"findings": [{"id": f"M-{i:04d}", "type": "pothole", "severity": "low", "status": "open", "source": "manual",
                        "lat": -33.8600001, "lon": -151.2000002, "x": 0, "y": 0, "z": 0, "evidence": e, "metrics": {},
                        "segment_id": e} for i, e in enumerate(evil)],
          "segments": []}
    store.save_analysis(proj["id"], sv["id"], an)
    r = c.get(f"/api/projects/{proj['id']}/surveys/{sv['id']}/export.csv")
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == len(evil)
    for row, e in zip(rows, evil):
        for col in ("evidence", "segment"):
            assert row[col] == "'" + e, (col, row[col])
        assert row["lat"] == "-33.8600001" and row["lon"] == "-151.2000002"  # numbers are not quoted

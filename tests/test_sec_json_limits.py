"""Security review M3: bounded measurement JSON and a per-route body cap (JSON 1 MB, chunked bodies refused)."""

import json

from helpers import client_for
from test_measure_api import body


def test_inner_point_lists_are_exactly_x_y():
    c = client_for("sec.json")
    long_pt = body()
    long_pt["ref_points"] = [[0.0] * 50_000] + long_pt["ref_points"][1:]
    assert c.post("/api/measure/preview", json=long_pt).status_code == 422
    out = body()
    out["outline"] = [[1.0, 2.0, 3.0]] + out["outline"][1:]
    assert c.post("/api/measure/preview", json=out).status_code == 422
    assert c.post("/api/measure/preview", json=body()).status_code == 200


def test_non_finite_and_absurd_coordinates_refused():
    c = client_for("sec.json")
    for bad in (float("nan"), float("inf"), 1e300):
        b = body()
        b["ref_points"] = [[bad, 10.0]] + b["ref_points"][1:]
        r = c.post("/api/measure/preview", content=json.dumps(b), headers={"content-type": "application/json"})
        # NaN/Inf: the schema refuses them, then FastAPI cannot echo the value in a JSON error -> 400
        want = (422,) if bad == 1e300 else (400, 422)
        assert r.status_code in want, (bad, r.status_code, r.text[:300])


def test_json_body_over_1mb_refused_before_parsing():
    c = client_for("sec.json")
    big = json.dumps({**body(), "pad": "x" * 1_200_000})
    r = c.post("/api/measure/preview", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_chunked_body_without_length_refused():
    c = client_for("sec.json")
    data = json.dumps(body()).encode()
    r = c.post("/api/measure/preview", content=iter([data[:100], data[100:]]), headers={"content-type": "application/json"})
    assert r.status_code == 411

"""Civil Helper RAG, provider settings and write-only keys (model calls are faked)."""

import io

import pytest

from helpers import admin, client_for

DOC = b"""# Crack sealing note
Crack sealing is done in cool, dry weather when cracks are open. Rout the crack to 12 mm wide,
blow it clean with compressed air, then fill with hot-applied rubberised sealant.

# Manhole adjustment note
A sunken manhole frame is raised with adjustment rings set in mortar; the frame must sit flush
within 6 mm of the new surface.
"""


@pytest.fixture
def fake_llm(monkeypatch):
    from civil import helper

    calls = {}

    def complete(cfg, company_id, system, user, timeout=240):
        calls["user"] = user
        return "Use adjustment rings set in mortar [1].", "fake-model"

    monkeypatch.setattr(helper, "complete", complete)
    monkeypatch.setattr(helper, "embed", lambda cfg, cid, texts: None)  # keyword search only
    return calls


def test_library_search_and_cited_answer(fake_llm):
    eng = client_for("uma")
    r = eng.post("/api/library", data={"title": "Maintenance notes"}, files={"file": ("notes.md", io.BytesIO(DOC), "text/markdown")})
    assert r.status_code == 200, r.text
    doc = r.json()
    a = eng.post("/api/helper/ask", json={"question": "How do I raise a sunken manhole frame?"}).json()
    assert a["answer"].startswith("Use adjustment rings") and a["model"].endswith("fake-model")
    assert a["sources"] and a["sources"][0]["title"] == "Maintenance notes"
    assert "adjustment rings" in fake_llm["user"]  # the matching passage was given to the model
    # only the uploader or an admin may delete
    other = client_for("vic")
    assert other.delete(f"/api/library/{doc['id']}").status_code == 403
    assert eng.delete(f"/api/library/{doc['id']}").status_code == 200


def test_unrecognised_survey_question_goes_to_helper(fake_llm):
    eng = client_for("uma")
    pid = eng.post("/api/projects", json={"name": "Civil Helper routing"}).json()["id"]
    r = eng.post(f"/api/projects/{pid}/chat", json={"message": "What sealant should I use for cracks in hot weather?"}).json()
    assert r["by"] == "helper" and "sources" in r


def test_library_rejects_other_file_types():
    eng = client_for("uma")
    r = eng.post("/api/library", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 400


def test_settings_are_admin_only_and_keys_write_only():
    eng = client_for("wes")
    assert eng.get("/api/settings").status_code == 403
    a = admin()
    r = a.put("/api/settings/helper", json={"type": "openai", "base_url": "https://gateway.example/v1", "model": "my-model",
                                            "embed_model": "", "api_key": "sk-test-123456"})
    assert r.status_code == 200 and r.json()["has_key"] is True
    s = a.get("/api/settings").json()
    assert "sk-test" not in str(s) and s["helper"]["model"] == "my-model"
    assert a.put("/api/settings/helper", json={"type": "nope", "model": "x"}).status_code == 400
    assert a.put("/api/settings/helper", json={"type": "ollama", "base_url": "file:///etc", "model": "x"}).status_code == 400
    # back to the default for other tests
    a.put("/api/settings/helper", json={"type": "ollama", "base_url": "", "model": "auto:smallest-qwen",
                                         "embed_model": "mxbai-embed-large", "api_key": ""})
    r = a.put("/api/settings/traffic", json={"osm": True, "google": True, "google_key": "AIza-test"})
    assert r.json()["has_google_key"] is True and "AIza" not in r.text


def test_network_mode_rules():
    a = admin()
    assert a.get("/api/settings").json()["network"]["mode"] == "internet"  # the default
    assert a.put("/api/settings/network", json={"mode": "internet"}).status_code == 400  # needs a host name
    r = a.put("/api/settings/network", json={"mode": "lan", "tls": "self-signed"})
    assert r.status_code == 200 and r.json()["restart_needed"]
    assert client_for("wes").put("/api/settings/network", json={"mode": "local"}).status_code == 403


def test_pick_smallest_official_qwen():
    import httpx

    from civil import helper

    tags = {"models": [
        {"name": "qwen3.5:35b", "size": 23e9, "details": {"parameter_size": "36.0B"}},
        {"name": "someone/qwen3.5-9b-tune:latest", "size": 6.549e9, "details": {"parameter_size": "9.0B"}},
        {"name": "qwen3.5:9b", "size": 6.55e9, "details": {"parameter_size": "9.0B"}},
        {"name": "qwen2.5-coder:14b", "size": 9e9, "details": {"parameter_size": "14.8B"}},
        {"name": "mxbai-embed-large:latest", "size": 6e8, "details": {"parameter_size": "334M"}},
    ]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=tags))
    with httpx.Client(transport=transport) as c:
        assert helper.resolve_model(helper.DEFAULTS, c) == "qwen3.5:9b"


def test_settings_saved_before_the_rename_still_apply():
    """Companies that saved provider settings or a key under the old name "Foreman" keep them."""
    from civil import db, helper, secrets

    a = admin()
    cid = a.get("/api/auth/state").json()["user"]["company_id"]
    db.set_setting(cid, "foreman", {"type": "openai", "base_url": "", "model": "old-model", "embed_model": ""})
    secrets.put(cid, helper.OLD_KEY_NAME, "sk-old-key-1")
    try:
        db.run("DELETE FROM settings WHERE scope=? AND key='helper'", cid)
        cfg = helper.config(cid)
        assert cfg["model"] == "old-model" and cfg["has_key"] and helper._key(cid) == "sk-old-key-1"
        # clearing the key in Settings removes the old copy too
        a.put("/api/settings/helper", json={"type": "ollama", "base_url": "", "model": "auto:smallest-qwen",
                                             "embed_model": "mxbai-embed-large", "api_key": ""})
        assert helper._key(cid) is None and helper.config(cid)["model"] == "auto:smallest-qwen"
    finally:
        secrets.put(cid, helper.OLD_KEY_NAME, None)

"""Civil Helper: a civil-engineering assistant that answers from the company's document library (RAG).

Provider is chosen per company in Settings, like OpenBot's model providers:
  ollama     local Ollama (default; model "auto:smallest-qwen" picks the smallest qwen* model)
  openai     OpenAI or any OpenAI-compatible endpoint (base URL: vLLM, LM Studio, OpenRouter, a gateway…)
  anthropic  Anthropic or an Anthropic-compatible endpoint
  google     Gemini through Google's OpenAI-compatible endpoint
Keys are entered by an admin and stored server-side (civil.secrets), never sent to browsers.

Retrieval is hybrid: BM25 keyword ranking always, plus embedding similarity when an
embedding model is available (Ollama mxbai-embed-large by default). Answers cite [n].
Questions go to the configured provider only; chat messages never do.
"""

from __future__ import annotations

import io
import math
import re
import secrets as _secrets
import time
from collections import Counter

import httpx
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from . import auth, db, secrets, store

router = APIRouter(prefix="/api")

PROVIDERS = ("ollama", "openai", "anthropic", "google")
DEFAULTS = {"type": "ollama", "base_url": "http://127.0.0.1:11434", "model": "auto:smallest-qwen",
            "embed_model": "mxbai-embed-large"}
BASES = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com",
         "google": "https://generativelanguage.googleapis.com/v1beta/openai"}
KEY_NAME = "HELPER_API_KEY"
OLD_KEY_NAME = "FOREMAN_API_KEY"  # saved before the rename to Civil Helper
MAX_DOC_BYTES = 40 * 1024 * 1024
CHUNK_CHARS, CHUNK_OVERLAP = 1100, 180
TOP_K = 6

SYSTEM = """You are Civil Helper, an assistant for civil engineers who inspect and repair roads, sidewalks and street assets.
Answer the engineer's question using the numbered sources below. Cite them inline like [1] or [2][3].
If the sources don't cover the question, say so plainly in one sentence, then give general engineering guidance
and label it "General guidance (not from your library)". Never invent standards, clause numbers, quantities or prices.
Prefer metric units. Be concise: short paragraphs or a short list. Safety first: mention traffic control or
hazards when the work involves a live road."""


# --- provider config ---------------------------------------------------------------------
def config(company_id: str) -> dict:
    saved = db.get_setting(company_id, "helper", None)
    if saved is None:  # settings saved before the rename to Civil Helper
        saved = db.get_setting(company_id, "foreman", {})
    c = {**DEFAULTS, **(saved or {})}
    c["has_key"] = secrets.has(company_id, KEY_NAME) or secrets.has(company_id, OLD_KEY_NAME)
    return c


def _base(cfg: dict) -> str:
    """Endpoint for the provider: the admin's base URL, else the provider's own API."""
    b = (cfg.get("base_url") or "").strip()
    if cfg["type"] == "ollama":
        return (b or DEFAULTS["base_url"]).rstrip("/")
    if not b or b.rstrip("/") == DEFAULTS["base_url"]:
        b = BASES[cfg["type"]]
    return b.rstrip("/")


def _key(company_id: str) -> str | None:
    return secrets.get(company_id, KEY_NAME) or secrets.get(company_id, OLD_KEY_NAME)


def resolve_model(cfg: dict, client: httpx.Client) -> str:
    m = cfg["model"]
    if cfg["type"] != "ollama" or not m.startswith("auto:"):
        return m
    r = client.get(_base(cfg) + "/api/tags")
    r.raise_for_status()
    models = r.json().get("models", [])
    qwen = [x for x in models if x["name"].split("/")[-1].lower().startswith("qwen")
            and "embed" not in x["name"] and "coder" not in x["name"]]
    if not qwen:
        raise HTTPException(503, "no qwen model in Ollama; pull one or pick another model in Settings")
    def params(x: dict) -> float:
        m = re.match(r"([0-9.]+)\s*([BM])", str(x.get("details", {}).get("parameter_size", "")), re.I)
        if not m:
            return x.get("size", 0) / 1e9
        return float(m.group(1)) * (1e-3 if m.group(2).upper() == "M" else 1)

    # fewest parameters; official library names (no "user/") before community uploads; then file size
    qwen.sort(key=lambda x: (params(x), "/" in x["name"], x.get("size", 0), x["name"]))
    return qwen[0]["name"]


def _strip_think(t: str) -> str:
    return re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()


def complete(cfg: dict, company_id: str, system: str, user: str, timeout: float = 240) -> tuple[str, str]:
    """Returns (text, model)."""
    typ = cfg["type"]
    if typ not in PROVIDERS:
        raise HTTPException(400, "unknown provider")
    with httpx.Client(timeout=timeout) as c:
        try:
            model = resolve_model(cfg, c)
            if typ == "ollama":
                r = c.post(_base(cfg) + "/api/chat", json={
                    "model": model, "stream": False, "think": False, "options": {"num_ctx": 8192, "temperature": 0.2},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                r.raise_for_status()
                return _strip_think(r.json()["message"]["content"]), model
            key = _key(company_id)
            if not key:
                raise HTTPException(503, "Civil Helper's provider needs an API key; an admin can add it in Settings")
            if typ == "anthropic":
                r = c.post(_base(cfg) + "/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                           json={"model": model, "max_tokens": 1500, "system": system,
                                 "messages": [{"role": "user", "content": user}]})
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json().get("content", [])).strip(), model
            r = c.post(_base(cfg) + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "temperature": 0.2,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            return _strip_think(r.json()["choices"][0]["message"]["content"]), model
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Civil Helper's model provider returned HTTP {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise HTTPException(503, f"can't reach Civil Helper's model provider ({type(e).__name__})") from e


def embed(cfg: dict, company_id: str, texts: list[str]) -> np.ndarray | None:
    """Embeddings for texts, or None when the provider has no embedding model configured/reachable."""
    m = cfg.get("embed_model")
    if not m or cfg["type"] == "anthropic":
        return None
    try:
        with httpx.Client(timeout=120) as c:
            if cfg["type"] == "ollama":
                r = c.post(_base(cfg) + "/api/embed", json={"model": m, "input": texts})
                r.raise_for_status()
                v = np.array(r.json()["embeddings"], dtype=np.float32)
            else:
                key = _key(company_id)
                if not key:
                    return None
                r = c.post(_base(cfg) + "/embeddings", headers={"Authorization": f"Bearer {key}"}, json={"model": m, "input": texts})
                r.raise_for_status()
                v = np.array([d["embedding"] for d in r.json()["data"]], dtype=np.float32)
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.maximum(n, 1e-9)


# --- library ---------------------------------------------------------------------------------
def extract(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """[(page, text)] from PDF, text or markdown."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        except Exception as e:  # pypdf raises many types on damaged files
            raise HTTPException(400, f"can't read this PDF ({type(e).__name__})") from e
    if name.endswith((".txt", ".md", ".csv")):
        return [(None, data.decode("utf-8", "replace"))]
    raise HTTPException(400, "upload a PDF, .txt or .md file")


def chunk(pages: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    out = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        i = 0
        while i < len(text):
            j = min(len(text), i + CHUNK_CHARS)
            if j < len(text):  # end on a paragraph or sentence break when possible
                cut = max(text.rfind("\n\n", i + CHUNK_CHARS // 2, j), text.rfind(". ", i + CHUNK_CHARS // 2, j))
                if cut > i:
                    j = cut + 1
            piece = text[i:j].strip()
            if len(piece) > 60:
                out.append((page, piece))
            if j >= len(text):
                break
            i = max(j - CHUNK_OVERLAP, i + 1)
    return out


def add_document(company_id: str, uploader: str, title: str, filename: str, data: bytes) -> dict:
    pages = extract(filename, data)
    chunks = chunk(pages)
    if not chunks:
        raise HTTPException(400, "no text found (a scanned PDF needs OCR first)")
    cfg = config(company_id)
    did = _secrets.token_hex(6)
    vecs = None
    texts = [t for _, t in chunks]
    parts = []
    for k in range(0, len(texts), 32):
        v = embed(cfg, company_id, texts[k:k + 32])
        if v is None:
            parts = None
            break
        parts.append(v)
    if parts:
        vecs = np.concatenate(parts)
    with db.tx() as con:
        con.execute("INSERT INTO docs(id,company_id,title,filename,created,chars,uploader,embedded) VALUES(?,?,?,?,?,?,?,?)",
                    (did, company_id, title[:200], filename[:200], time.time(), sum(len(t) for t in texts), uploader,
                     int(vecs is not None)))
        con.executemany("INSERT INTO chunks(doc_id,ord,page,text,embedding) VALUES(?,?,?,?,?)",
                        [(did, i, p, t, vecs[i].tobytes() if vecs is not None else None) for i, (p, t) in enumerate(chunks)])
    if vecs is not None:
        db.set_setting(company_id, "library_embed_model", cfg["embed_model"])
    return _doc_out(db.one("SELECT * FROM docs WHERE id=?", did) | {"chunks": len(chunks)})


TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
STOP = set("a an and are as at be by for from has have how i in is it its of on or that the this to was what when where which who why will with do does can should".split())


def tokens(t: str) -> list[str]:
    return [w for w in TOKEN.findall(t.lower()) if w not in STOP and len(w) > 1]


def search(company_id: str, query: str, k: int = TOP_K) -> list[dict]:
    rows = db.all_("SELECT c.id, c.doc_id, c.page, c.text, c.embedding, d.title FROM chunks c JOIN docs d ON d.id=c.doc_id "
                   "WHERE d.company_id=?", company_id)
    if not rows:
        return []
    q = tokens(query)
    docs_tok = [tokens(r["text"]) for r in rows]
    n = len(rows)
    avg = sum(len(t) for t in docs_tok) / n
    df = Counter(w for t in docs_tok for w in set(t))
    bm = np.zeros(n)
    for i, t in enumerate(docs_tok):
        tf = Counter(t)
        for w in q:
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                bm[i] += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(t) / avg))
    score = bm / bm.max() if bm.max() > 0 else bm
    cfg = config(company_id)
    if all(r["embedding"] for r in rows) and db.get_setting(company_id, "library_embed_model") == cfg.get("embed_model"):
        qv = embed(cfg, company_id, [query])
        if qv is not None:
            m = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            if m.shape[1] == qv.shape[1]:
                cos = m @ qv[0]
                cos = (cos - cos.min()) / max(1e-9, cos.max() - cos.min())
                score = 0.45 * score + 0.55 * cos
    top = np.argsort(-score)[:k]
    return [{"chunk_id": rows[i]["id"], "doc_id": rows[i]["doc_id"], "title": rows[i]["title"], "page": rows[i]["page"],
             "text": rows[i]["text"], "score": round(float(score[i]), 3)} for i in top if score[i] > 0]


def survey_context(company_id: str, project: str | None, survey: str | None) -> str | None:
    if not (project and survey):
        return None
    try:
        proj = store.get_project(project)
        if proj.get("company_id") != company_id:
            return None
        an = store.get_analysis(project, survey)
    except KeyError:
        return None
    from . import catalog

    defects = [f for f in an["findings"] if catalog.CATALOG[f["type"]].kind == "defect" and f.get("status") not in ("verified", "dismissed")]
    by = Counter(f"{catalog.CATALOG[f['type']].label} ({f.get('severity')})" for f in defects)
    segs = [s for s in an["segments"] if s.get("condition") is not None]
    worst = sorted(segs, key=lambda s: s["condition"])[:3]
    return (f"Project '{proj['name']}', survey {survey}: {len(segs)} segments, open defects: "
            + (", ".join(f"{v}x {k}" for k, v in by.most_common(12)) or "none")
            + ". Lowest segments: " + ", ".join(f"{s['id']} index {s['condition']}" for s in worst) + ".")


def ask(company_id: str, question: str, project: str | None = None, survey: str | None = None) -> dict:
    hits = search(company_id, question)
    ctx = survey_context(company_id, project, survey)
    parts = []
    for i, h in enumerate(hits, 1):
        where = f", page {h['page']}" if h["page"] else ""
        parts.append(f"[{i}] {h['title']}{where}\n{h['text']}")
    if ctx:
        parts.append(f"[{len(hits) + 1}] Survey data from iScale\n{ctx}")
    sources_txt = "\n\n".join(parts) if parts else "(no matching documents in the library)"
    user = f"Sources:\n{sources_txt}\n\nQuestion: {question}"
    cfg = config(company_id)
    t0 = time.time()
    text, model = complete(cfg, company_id, SYSTEM, user)
    sources = [{"n": i, "title": h["title"], "page": h["page"], "doc_id": h["doc_id"], "snippet": h["text"][:280]}
               for i, h in enumerate(hits, 1)]
    if ctx:
        sources.append({"n": len(hits) + 1, "title": "Survey data from iScale", "page": None, "doc_id": None, "snippet": ctx[:280]})
    return {"answer": text, "sources": sources, "model": f"{cfg['type']}:{model}", "seconds": round(time.time() - t0, 1),
            "library_hits": len(hits)}


# --- routes -------------------------------------------------------------------------------------
class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    project: str | None = None
    survey: str | None = None


@router.post("/helper/ask")
def ask_route(body: AskIn, request: Request):
    me = auth.require(request)
    return ask(me["company_id"], body.question, body.project, body.survey)


@router.get("/helper/status")
def status(request: Request):
    me = auth.require(request)
    cfg = config(me["company_id"])
    out = {"type": cfg["type"], "model_setting": cfg["model"], "embed_model": cfg.get("embed_model"),
           "documents": db.one("SELECT COUNT(*) AS n FROM docs WHERE company_id=?", me["company_id"])["n"]}
    try:
        with httpx.Client(timeout=5) as c:
            out["model"] = resolve_model(cfg, c)
            out["reachable"] = True
    except (httpx.HTTPError, HTTPException) as e:
        out["reachable"] = False
        out["error"] = getattr(e, "detail", type(e).__name__)
    return out


@router.get("/library")
def library(request: Request):
    me = auth.require(request)
    rows = db.all_("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.doc_id=d.id) AS chunks FROM docs d "
                   "WHERE company_id=? ORDER BY created DESC", me["company_id"])
    return [_doc_out(r) for r in rows]


def _doc_out(d: dict) -> dict:
    who = auth.person(d["uploader"])
    return {k: v for k, v in d.items() if k != "embedding"} | {"uploader": who["username"] if who else None}


@router.post("/library")
async def upload_doc(request: Request, title: str = Form(""), file: UploadFile = File(...)):
    me = auth.require(request)
    data = await file.read(MAX_DOC_BYTES + 1)
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(413, "documents are limited to 40 MB")
    name = store.safe_filename(file.filename or "document")
    return add_document(me["company_id"], me["uid"], title.strip() or name, name, data)


@router.delete("/library/{doc_id}")
def delete_doc(doc_id: str, request: Request):
    me = auth.require(request)
    d = db.one("SELECT * FROM docs WHERE id=? AND company_id=?", doc_id, me["company_id"])
    if not d:
        raise HTTPException(404, "no such document")
    if me["role"] != "admin" and d["uploader"] != me["uid"]:
        raise HTTPException(403, "only the uploader or an admin can remove a document")
    db.run("DELETE FROM docs WHERE id=?", doc_id)
    return {"ok": True}


@router.post("/library/reindex")
def reindex(request: Request):
    """Recompute embeddings with the current embedding model (after changing provider)."""
    me = auth.require_admin(request)
    cfg = config(me["company_id"])
    rows = db.all_("SELECT c.id, c.text FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.company_id=? ORDER BY c.id", me["company_id"])
    done = 0
    for k in range(0, len(rows), 32):
        part = rows[k:k + 32]
        v = embed(cfg, me["company_id"], [r["text"] for r in part])
        if v is None:
            raise HTTPException(503, "the embedding model isn't reachable; keyword search still works")
        with db.tx() as con:
            con.executemany("UPDATE chunks SET embedding=? WHERE id=?", [(v[i].tobytes(), r["id"]) for i, r in enumerate(part)])
        done += len(part)
    db.run("UPDATE docs SET embedded=1 WHERE company_id=?", me["company_id"])
    db.set_setting(me["company_id"], "library_embed_model", cfg.get("embed_model"))
    return {"chunks": done}

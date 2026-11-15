# Security review, 2026-11-14

Scope: the whole tree except `.venv/` and `static/vendor/`. Done by Mr.Main after the
Security Reviewer teammate could not run (its model provider was offline). The app is
meant for one user on their own computer (bound to 127.0.0.1, no login).

## Fixed

| # | Severity | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | High | **DNS rebinding.** The server answered any `Host`, so a hostile web page could point its own domain at 127.0.0.1 and use the API with full read/write access: read surveys, delete projects, start video jobs that spend Roboflow credits. | `TrustedHostMiddleware` with `CIVIL_ALLOWED_HOSTS` (default `127.0.0.1,localhost,[::1]`). | `test_cross_site_and_rebinding_requests_are_refused` |
| 2 | Medium | **Cross-site requests.** No-body POSTs (`/api/demo`, `…/retry`) and multipart uploads are "simple" requests a browser sends cross-origin without a preflight. | Every non-GET `/api` call must carry `X-Civil-Scan: 1`; other origins can only send it after a CORS preflight, which the server never grants. The UI sends it. | same test |
| 3 | Medium | **Roboflow key passed to subprocesses.** LingBot and external decoders inherited the server environment, including `ROBOFLOW_API_KEY`. | Secrets in `SECRET_ENV` are removed from subprocess environments. | `test_decoder_processes_do_not_get_the_roboflow_key` |
| 4 | Low | **Upload size checked late.** The 4 GB limit was enforced while copying, after Starlette had already spooled the upload to temporary disk. | Requests whose `Content-Length` exceeds the limit are refused before the body is read. | manual (`curl`) |

## Checked, no change needed

- **XSS:** every place that builds HTML from server data escapes it (`esc()`); the chat
  renderer escapes before applying its small markdown; map popups use server-generated
  ids and numbers only; the SVG map uses `textContent`.
- **Paths:** project and survey ids must match `^[a-z0-9]{6,32}$`; upload names are
  reduced to a safe base name; evidence images must match `t[0-9_]+(_bev)?\.jpg`.
- **Subprocesses:** argument lists, never a shell; uploaded file names reach commands only
  as absolute paths, so a name like `-rf` can't become an option; commands come from
  local config files, not from requests.
- **Files:** `np.load(..., allow_pickle=False)` everywhere; PLY vertex count capped.
- **Key handling:** the Roboflow key travels in a request header (not the URL), is never
  written to `video.json`, survey records or logs (checked with grep), and errors don't
  include it.

## Remaining, by design

- ~~No login~~ (fixed on 14 Nov 2026: username + device-key sign-in, see below).
- A very large or malformed PLY/video uploaded by the user can use a lot of memory or
  CPU. That's accepted for a single-user local tool.
- `/docs` (FastAPI's API explorer) is enabled; it is covered by the same host and header
  checks.

## Update, 14 Nov 2026: accounts, chat, groups, traffic

| Area | Protection | Checked by |
|---|---|---|
| Sign-in | ECDSA P-256 device key (non-extractable), single-use 2-min nonce, username bound on first sign-in; HttpOnly SameSite=Strict session | tests/test_auth.py |
| Data at rest | usernames, names, group names AES-256-GCM (column as associated data); rows keyed by HMAC-SHA256 uid; keys from one server key via HKDF; migration vacuums and truncates the WAL; `secure_delete` on | tests/test_auth.py, byte scan of civil.db + WAL |
| Chat | Signal Protocol (X3DH + Double Ratchet) in the browser; server stores ciphertext until ack, max 30 days; rate limit per send action | tests/test_messaging.py |
| Groups | roster on server; sender and every recipient must be members; one copy per member; group id inside the ciphertext must match the envelope or the device drops it; removed members lose undelivered copies | tests/test_groups.py |
| Security code | 60-digit Signal fingerprint, computed with WebCrypto (same output as the library, checked in the browser) | manual browser check |
| Google traffic | Routes results kept in memory 5 min, never on disk (Google terms) | tests/test_messaging.py |
| Civil Helper routing | general questions go to Civil Helper; survey questions stay on the rules | tests/test_units.py |

Known limits: the server sees group membership, message timing and size; a member of a
group can post a fake "notice" line into that group; the key file next to the database
protects copied databases only if `CIVIL_DB_KEY` is used instead.

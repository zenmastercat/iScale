# iScale web (Next.js)

New frontend for iScale. The backend (`../civil`, FastAPI) is unchanged; the old UI in `../static` stays.

```bash
# backend, from the repo root
uv sync && uv run civil serve        # http://127.0.0.1:8765

# frontend, dev
cd web && pnpm install && pnpm dev   # http://localhost:3000 (/api proxied to :8765)

# frontend, pitch / production-like
pnpm build && pnpm serve             # static export in out/, served + /api proxied on http://127.0.0.1:3000
```

`CIVIL_API` changes the backend URL (both `pnpm dev` and `pnpm serve`). To open the site from a phone on the
same network: `HOST=0.0.0.0 CIVIL_ALLOWED_HOSTS=<laptop-ip> pnpm serve` (see `PITCH.md`).

```bash
pnpm rehearse --build   # the whole demo story in a real browser, on its own backend (:8790) and port (:3190);
                        # checks every page at 1440 and 390 px incl. accessibility. Output in rehearsal/.
pnpm lint && pnpm typecheck
```

Pages: Overview, Findings, Map (+ finding drawer, phone QR), Fix first, Repair plan, Verification, Surveys,
Report (print / PDF), Team, phone job card (`/job`). English / Thai switch in the top bar.

- `PITCH.md`: how to run the pitch, the click path, what to do when something fails
- `CONTRACT.md`: how the code is organised (ownership, data hooks, i18n, density, accessibility)
- `STATUS.md`: progress and decisions

## Security (25 Nov)

- **Accounts:** self sign-up is off by default. People get an account from an admin (Team → Add person) and the
  first device that signs in owns it. Turn sign-up on with `CIVIL_OPEN_SIGNUP=1` or in the backend's Settings.
- **Sign-in:** device-key signatures (no passwords), 30 challenge/login calls per minute per address. The session
  cookie is HttpOnly + SameSite=Strict; behind an HTTPS proxy start the backend with `CIVIL_SECURE_COOKIE=1`.
- **Headers:** backend and `pnpm serve` send nosniff, no framing, same-origin referrer and COOP/CORP. The pages get
  a CSP that allows only this origin plus the OSM tile server, with inline scripts pinned by hash. `pnpm rehearse`
  fails on any CSP violation.
- **Network:** both servers refuse unknown Host headers (DNS rebinding); add a LAN IP with `CIVIL_ALLOWED_HOSTS`.
  Every state-changing API call needs the `X-Civil-Scan` header (CSRF).

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

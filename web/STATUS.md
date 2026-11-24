# iScale web: status

Code freeze: evening of 25 Nov 2026 · Pitch: 26 Nov 2026 · Branch `web-frontend` (the lead commits)

## Lead
Done (24 Nov):
- Scaffold: Next 16 (static export), Tailwind v4, shadcn/ui (Base UI), TanStack Query, map/chart/3D packages
- Tokens + fonts (Plex Sans / Sans Thai / Mono), `lib/api.ts` (all endpoints), `lib/types.ts` (from real responses)
- Sign-in (`/login`, port of static/session.js) + first-run setup; tested against a live backend:
  setup → sign-in → sign-out → sign-in again with the same device key
- App shell: left rail / phone bottom bar, project + survey pickers, Sample data badge, sign out
- Shared components, CONTRACT.md
- Overview: summary sentence, 4 KPI tiles, chainage strip, condition share, Fix first top 5.
  Demo numbers match the README: 242 m, 89/100, 10 open (4 high), USD 2,585

Next: integrate A and B, `pnpm build` after each report.

### Pitch serving (decision)
`civil/` only serves `static/`, and the backend must not change, so FastAPI can't serve `out/`.
For the pitch: `cd web && pnpm build && pnpm serve` (scripts/serve.mjs: serves `out/` and proxies `/api` to
:8765, no dev compile delays). Fallback: `pnpm dev`.

### Scope cut / known gaps
- Login has sign-in + first-run setup only. "Create account" / join code (POST /api/auth/register) is wired
  in `lib/auth.ts` (`register`) but has no UI; admins add people in the old UI.

## Sub-agent A (Map, finding drawer, job card)
_(A writes here)_

## Sub-agent B (Repair plan, Fix first, Verification, Surveys)
_(B writes here)_

## Requests to the lead
_(packages, types, shared components: write here and message the lead)_

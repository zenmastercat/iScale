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

- Security fixes: login `next` redirect is same-origin only; serve.mjs checks Host and survives bad URLs
- MapLibre 6 worker: copied to `public/maplibre/` on install/dev/build; import react-map-gl from `@/lib/maplibre`
- Reviewed + committed A's Map, drawer and job card (browser-checked at 1440 and 390 px, no console errors)

Next: B's pages when B reports; then a full click-through at 390 px.

### Dev servers (only ONE `next dev` per folder)
Everyone shares the lead's `http://127.0.0.1:3000`, proxied to a throwaway backend on :8767 (signed in,
demo loaded). The lead browser-tests and reviews; sub-agents typecheck/lint and report.

### Pitch serving (decision)
`civil/` only serves `static/`, and the backend must not change, so FastAPI can't serve `out/`.
For the pitch: `cd web && pnpm build && pnpm serve` (scripts/serve.mjs: serves `out/` and proxies `/api` to
:8765, no dev compile delays). Fallback: `pnpm dev`.

### Scope cut / known gaps
- Login has sign-in + first-run setup only. "Create account" / join code (POST /api/auth/register) is wired
  in `lib/auth.ts` (`register`) but has no UI; admins add people in the old UI.

## Sub-agent A (Map, finding drawer, job card)
A: Map /map (MapLibre, OSM tiles over plain background, condition lines, severity-shape markers, Condition/Defects/Assets toggles, legend, fit bounds, ?segment= focus). Files: app/(app)/map/page.tsx, components/map/*
A: Finding drawer (?finding=, right sheet on desktop, bottom sheet on phone): trust badge, frame or placeholder, metrics, evidence, materials THB, Open job card, Add to work order. components/map/finding-drawer.tsx
A: Job card /job?finding= (Location/Materials/Timing/Steps tabs, EN/TH toggle, Navigate, Mark as fixed). components/jobcard/*
A: lint + typecheck clean for my files (typecheck errors exist in components/plan/use-plan.ts, B's). NOT yet checked in a browser: Playwright's Chrome is missing, and Next allows one dev server per dir so I used the lead's :3000. Lead please eyeball /map and /job at 390px.
A: Not done: pins (/api/pins/{id}/card), 3D view.
Lead (24 Nov): reviewed in a browser and committed. Fixed: worker import, nativeButton on link buttons, depth in cm.
Pins and the 3D view are cut from scope.

## Sub-agent B (Repair plan, Fix first, Verification, Surveys)
B: Repair plan `/plan`, Fix first `/fix-first`, Verification `/verification`, Surveys + Add survey `/surveys` written. `pnpm typecheck`, `pnpm lint`, `pnpm build` pass.
B: API flow checked against a throwaway backend (:8772) with the demo project: plan (spot, budget, segment) → priority → work order → scheduled → completed → verify (6 verified / 4 not fixed). All shapes match the pages.
B: NOT checked by eye: no Chrome for Playwright here and `pnpm dev` on :3002 is blocked by the lead's dev server on :3000 (same dir lock), so the UI was never opened in a browser. Please click through each page once.
B: Notes: Add survey upload uses XMLHttpRequest (components/surveys/upload.ts) because fetch has no upload progress. `/api/priority` pins also return `confirmations`, `reporter`, `road_name` and finding rows have `cost`; types.ts lacks them, so components/fix-first/ranking-table.tsx declares a local `PriorityRow`.

## Requests to the lead
_(packages, types, shared components: write here and message the lead)_

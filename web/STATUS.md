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

- Reviewed + committed B's pages (plan → WO-0001 → verify: 6 verified / 4 not fixed)
- 25 Nov full review (fresh backend, setup → demo → every page at 1440 + 390, flows, axe WCAG 2 AA): sign-in, demo,
  map keyboard (Enter opens drawer, focus to Close, Escape returns focus to the marker), Fix first exports (200),
  plan slider + Whole segments + Create work order, verification flow, Set as baseline confirm, sign out/in all pass.
  No console errors. Fixed: sideways scroll at 390 px (Overview, Surveys, Verification tables: sr-only/absolute children
  escaped `overflow-x-auto`; wrappers are now `relative`), Select triggers stuck at 32 px (kit's `data-[size=default]:h-8`
  beat `h-11`; now 44 px on phones), Budget slider input had no label (thumb gets the aria-label) and a 12 px thumb (now 20 px, 44 px hit area).

Open: Verification layout vs design (B), MapLibre zoom buttons 29 px (A). /job on phones now hides the top bar (done by the lead).

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
A: Segment hover/click on /map shows a popup (id, condition score + band, length, defect count); click pins it, click empty map clears. components/map/map-view.tsx. Lint/typecheck clean; not seen in a browser by me.
A: URL sync already works: marker click sets ?finding=, closing the drawer drops it (map/page.tsx). Job card action bar untouched (still above the bottom nav).
A: Round 3 (lint + typecheck clean, not browser-tested): marker click now pushes ?finding= (browser back works), close replaces it; ?segment= draws a navy halo and an id/score/defect-count card; Add to work order invalidates workOrders, analysis, priority, jobCard so the drawer shows Planned; job card Mark as fixed asks to confirm (EN/TH) then invalidates the same keys; /job bottom padding 160px covers the action bar (72) + bottom nav (56).
A: Round 4 (lint + typecheck clean, not browser-tested): markers are <button> with aria-label "<id>, <label>, <sev> severity[, status]"; drawer focuses its close button on open and returns focus to the marker on close; resolved (fixed/verified/dismissed) markers are muted with a check; offline tile failure shows a notice over the plain background; layer toggles aria-pressed, min-h-11.
A: Job card vs design gaps I can't confirm without a browser: exact tile order/labels depend on the backend tiles list; button height is 48px vs ~50px in the PNG; the photo placeholder has no diagonal corner mark. Header, tabs, tile grid, address card and the Navigate/Mark as fixed pair follow the design.
A: Round 5: map zoom buttons are 44px below md (arbitrary-variant class on the map wrapper, max-md:[&_.maplibregl-ctrl-group_button]:size-11). Lint/typecheck clean, not browser-tested.
A: Not done: pins (/api/pins/{id}/card), 3D view.
Lead (24 Nov): reviewed in a browser and committed. Fixed: worker import, nativeButton on link buttons, depth in cm.
Pins and the 3D view are cut from scope.

## Sub-agent B (Repair plan, Fix first, Verification, Surveys)
B: Repair plan `/plan`, Fix first `/fix-first`, Verification `/verification`, Surveys + Add survey `/surveys` written. `pnpm typecheck`, `pnpm lint`, `pnpm build` pass.
B: API flow checked against a throwaway backend (:8772) with the demo project: plan (spot, budget, segment) → priority → work order → scheduled → completed → verify (6 verified / 4 not fixed). All shapes match the pages.
B: NOT checked by eye: no Chrome for Playwright here and `pnpm dev` on :3002 is blocked by the lead's dev server on :3000 (same dir lock), so the UI was never opened in a browser. Please click through each page once.
B: Notes: Add survey upload uses XMLHttpRequest (components/surveys/upload.ts) because fetch has no upload progress. `/api/priority` pins also return `confirmations`, `reporter`, `road_name` and finding rows have `cost`; types.ts lacks them, so components/fix-first/ranking-table.tsx declares a local `PriorityRow`.
B: Round 2 (typecheck, eslint on my folders and build pass; not browser-tested at 390 px, no Chrome here): /fix-first and /plan render cards below md (table kept on md+), each with a full-width 44 px "Open on map" link. Local PriorityRow removed, PriorityItem used.
B: /verification: Mark scheduled/completed and Run verification now invalidate work orders, verification, the baseline's analysis and priority, and the project (components/verification/invalidate.ts). Run button uses the default variant and is disabled only while running or when before = after; I could not reproduce the grey look without a browser, please recheck.
B: /surveys: uploading selects the new survey, so other pages show ProcessingState until it is done, and the Surveys page shows a ProcessingState card per queued/running survey. Dialog inputs have labels; failures toast the server detail.
B: Round 3 (typecheck + eslint clean; no browser here): /plan has 0 / mid / max labels and a one-line explanation under the slider, and "Create work order (n)" sits in the page header. Whole segments: checked on the API that budget applies (none 13,222 → 10 funded; 4,000 → 1 funded/9 deferred; 9,000 → 6/4) and the table shows ConditionChip, treatment, area, urgency, cost. Switching mode resets the budget to No limit (the two modes have different totals).
B: /fix-first has Export CSV and Export GeoJSON links (exportUrl, a href download, min-h-11). /surveys: Retry on failed surveys was already there; "Set as baseline" now asks for confirmation in a dialog.
B: GAP: round 3 item 1 (Verification vs design) NOT done. The design PNGs under /tmp/claude-1000/.../b94385a4-.../scratchpad/design/ no longer exist on disk (the folder holds only started/, tasks/ and an empty scratchpad), so I could not match the layout or wording. Please re-save the two PNGs (Verification, Repair plan) somewhere stable and I will do it; the Repair plan items were built from the written description only.

## Requests to the lead
_(packages, types, shared components: write here and message the lead)_
- A -> lead: /job on phones should hide the app top bar. Needed from the shell: in components/shell (TopBar or app/(app)/layout.tsx) skip rendering TopBar when usePathname() === "/job" and the viewport is below md (e.g. className "max-md:hidden" on TopBar for that route). No change needed on my side: the job card header already has its own back and language buttons, and its -mt-6/-mx-4 offsets cancel main's padding.

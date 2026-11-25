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

25 Nov, user decisions: build a Findings table (A) and a compact Overview (lead) before the freeze; dense on
desktop only (CONTRACT.md "Density"). Printable report, segment line diagram, portfolio view: after the pitch.
- Compact Overview (lead, done): clickable KPI tiles → /findings (filtered), /plan, /map; condition strip next to an
  open-defect type × severity grid (each count links to /findings?type=&severity=&status=open,planned,not_fixed);
  repair cost by action (plan.by_action + mobilisation + total); condition change per segment, baseline → other drive.
- Fixed: usePriority(5) on the Overview shared a cache key with usePriority() on Fix first (the full list could show 5 rows).

25 Nov, evening (user: "keep going until the limit"): pitch safety + story features.
- `pnpm rehearse [--build]` (scripts/rehearse.mjs): own backend :8790 + out/ on :3190; setup → demo → every page at
  1440 + 390 (renders, no sideways scroll, axe WCAG 2 AA) → map drawer → budget → work order → phone job card →
  verify 6/4 → report PDF → Team adds a crew member and a second "phone" browser signs in to the job card →
  Thai switch → sign out/in. Found + fixed: serve.mjs sent .mjs as octet-stream (map worker failed in the pitch build).
- PITCH.md runbook. Team page (add people + sign-in QR, reset device). How we measure panel (rules read from the
  backend code). Thai/English switch (lib/i18n.tsx) for shell, shared badges, Overview, login. Favicon, 404, page titles.
- Segment line diagram (A) placed on the Overview.

Earlier open items: Verification layout vs design (B), MapLibre zoom buttons 29 px (A). /job on phones now hides the top bar (done by the lead).

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
A: Findings table /findings (lint + typecheck clean, not browser-tested): app/(app)/findings/page.tsx, components/findings/{rows.ts,filter-bar.tsx,findings-table.tsx}. All 13 columns, sticky header + totals row, header click sorts (aria-sort, numbers right-aligned in num), kind/severity/status/type/segment filters + search, "n of N findings", Clear filters, Export CSV (client Blob, filtered rows, formula-guarded). Every filter and sort lives in the URL via parseFindingsFilter/findingsQuery (router.replace; search is debounced 250 ms). Below md: compact cards. Default sort is chainage ascending. Multi-selects are native <details> checklists (no Popover component in ui/). Empty values sort last. Please check: deep link /findings?severity=high&status=open.
A: Queue 1 done (lint + typecheck clean, not browser-tested): QR "Open on a phone" in the finding drawer (components/map/qr-block.tsx): absolute /job URL, Copy link, localhost hint (mentions PITCH.md, which doesn't exist in the repo yet), hidden below md.
A: Queue 2 done: job card uses useLang()/setLang from lib/i18n; its own toggle button now flips the app language (components/jobcard/job-card.tsx).
A: Queue 3 done: Thai via useT() on /map (toggles, legend, popup, tile notice, marker aria-labels), the drawer, TrustBadge and /findings (columns, filters, empty state, totals). Left in English because they come from shared code or the server: StatusPill words, the Source column (evidenceSource), catalog labels, evidence, condition band words in the segment diagram aria-label.
A: Queue 4 done: components/linear/segment-diagram.tsx, SegmentDiagram({ segments, findings, labelFor, withSel }). Chainage axis with 50 m ticks and gridlines; lanes Condition (band blocks + score), Defects (severity marks, links to /map?finding=, stacked when within 4 m), Road width, Coverage, Surface roughness; sticky left labels; each segment column is a link to /map?segment= with a full aria-label; hover/focus highlights the column and fills a readout line; scrolls horizontally inside the box below ~640 px track width. Caveat: stacked defect marks are 44 px targets at 16 px spacing, so they overlap; check on a phone.
A: Findings density pass (lint + typecheck clean, not browser-checked): ids nowrap; body cells md:py-1 (header/totals unchanged), compact StatusPill/SeverityBadge (py-0, text-xs), Type truncates at 9rem with a title tooltip, table min-w-[1168px] so it scrolls sideways only below that. Expect ~28 px rows. Table box height is calc(100dvh-16rem); if 20 rows don't fit at 1440x900, lower the 16rem.
A: Queue 5.1 SegmentDiagram: resolved (fixed/verified/dismissed) defects are grey with a check and the aria-label says resolved (status); legend row High ▲ Medium ● Low ▼ + Resolved ✓ under the diagram. components/linear/segment-diagram.tsx.
A: Queue 5.2 Drawer History: components/map/history.tsx, newest first, 5 then "Show all N", event/when/by/work order, Thai via useT; event words translated for created, edited, planned, "workorder <status>", "verification: <status>".
A: Queue 5.3 Map "Colour by" Condition | Roughness | Coverage | Road width, ?colour= kept in the URL (also across marker click and drawer close). Non-condition metrics: 4 equal-width steps of accent blue between the survey's min and max, legend shows the ranges + "No value"; popup shows the metric. components/map/metrics.ts, legend.tsx, map-view.tsx, map/page.tsx.
A: Queue 5.4 Job card Thai: tile labels were falling back to English server text because my key map didn't match the backend keys (area_m2, depth_max_m, volume_m3, diameter_m). Fixed, volume now shows in L as in the design; "layer(s)" and the traffic level (low/light/medium/moderate/high/heavy) translated. Still English by design: server text (method label, bill lines without label_th, tools, steps, urgency, warning, reason, road class) and the shared SeverityBadge/StatusPill words.
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
B: Round 3 item 1 done (supersedes the GAP note): /verification now follows the design PNG. Header chips Before: X -> After: Y and a crumb with the work order and its status; three round-icon tiles (Verified fixed / Still present / Not covered by the after drive); card 'Each repair, before and after' with All(n)/Verified/Still present/Not covered filters; result cards with Before/After bars + cm, the evidence sentence verbatim and a pill. Work orders and Run controls are below the results. Layout stacks below md (one column, pill beside the name). Typecheck and eslint clean; NOT checked in a browser or at 390 px (no Chrome here). Gaps vs the PNG: after value for a fixed finding is surface_delta_m (+0.4 cm), bars scale to the largest before/after size in the list; the design's rows show the segment next to the id (F-0001 · S001) but the verification result has no segment_id, so only the id is shown.
B: Verification bars fixed for area defects: Before/After show the measure that exists (cm for depth/step/height, else area in m²) with its unit; bars scale per unit (cm rows vs cm, m² rows vs m²); no value = no bar (not_covered still draws the grey 'no data' bar). Typecheck and eslint clean; not re-checked in a browser.
B: Density (CONTRACT 'Density') applied on md+ only to /plan, /fix-first, /verification, /surveys: card padding md:p-4, section gaps md:gap-4, headings md:text-base, tables md:text-[13px] with md:py-1.5 rows, budget figure md:text-5xl, verification rows md:p-3 and narrower columns so evidence fits on one line at lg+. Below md nothing changed (cards, 44 px targets). No behaviour change. Typecheck and eslint clean; not browser-checked. KpiTile/EmptyState are shared and untouched, so KPI tiles keep their own padding.
B: Report /report done (app/(app)/report, components/report/report-sheet.tsx): A4 white sheet on grey; header (project, survey, date, company), 4 figures, condition share bar, top 10 repairs, work orders, verification summary (or 'No verification yet'), method footnote. Print button = window.print(); @page A4 12mm; my page chrome is print:hidden; sheet uses print:text-black, print-color-adjust exact, break-inside-avoid on rows. The shell (rail/top bar/bottom bar) needs print:hidden from the lead. Thai built in with useT(). eslint clean on my files; typecheck: my files clean, the only errors are in components/map/finding-drawer.tsx (missing `t`, A mid-edit). Not browser/print-preview checked.
B: Thai done with useT() on /plan, /fix-first, /verification, /surveys (incl. Add survey dialog and baseline confirm) and /report: headings, labels, buttons, empty states, toasts, table heads, help lines, work-order status words (components/verification/words.ts). Left as-is: ids, numbers, units, server text (evidence, formula, plan note, decoder labels). NOT translated because shared (lead): SeverityBadge word (High/Medium/Low), ConditionChip band word, KpiTile/EmptyState internals, StatusPill, ProcessingState text. The report prints its own Thai severity/band words. eslint clean; typecheck clean except components/map (A mid-edit earlier). Also fixed leftover md:p-7 in verification results. Not browser-checked.

## Requests to the lead
_(packages, types, shared components: write here and message the lead)_
- A -> lead: /job on phones should hide the app top bar. Needed from the shell: in components/shell (TopBar or app/(app)/layout.tsx) skip rendering TopBar when usePathname() === "/job" and the viewport is below md (e.g. className "max-md:hidden" on TopBar for that route). No change needed on my side: the job card header already has its own back and language buttons, and its -mt-6/-mx-4 offsets cancel main's padding.

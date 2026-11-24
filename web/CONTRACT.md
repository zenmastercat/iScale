# iScale web: contract for sub-agents

The lead owns the foundation. Sub-agents A and B build feature pages on top of it.
**Rule: edit only files inside your own folders (below).** Need a package, a type, an API function, a
shared component or a change to anything you don't own? Write it in `STATUS.md` under *Requests*
and message the lead (pane `w7:p1`). The lead makes the change and tells you. Don't work around it
with a local copy.

Read first: this file, `lib/types.ts`, `lib/api.ts`, `lib/queries.ts`, `lib/selection.tsx`,
`components/shared/index.ts`, and `app/(app)/page.tsx` (Overview, a full example page).
Design PNGs: ask the lead for the path if you don't have them.

## Run it

```bash
# terminal 1, repo root: the backend (never edit civil/)
uv sync && uv run civil serve            # http://127.0.0.1:8765
# terminal 2
cd web && pnpm dev                       # http://localhost:3000, /api proxied to :8765
pnpm lint && pnpm typecheck              # before you report done
```

Sign in at `/login`. Press **Load demo street** on any page with no project.
`pnpm build` (static export to `out/`) is checked by the lead; you can run it too, it doesn't disturb `pnpm dev`.

## Ownership

| Who | Owns (create anything inside) | Routes |
|---|---|---|
| **Lead** | `package.json`, lockfile, all configs, `app/layout.tsx`, `app/globals.css`, `app/(app)/layout.tsx`, `app/(app)/page.tsx`, `app/login/`, `lib/**`, `components/ui/**`, `components/shared/**`, `components/shell/**`, `components/overview/**`, `CONTRACT.md`, `scripts/` | `/`, `/login` |
| **A** (Map, finding drawer, job card) | `app/(app)/map/`, `app/(app)/job/`, `components/map/`, `components/jobcard/` | `/map`, `/job` |
| **B** (Repair plan, Fix first, Verification, Surveys) | `app/(app)/plan/`, `app/(app)/fix-first/`, `app/(app)/verification/`, `app/(app)/surveys/`, `components/plan/`, `components/fix-first/`, `components/verification/`, `components/surveys/` | `/plan`, `/fix-first`, `/verification`, `/surveys` |
| Everyone | `STATUS.md`: your own section only | |

Each route already has a stub `page.tsx` from the lead; replace it. **Only the lead commits.**

## Page rules

- Every page and component file starts with `"use client"`. Static export: no server actions, no route
  handlers, no dynamic `[param]` routes. Pass ids in the query string (`/job?finding=FEF0-0001`).
- `useSearchParams()` needs a `<Suspense>` boundary above it. The `(app)` layout already wraps
  every page in one, so it's fine inside pages under `app/(app)/`.
- Page skeleton:

```tsx
"use client";
import { PageHeader, SurveyGate } from "@/components/shared";
import { useSelection } from "@/lib/selection";

export default function MapPage() {
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader title="Map" crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} actions={/* buttons */ null} />
      <SurveyGate>{/* only renders once the selected survey is processed */}<MapBody /></SurveyGate>
    </>
  );
}
```

- In-app links: `withSel(path, extra?)` from `useSelection()` keeps `?project&survey`:
  `<Link href={withSel("/map", { finding: f.id })}>`. Use `next/link`; never hard-code ids.
- shadcn/ui here is **Base UI**, not Radix: no `asChild`. Use the `render` prop:
  `<SheetTrigger render={<Button variant="outline" />}>Open</SheetTrigger>`.
  Select takes `items`, `value`, `onValueChange(value)`. See `components/shell/top-bar.tsx`.
- Light theme only. Use tokens, never hex (except MapLibre paint, where you use `CONDITION_BANDS[i].color`
  / `SEVERITY[s].color`).

## Routes (`components/shell/nav.ts`, `ROUTES`)

`/` Overview · `/map` Map (`?finding=<fid>` opens the drawer, `?segment=<sid>` focuses a segment) ·
`/fix-first` · `/plan` · `/verification` · `/surveys` · `/job?finding=<fid>` phone job card · `/login`.
The Overview already links to `/map?finding=…`, `/map?segment=…` and `/fix-first`. Please support those params.

## Data: `lib/api.ts`, `lib/queries.ts`

Never call `fetch` yourself, and never build an `/api/...` path by string concatenation in a component:
add the function to `lib/api.ts` (ask the lead), where every id goes through `seg()` (ids from the URL are untrusted). `api()` adds `X-Civil-Scan: 1` to writes, parses JSON, throws
`ApiError(status, detail)` with the server's message, and sends 401s to `/login`.

Prefer the hooks (they share cache and wait until the survey is processed):

| Hook | Returns |
|---|---|
| `useSelection()` | `{ projectId, surveyId, project, survey, otherSurveys, projects, isDemo, setProject, setSurvey, withSel }` |
| `useAnalysis()` | `Analysis { segments, findings, params }` for the selected survey |
| `usePriority(limit?)` | `Priority { items: PriorityItem[], formula }` (Fix first ranking) |
| `useSpotPlan(budget?)` | `SpotPlan`; keeps the previous plan while the budget changes (slider) |
| `useSegmentPlan(budget?)` | `SegmentPlan` |
| `useWorkOrders()` | `WorkOrder[]` for the project |
| `useVerification()` | `Verification \| null` (null until a verify was run) |
| `useMeta()`, `useCatalogLabel()` | catalog; `label("manhole_sunken")` → "Sunken manhole" |
| `useAuthState()` | `{ user, setup_needed }` |

Plain functions for anything else (use with `useQuery`/`useMutation` and the `qk` keys):
`getJobCard(pid,sid,fid)`, `patchFinding(pid,sid,fid,{status,severity,type,note})`,
`addFinding(...)`, `getPlan(pid,sid,mode,budget)`, `createWorkOrder(pid,{survey_id,finding_ids,title})`,
`patchWorkOrder(pid,wid,status)`, `runVerify(pid,{before,after,workorder_id})`, `getVerification(pid)`,
`createSurvey(pid, FormData)`, `waitForSurvey(pid,sid)`, `setBaseline`, `retrySurvey`, `createDemo()`,
`exportUrl(pid,sid,"csv"|"geojson"|"ply")`, `frameUrl(pid,sid,n)`.

After a mutation, invalidate what changed, e.g.
`qc.invalidateQueries({ queryKey: qk.analysis(pid, sid) })`, `qk.workOrders(pid)`, `qk.verification(pid)`,
`qk.priority(pid, sid)`, and `["project", pid]` (prefix: everything of that project).

### Facts about the data (from the real demo responses)

- Findings: `severity` is `null` for **assets** (signs, trees, poles). Defects have high/medium/low.
  `isOpenDefect(f)` in `lib/chainage.ts` = defect and not fixed/verified/dismissed.
- `finding.evidence` is a ready sentence ("depression 7.8 cm deep, 0.87 m across, 31.1 L missing material").
- `finding.source`: `geometry` → "Measured", `decoder` → "Measured + detector", `manual` → "Tagged by hand"
  (`evidenceSource()` in `components/overview/fix-first-table.tsx`; ask if you want it moved to shared).
- Two currencies: plan/priority/work-order costs are **USD** (`plan.currency`), shown as `USD 2,585`.
  Materials-only costs (`finding.cost`, `priority.materials`, job card) are **THB**, shown as `฿1,645`
  (`<Money style="symbol" symbol={cost.symbol} />`).
- `segment.coords` are `[lon, lat]`; findings have `lat`/`lon`. Chainage of a finding: `findingChainage(f, segments)`.
- Plan with budget: `items` fit, `deferred` don't; `total` includes `mobilization` (USD 1,200 on the demo).
- Verify needs a before survey (baseline) and an after survey: `project.baseline` and the other survey in
  `project.survey_list`. Result statuses: `verified | not_fixed | not_covered`.
- Work-order flow: create (findings → `planned`) → PATCH `completed` (→ `fixed`) → verify (→ `verified`/`not_fixed`).
- Job card `location.photo` is `null` on the demo (no video frames). Show a placeholder.
- Demo surveys take ~20 s to process; `useSelection()` polls the project while any survey is running.

## Shared components (`@/components/shared`)

| Component | Props | Notes |
|---|---|---|
| `SeverityBadge` | `severity: Severity \| null`, `size?: "sm" \| "md"` | colour + shape + word; renders nothing for null |
| `SeverityIcon` | `severity`, `size?`, `title?` | ▲ high, ● medium, ▼ low; give `title` if it stands alone |
| `SEVERITY` | record | `{ label, text, bg, fill, color }` per severity |
| `ConditionChip` | `score: number \| null`, `showLabel?` | swatch + score + band word |
| `StatusPill` | `status: FindingStatus \| VerifyStatus` | open, planned, fixed, verified, not_fixed, not_covered, dismissed; icon + word |
| `KpiTile` | `label, value, unit?, sub?` | value pre-formatted |
| `EmptyState` | `icon?, title, description?, action?` | |
| `ProcessingState` | `survey?, action?` | queued / running stage / failed |
| `SurveyGate` | `children` | loading → no project (demo button) → processing → children |
| `PageHeader` | `title, crumb?, actions?` | |
| `Num` | `value, digits?, unit?` | Plex Mono tabular |
| `Money` | `amount, currency?, style?: "code" \| "symbol", symbol?, digits?` | |
| `DemoButton` | `variant?` | POST /api/demo and select it |

Helpers: `lib/format.ts` (`formatNumber, formatMoney, formatLength, formatChainage, formatCm, formatPercent,
formatDate, humanize`), `lib/condition.ts` (`CONDITION_BANDS, bandFor, routeCondition, conditionShares`).
UI kit: `components/ui/*` (button, card, badge, sheet, slider, tabs, dialog, table, skeleton, sonner, select, tooltip).
Toasts: `import { toast } from "sonner"`.

Installed packages you may import: `@tanstack/react-query`, `react-map-gl` (use `react-map-gl/maplibre`),
`maplibre-gl` (import `maplibre-gl/dist/maplibre-gl.css` in your map component), `recharts`, `lucide-react`,
`three`, `@react-three/fiber`, `@react-three/drei`, `sonner`. **Don't edit `package.json`.**

## Design tokens (`app/globals.css`)

`bg-brand` #102D50 · `text-accent-blue` #347BC3 · `text-link` (accent darkened for text) ·
`grey-50…900` · `sev-{high,medium,low}` (marks), `-fg` (text), `-bg` (fill) ·
`bg-cond-{good,satisfactory,fair,poor,very-poor,failed,none}` · radius 6px (`rounded-lg`) ·
`class="num"` on every figure (Plex Mono, tabular-nums).

## Accessibility (checked at review)

Real `<button>`/`<Link>`, never clickable divs. `aria-label` on icon-only buttons. Labels on inputs.
Touch targets ≥ 44 px (`min-h-11`, `size-11`). Text contrast ≥ 4.5:1 (use the `-fg` tokens on tinted
fills; `text-muted-foreground` is OK on white and grey-50). Never colour alone: severity has a shape and a
word, condition has a number or word. The bottom bar covers 56 px on phones; `main` already pads for it.

## Reporting

When a piece works, add it to your section of `STATUS.md` (what, route, anything the lead must check)
and message the lead. The lead runs `pnpm build`, fixes cross-cutting lint/type issues and commits.

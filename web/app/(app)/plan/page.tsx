"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardList } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { BudgetBar } from "@/components/plan/budget-bar";
import { SegmentTable, SpotTable } from "@/components/plan/plan-table";
import { usePlan } from "@/components/plan/use-plan";
import { EmptyState } from "@/components/shared/empty-state";
import { KpiTile } from "@/components/shared/kpi-tile";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { createWorkOrder, qk } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import { useSelection } from "@/lib/selection";
import type { SegmentPlan, SpotPlan } from "@/lib/types";
import { cn } from "@/lib/utils";

type Mode = "spot" | "segment";
const DEBOUNCE_MS = 150;

function usePlanScreen() {
  const { projectId, surveyId, withSel } = useSelection();
  const qc = useQueryClient();
  const [mode, setModeRaw] = useState<Mode>("spot");
  // null = no limit (everything funded)
  const [budget, setBudget] = useState<number | null>(null);
  const [debounced, setDebounced] = useState<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(budget), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [budget]);

  const spotAll = usePlan("spot", null);
  const segAll = usePlan("segment", null);
  const spot = usePlan("spot", mode === "spot" ? debounced : null);
  const seg = usePlan("segment", mode === "segment" ? debounced : null);

  const all = mode === "spot" ? spotAll.data : segAll.data;
  const unlimited = all?.total ?? 0;
  const max = Math.max(100, Math.ceil((unlimited * 1.1) / 100) * 100);
  const shown = budget ?? unlimited;
  const currency = all?.currency ?? "USD";

  const active = mode === "spot" ? spot : seg;
  const plan: SpotPlan | SegmentPlan | undefined = active.data;
  const stale = active.isFetching;

  const spotPlan = plan?.mode === "spot" ? plan : null;
  const fundedIds = useMemo(() => spotPlan?.items.map((i) => i.finding_id) ?? [], [spotPlan]);

  const makeOrder = useMutation({
    mutationFn: () => createWorkOrder(projectId!, { survey_id: surveyId!, finding_ids: fundedIds }),
    onSuccess: (wo) => {
      qc.invalidateQueries({ queryKey: qk.workOrders(projectId!) });
      qc.invalidateQueries({ queryKey: qk.analysis(projectId!, surveyId!) });
      qc.invalidateQueries({ queryKey: qk.priority(projectId!, surveyId!) });
      qc.invalidateQueries({ queryKey: ["project", projectId!, "survey", surveyId!, "plan"] });
      toast.success(`Work order ${wo.id} created with ${wo.items.length} repairs`);
    },
    onError: (e: Error) => toast.error(`Could not create the work order: ${e.message}`),
  });

  function setBudgetClamped(v: number) {
    setBudget(v >= unlimited ? null : Math.max(0, v));
  }

  function setMode(m: Mode) {
    // the two modes have different totals, so a budget set for one is meaningless in the other
    setModeRaw(m);
    setBudget(null);
    setDebounced(null);
  }

  return {
    mode, setMode, budget, setBudget, unlimited, max, shown, currency, plan, stale, spotPlan, fundedIds,
    makeOrder, setBudgetClamped, spotAll, segAll, withSel,
  };
}

type PlanScreen = ReturnType<typeof usePlanScreen>;

function PlanBody({ s }: { s: PlanScreen }) {
  const { mode, setMode, budget, setBudget, unlimited, max, shown, currency, plan, stale, spotPlan,
    makeOrder, setBudgetClamped, spotAll, segAll, withSel } = s;
  const all = mode === "spot" ? spotAll.data : segAll.data;
  if (spotAll.isError || segAll.isError)
    return (
      <p role="alert" className="text-sev-high-fg">
        Could not load the plan: {(spotAll.error ?? segAll.error)?.message}
      </p>
    );
  if (!plan || !all) return <Skeleton className="h-96 w-full" />;

  const fundedCost = plan.total;
  const deferredCost = plan.deferred.reduce((a, i) => a + i.cost, 0);
  const high = spotPlan
    ? {
        covered: spotPlan.items.filter((i) => i.severity === "high").length,
        total: [...spotPlan.items, ...spotPlan.deferred].filter((i) => i.severity === "high").length,
      }
    : null;
  const presets = [0.25, 0.5, 0.75].map((p) => ({ label: `${p * 100}%`, value: Math.round((unlimited * p) / 50) * 50 }));

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Budget" className="rounded-lg border bg-card p-5 md:p-7">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-muted-foreground">Budget</p>
            <p className="num text-5xl font-semibold tracking-tight text-brand md:text-6xl" aria-live="polite">
              {budget === null ? "No limit" : formatMoney(shown, currency)}
            </p>
            {budget === null && (
              <p className="num mt-1 text-sm text-muted-foreground">Everything costs {formatMoney(unlimited, currency)}</p>
            )}
          </div>
          <div
            role="group"
            aria-label="Plan mode"
            className="inline-flex rounded-lg border p-0.5"
          >
            {(["spot", "segment"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
                className={cn(
                  "min-h-11 rounded-md px-4 text-sm font-medium",
                  mode === m ? "bg-brand text-white" : "text-grey-700 hover:bg-grey-50",
                )}
              >
                {m === "spot" ? "Spot repairs" : "Whole segments"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex min-h-11 items-center">
          <Slider
            aria-label="Budget"
            min={0}
            max={max}
            step={50}
            value={[shown]}
            onValueChange={(v) => setBudgetClamped(Array.isArray(v) ? v[0] : v)}
          />
        </div>
        <div className="num mt-1 flex justify-between text-sm text-muted-foreground" aria-hidden>
          <span>0</span>
          <span>{formatNumber(max / 2)}</span>
          <span>{formatNumber(max)}</span>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Drag to set how much you can spend. Repairs are funded in priority order until the money runs out; the rest
          wait. The mobilisation fee is paid once.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {presets.map((p) => (
            <Button key={p.label} variant="outline" className="min-h-11" onClick={() => setBudgetClamped(p.value)}>
              {p.label} · <span className="num ml-1">{formatNumber(p.value)}</span>
            </Button>
          ))}
          <Button variant={budget === null ? "default" : "outline"} className="min-h-11" onClick={() => setBudget(null)}>
            No limit
          </Button>
        </div>

        <div className={cn("mt-6 transition-opacity", stale && "opacity-70")} aria-busy={stale}>
          <BudgetBar funded={fundedCost} deferred={deferredCost} currency={currency} />
        </div>
      </section>

      <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity", stale && "opacity-70")}>
        <KpiTile
          label="Funded"
          value={plan.items.length}
          sub={<>{mode === "spot" ? "repairs" : "segments"} · <span className="num">{formatMoney(fundedCost, currency)}</span></>}
        />
        <KpiTile
          label="Deferred"
          value={plan.deferred.length}
          sub={<>{mode === "spot" ? "repairs" : "segments"} · <span className="num">{formatMoney(deferredCost, currency)}</span></>}
        />
        <KpiTile
          label="Mobilisation"
          value={spotPlan ? formatNumber(spotPlan.mobilization) : "–"}
          unit={spotPlan ? currency : undefined}
          sub={spotPlan ? "one-off, included in the funded cost" : "not applied to whole segments"}
        />
        <KpiTile
          label="High severity covered"
          value={high ? `${high.covered}/${high.total}` : "–"}
          sub={high ? (high.covered === high.total ? "all high-severity defects funded" : "high-severity defects still deferred") : "spot repairs only"}
        />
      </div>

      <section aria-label="Plan items" className="rounded-lg border bg-card p-5 md:p-7">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-grey-900">
            {mode === "spot" ? "Repairs" : "Segments"}{" "}
            <span className="num text-sm font-normal text-muted-foreground">
              {plan.items.length} funded · {plan.deferred.length} deferred
            </span>
          </h2>
        </div>
        {makeOrder.isSuccess && (
          <p role="status" className="mb-4 text-sm">
            Work order <span className="num font-medium">{makeOrder.data.id}</span> created.{" "}
            <Link href={withSel("/verification")} className="font-medium text-link underline underline-offset-4">
              Track it in Verification
            </Link>
          </p>
        )}
        {plan.items.length + plan.deferred.length === 0 ? (
          <EmptyState title="Nothing to repair" description="This survey has no open defects to plan." />
        ) : plan.mode === "spot" ? (
          <SpotTable items={plan.items} deferred={plan.deferred} currency={currency} />
        ) : (
          <SegmentTable items={plan.items} deferred={plan.deferred} currency={currency} />
        )}
        <p className="mt-4 text-sm text-muted-foreground">{plan.note}</p>
      </section>
    </div>
  );
}

export default function RepairPlanPage() {
  const { project, survey } = useSelection();
  const screen = usePlanScreen();
  const { mode, fundedIds, makeOrder, stale } = screen;
  return (
    <>
      <PageHeader
        title="Repair plan"
        crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined}
        actions={
          survey?.status === "done" && mode === "spot" ? (
            <Button
              className="min-h-11"
              disabled={!fundedIds.length || makeOrder.isPending || stale}
              onClick={() => makeOrder.mutate()}
            >
              <ClipboardList aria-hidden />
              {makeOrder.isPending ? "Creating…" : `Create work order (${fundedIds.length})`}
            </Button>
          ) : null
        }
      />
      <SurveyGate>
        <PlanBody s={screen} />
      </SurveyGate>
    </>
  );
}

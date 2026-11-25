"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardList } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { BudgetChart } from "@/components/plan/budget-chart";
import { BudgetBar } from "@/components/plan/budget-bar";
import { SegmentTable, SpotTable } from "@/components/plan/plan-table";
import { usePlan, zeroBudgetPlan } from "@/components/plan/use-plan";
import { EmptyState } from "@/components/shared/empty-state";
import { KpiTile } from "@/components/shared/kpi-tile";
import { PageHeader } from "@/components/shared/page-header";
import { QueryError } from "@/components/surveys/query-error";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { createWorkOrder, qk } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { SegmentPlan, SpotPlan } from "@/lib/types";
import { cn } from "@/lib/utils";

type Mode = "spot" | "segment";
const DEBOUNCE_MS = 150;

function usePlanScreen() {
  const t = useT();
  const { projectId, surveyId, withSel } = useSelection();
  const qc = useQueryClient();
  const [mode, setModeRaw] = useState<Mode>("spot");
  // null = no limit (everything funded)
  const [budget, setBudget] = useState<number | null>(null);
  const [debounced, setDebounced] = useState<number | null>(null);

  useEffect(() => {
    const h = setTimeout(() => setDebounced(budget), DEBOUNCE_MS);
    return () => clearTimeout(h);
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
  const zero = debounced === 0 && !!all;
  const plan: SpotPlan | SegmentPlan | undefined = zero ? zeroBudgetPlan(all) : active.data;
  const stale = zero ? false : active.isFetching;

  const spotPlan = plan?.mode === "spot" ? plan : null;
  const fundedIds = useMemo(() => spotPlan?.items.map((i) => i.finding_id) ?? [], [spotPlan]);

  const makeOrder = useMutation({
    mutationFn: () => createWorkOrder(projectId!, { survey_id: surveyId!, finding_ids: fundedIds }),
    onSuccess: (wo) => {
      qc.invalidateQueries({ queryKey: qk.workOrders(projectId!) });
      qc.invalidateQueries({ queryKey: qk.analysis(projectId!, surveyId!) });
      qc.invalidateQueries({ queryKey: qk.priority(projectId!, surveyId!) });
      qc.invalidateQueries({ queryKey: ["project", projectId!, "survey", surveyId!, "plan"] });
      toast.success(t(`Work order ${wo.id} created with ${wo.items.length} repairs`, `สร้างใบสั่งงาน ${wo.id} แล้ว มี ${wo.items.length} งานซ่อม`));
    },
    onError: (e: Error) => toast.error(`${t("Could not create the work order", "สร้างใบสั่งงานไม่ได้")}: ${e.message}`),
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
    t, mode, setMode, budget, setBudget, unlimited, max, shown, currency, plan, stale, spotPlan, fundedIds,
    makeOrder, setBudgetClamped, spotAll, segAll, withSel,
  };
}

type PlanScreen = ReturnType<typeof usePlanScreen>;

function PlanBody({ s }: { s: PlanScreen }) {
  const { t, mode, setMode, budget, setBudget, unlimited, max, shown, currency, plan, stale, spotPlan,
    makeOrder, setBudgetClamped, spotAll, segAll, withSel } = s;
  const all = mode === "spot" ? spotAll.data : segAll.data;
  if (spotAll.isError || segAll.isError)
    return (
      <QueryError
        what={t("Could not load the plan", "โหลดแผนซ่อมไม่ได้")}
        error={spotAll.error ?? segAll.error}
        onRetry={() => { spotAll.refetch(); segAll.refetch(); }}
      />
    );
  if (!plan || !all) return <Skeleton className="h-96 w-full" />;
  if (all.items.length + all.deferred.length === 0)
    return (
      <EmptyState
        title={t("No open defects to repair", "ไม่มีข้อบกพร่องที่ต้องซ่อม")}
        description={t("This survey has no open defects, so there is nothing to plan or budget.", "การสำรวจนี้ไม่มีข้อบกพร่องค้าง จึงไม่มีอะไรต้องวางแผนหรือตั้งงบ")}
      />
    );

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
    <div className="flex flex-col gap-6 md:gap-4">
      <section aria-label={t("Budget", "งบประมาณ")} className="rounded-lg border bg-card p-5 md:p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-muted-foreground">{t("Budget", "งบประมาณ")}</p>
            <p className="num text-5xl font-semibold tracking-tight text-brand md:text-5xl" aria-live="polite">
              {budget === null ? t("No limit", "ไม่จำกัด") : formatMoney(shown, currency)}
            </p>
            {budget === null && (
              <p className="num mt-1 text-sm text-muted-foreground">{t("Everything costs", "ซ่อมทั้งหมดใช้")} {formatMoney(unlimited, currency)}</p>
            )}
          </div>
          <div
            role="group"
            aria-label={t("Plan mode", "รูปแบบแผน")}
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
                {m === "spot" ? t("Spot repairs", "ซ่อมเป็นจุด") : t("Whole segments", "ซ่อมทั้งช่วง")}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex min-h-11 items-center">
          <Slider
            aria-label={t("Budget", "งบประมาณ")}
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
        {budget === 0 && (
          <p role="status" className="mt-2 text-sm font-medium text-sev-medium-fg">
            {t("Budget is 0: nothing is funded. Every repair is deferred.", "งบเป็น 0: ไม่มีงานซ่อมได้รับงบ ทุกงานถูกเลื่อนไว้")}
          </p>
        )}
        <p className="mt-2 text-sm text-muted-foreground">
          {t(
            "Drag to set how much you can spend. Repairs are funded in priority order until the money runs out; the rest wait. The mobilisation fee is paid once.",
            "ลากเพื่อกำหนดงบที่ใช้ได้ งานซ่อมจะได้รับงบตามลำดับความสำคัญจนงบหมด งานที่เหลือรอก่อน ค่าเคลื่อนย้ายจ่ายครั้งเดียว",
          )}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {presets.map((p) => (
            <Button key={p.label} variant="outline" className="min-h-11" onClick={() => setBudgetClamped(p.value)}>
              {p.label} · <span className="num ml-1">{formatNumber(p.value)}</span>
            </Button>
          ))}
          <Button variant={budget === null ? "default" : "outline"} className="min-h-11" onClick={() => setBudget(null)}>
            {t("No limit", "ไม่จำกัด")}
          </Button>
        </div>

        <div className={cn("mt-6 transition-opacity", stale && "opacity-70")} aria-busy={stale}>
          <BudgetBar funded={fundedCost} deferred={deferredCost} currency={currency} />
        </div>
      </section>

      <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity", stale && "opacity-70")}>
        <KpiTile
          label={t("Funded", "ได้รับงบ")}
          value={plan.items.length}
          sub={<>{mode === "spot" ? t("repairs", "งานซ่อม") : t("segments", "ช่วง")} · <span className="num">{formatMoney(fundedCost, currency)}</span></>}
        />
        <KpiTile
          label={t("Deferred", "เลื่อนไว้")}
          value={plan.deferred.length}
          sub={<>{mode === "spot" ? t("repairs", "งานซ่อม") : t("segments", "ช่วง")} · <span className="num">{formatMoney(deferredCost, currency)}</span></>}
        />
        <KpiTile
          label={t("Mobilisation", "ค่าเคลื่อนย้าย")}
          value={spotPlan ? formatNumber(spotPlan.mobilization) : "–"}
          unit={spotPlan ? currency : undefined}
          sub={spotPlan ? t("one-off, included in the funded cost", "จ่ายครั้งเดียว รวมในยอดที่ได้รับงบ") : t("not applied to whole segments", "ไม่คิดกับการซ่อมทั้งช่วง")}
        />
        <KpiTile
          label={t("High severity covered", "งานรุนแรงสูงที่ได้รับงบ")}
          value={high ? `${high.covered}/${high.total}` : "–"}
          sub={high ? (high.covered === high.total ? t("all high-severity defects funded", "ได้รับงบครบทุกจุดที่รุนแรงสูง") : t("high-severity defects still deferred", "ยังมีจุดรุนแรงสูงที่เลื่อนไว้")) : t("spot repairs only", "เฉพาะซ่อมเป็นจุด")}
        />
      </div>

      {spotAll.data?.mode === "spot" && <BudgetChart all={spotAll.data} max={max} current={shown} />}

      <section aria-label={t("Plan items", "รายการในแผน")} className="rounded-lg border bg-card p-5 md:p-4">
        <div className="mb-5 md:mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg md:text-base font-semibold text-grey-900">
            {mode === "spot" ? t("Repairs", "งานซ่อม") : t("Segments", "ช่วงถนน")}{" "}
            <span className="num text-sm font-normal text-muted-foreground">
              {plan.items.length} {t("funded", "ได้รับงบ")} · {plan.deferred.length} {t("deferred", "เลื่อนไว้")}
            </span>
          </h2>
        </div>
        {makeOrder.isSuccess && (
          <p role="status" className="mb-4 text-sm">
            {t("Work order", "ใบสั่งงาน")} <span className="num font-medium">{makeOrder.data.id}</span> {t("created.", "สร้างแล้ว")}{" "}
            <Link href={withSel("/verification")} className="font-medium text-link underline underline-offset-4">
              {t("Track it in Verification", "ติดตามในหน้าตรวจยืนยัน")}
            </Link>
          </p>
        )}
        {plan.items.length + plan.deferred.length === 0 ? (
          <EmptyState title={t("Nothing to repair", "ไม่มีงานซ่อม")} description={t("This survey has no open defects to plan.", "การสำรวจนี้ไม่มีข้อบกพร่องที่ต้องวางแผนซ่อม")} />
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
  const { t, mode, fundedIds, makeOrder, stale } = screen;
  return (
    <>
      <PageHeader
        title={t("Repair plan", "แผนซ่อม")}
        crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined}
        actions={
          survey?.status === "done" && mode === "spot" ? (
            <Button
              className="min-h-11"
              disabled={!fundedIds.length || makeOrder.isPending || stale}
              onClick={() => makeOrder.mutate()}
            >
              <ClipboardList aria-hidden />
              {makeOrder.isPending ? t("Creating…", "กำลังสร้าง…") : `${t("Create work order", "สร้างใบสั่งงาน")} (${fundedIds.length})`}
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

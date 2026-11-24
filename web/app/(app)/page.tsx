"use client";
import Link from "next/link";
import { useMemo } from "react";
import { ChainageStrip } from "@/components/overview/chainage-strip";
import { ConditionShareBar } from "@/components/overview/condition-share-bar";
import { FixFirstTable } from "@/components/overview/fix-first-table";
import { SummarySentence } from "@/components/overview/summary-sentence";
import { KpiTile } from "@/components/shared/kpi-tile";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { isOpenDefect } from "@/lib/chainage";
import { bandFor, routeCondition } from "@/lib/condition";
import { formatMoney, formatNumber } from "@/lib/format";
import { useAnalysis, useCatalogLabel, usePriority, useSpotPlan } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

function Card({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5 md:p-7" aria-label={title}>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-grey-900">{title}</h2>
        {note && <p className="text-sm text-muted-foreground">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function OverviewBody() {
  const { survey, withSel } = useSelection();
  const analysis = useAnalysis();
  const plan = useSpotPlan();
  const priority = usePriority(5);
  const labelFor = useCatalogLabel();

  const stats = useMemo(() => {
    const an = analysis.data;
    if (!an) return null;
    const open = an.findings.filter(isOpenDefect);
    const by = { high: 0, medium: 0, low: 0 };
    for (const f of open) by[f.severity!]++;
    return {
      open,
      by,
      assets: an.findings.filter((f) => !f.severity).length,
      score: routeCondition(an.segments),
      lengthM: survey?.stats?.length_m ?? an.segments.reduce((a, s) => a + s.length_m, 0),
      findingsById: new Map(an.findings.map((f) => [f.id, f])),
    };
  }, [analysis.data, survey]);

  if (analysis.isError) return <p role="alert" className="text-sev-high-fg">Could not load the analysis: {analysis.error.message}</p>;
  if (!analysis.data || !stats) return <Skeleton className="h-96 w-full" />;
  const an = analysis.data;
  const currency = plan.data?.currency ?? "USD";
  const cost = plan.data ? plan.data.total : null;

  return (
    <div className="flex flex-col gap-6">
      <SummarySentence
        lengthM={stats.lengthM}
        score={stats.score}
        open={stats.open.length}
        high={stats.by.high}
        cost={cost}
        currency={currency}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile
          label="Condition index"
          value={stats.score === null ? "–" : formatNumber(stats.score)}
          unit="/100"
          sub={`${bandFor(stats.score).label} · PCI-like, 0–100`}
        />
        <KpiTile
          label="Open defects"
          value={stats.open.length}
          sub={`${stats.by.high} high · ${stats.by.medium} medium · ${stats.by.low} low`}
        />
        <KpiTile
          label="Repair estimate"
          value={cost === null ? "…" : formatNumber(cost)}
          unit={currency}
          sub={plan.data ? `incl. ${formatMoney(plan.data.mobilization, currency)} mobilisation` : " "}
        />
        <KpiTile
          label="Road surveyed"
          value={formatNumber(stats.lengthM)}
          unit="m"
          sub={`${an.segments.length} segments · ${stats.assets} assets on record`}
        />
      </div>

      <Card title="Condition along the route" note="Each block is a 25 m segment · marks above are open defects">
        <ChainageStrip segments={an.segments} findings={an.findings} labelFor={labelFor} />
        <div className="mt-6">
          <ConditionShareBar segments={an.segments} />
        </div>
      </Card>

      <Card title="Fix first" note="Ranked by severity × safety × traffic">
        {priority.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : priority.data?.items.length ? (
          <>
            <FixFirstTable items={priority.data.items.slice(0, 5)} findingsById={stats.findingsById} currency={currency} />
            <Link
              href={withSel("/fix-first")}
              className="mt-4 inline-flex min-h-11 items-center font-medium text-link underline underline-offset-4 hover:text-brand"
            >
              See the full list
            </Link>
          </>
        ) : (
          <p className="text-muted-foreground">Nothing to fix: no open defects.</p>
        )}
      </Card>
    </div>
  );
}

export default function OverviewPage() {
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader
        title="Overview"
        crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined}
      />
      <SurveyGate>
        <OverviewBody />
      </SurveyGate>
    </>
  );
}

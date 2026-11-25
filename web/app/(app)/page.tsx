"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";
import { ChainageStrip } from "@/components/overview/chainage-strip";
import { ConditionShareBar } from "@/components/overview/condition-share-bar";
import { CostByAction } from "@/components/overview/cost-by-action";
import { DefectMatrix } from "@/components/overview/defect-matrix";
import { FixFirstTable } from "@/components/overview/fix-first-table";
import { SegmentChange } from "@/components/overview/segment-change";
import { SegmentDiagram } from "@/components/linear/segment-diagram";
import { getAnalysis, qk } from "@/lib/api";
import { findingsQuery, OPEN_STATUSES } from "@/lib/findings-filter";
import { useT } from "@/lib/i18n";
import { SummarySentence } from "@/components/overview/summary-sentence";
import { HowWeMeasure } from "@/components/shared/how-we-measure";
import { KpiTile } from "@/components/shared/kpi-tile";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { isOpenDefect } from "@/lib/chainage";
import { bandFor, routeCondition } from "@/lib/condition";
import { APP_CURRENCY, formatMoney, formatNumber } from "@/lib/format";
import { useAnalysis, useCatalogLabel, usePriority, useSpotPlan } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

function Card({ title, note, className, children }: { title: string; note?: string; className?: string; children: React.ReactNode }) {
  return (
    <section className={`min-w-0 rounded-lg border bg-card p-5 md:p-4 ${className ?? ""}`} aria-label={title}>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 md:mb-3">
        <h2 className="text-lg font-semibold text-grey-900 md:text-base">{title}</h2>
        {note && <p className="text-sm text-muted-foreground md:text-xs">{note}</p>}
      </div>
      {children}
    </section>
  );
}

/** The survey to compare against: baseline ↔ the newest other processed survey. */
function useComparison() {
  const { project, projectId, surveyId } = useSelection();
  const base = project?.baseline;
  const others = (project?.survey_list ?? []).filter((s) => s.id !== base && s.status === "done").sort((a, b) => b.created - a.created);
  const beforeId = base;
  const afterId = surveyId && surveyId !== base ? surveyId : others[0]?.id;
  const enabled = !!projectId && !!beforeId && !!afterId && beforeId !== afterId;
  const before = useQuery({ queryKey: qk.analysis(projectId ?? "", beforeId ?? ""), queryFn: () => getAnalysis(projectId!, beforeId!), enabled });
  const after = useQuery({ queryKey: qk.analysis(projectId ?? "", afterId ?? ""), queryFn: () => getAnalysis(projectId!, afterId!), enabled });
  const name = (id?: string) => project?.survey_list.find((s) => s.id === id)?.name ?? "";
  if (!enabled || !before.data || !after.data) return null;
  return { before: before.data.segments, after: after.data.segments, beforeName: name(beforeId), afterName: name(afterId) };
}

function OverviewBody() {
  const { survey, withSel } = useSelection();
  const analysis = useAnalysis();
  const plan = useSpotPlan();
  const priority = usePriority(5);
  const labelFor = useCatalogLabel();
  const comparison = useComparison();
  const t = useT();

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
  const currency = plan.data?.currency ?? APP_CURRENCY;
  const cost = plan.data ? plan.data.total : null;

  return (
    <div className="flex flex-col gap-6 md:gap-4">
      <SummarySentence
        lengthM={stats.lengthM}
        score={stats.score}
        open={stats.open.length}
        high={stats.by.high}
        cost={cost}
        currency={currency}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:gap-3 xl:grid-cols-4">
        <KpiTile
          label={t("Condition index", "ดัชนีสภาพถนน")}
          value={stats.score === null ? "–" : formatNumber(stats.score)}
          unit="/100"
          sub={`${t(bandFor(stats.score).label, bandFor(stats.score).th)} · ${t("PCI-like, 0–100", "คล้าย PCI, 0–100")}`}
          href={withSel("/map")}
        />
        <KpiTile
          label={t("Open defects", "ข้อบกพร่องที่ยังไม่ซ่อม")}
          value={stats.open.length}
          sub={t(`${stats.by.high} high · ${stats.by.medium} medium · ${stats.by.low} low`, `สูง ${stats.by.high} · กลาง ${stats.by.medium} · ต่ำ ${stats.by.low}`)}
          href={withSel("/findings", findingsQuery({ kind: "defect", status: OPEN_STATUSES }))}
        />
        <KpiTile
          label={t("Repair estimate", "ประมาณค่าซ่อม")}
          value={cost === null ? "…" : formatMoney(cost, currency)}
          sub={plan.data ? t(`incl. ${formatMoney(plan.data.mobilization, currency)} mobilisation`, `รวมค่าเคลื่อนย้าย ${formatMoney(plan.data.mobilization, currency)}`) : " "}
          href={withSel("/plan")}
        />
        <KpiTile
          label={t("Road surveyed", "ระยะทางที่สำรวจ")}
          value={formatNumber(stats.lengthM)}
          unit="m"
          sub={t(`${an.segments.length} segments · ${stats.assets} assets on record`, `${an.segments.length} ช่วง · ทรัพย์สิน ${stats.assets} รายการ`)}
          href={withSel("/findings", findingsQuery({ kind: "asset" }))}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 md:gap-4 xl:grid-cols-5">
        <Card title={t("Condition along the route", "สภาพถนนตลอดเส้นทาง")} note={t("25 m segments · marks are open defects", "ช่วงละ 25 ม. · สัญลักษณ์คือจุดที่ยังไม่ซ่อม")} className="xl:col-span-3">
          <ChainageStrip segments={an.segments} findings={an.findings} labelFor={labelFor} />
          <div className="mt-6 md:mt-4">
            <ConditionShareBar segments={an.segments} />
          </div>
        </Card>
        <Card title={t("Open defects by type", "ข้อบกพร่องตามชนิด")} note={t("Counts open the list", "กดตัวเลขเพื่อดูรายการ")} className="xl:col-span-2">
          <DefectMatrix findings={an.findings} labelFor={labelFor} withSel={withSel} />
        </Card>
      </div>

      <Card
        title={t("Segment line diagram", "แผนภาพเส้นตรงรายช่วง")}
        note={t("Condition, defects, width, coverage and roughness along the chainage", "สภาพ ข้อบกพร่อง ความกว้าง ความครอบคลุม และความขรุขระ ตามระยะทาง")}
      >
        <SegmentDiagram segments={an.segments} findings={an.findings} labelFor={labelFor} withSel={withSel} />
      </Card>

      <div className={`grid grid-cols-1 gap-6 md:gap-4 ${comparison ? "xl:grid-cols-2" : ""}`}>
        <Card title={t("Repair cost by action", "ค่าซ่อมตามวิธีซ่อม")} note={t(`All open repairs · ${currency}`, `งานซ่อมทั้งหมด · ${currency}`)}>
          {plan.data ? <CostByAction plan={plan.data} /> : <Skeleton className="h-40 w-full" />}
        </Card>
        {comparison && (
          <Card title={t("Condition change per segment", "การเปลี่ยนแปลงสภาพแต่ละช่วง")} note={`${comparison.beforeName} → ${comparison.afterName}`}>
            <SegmentChange {...comparison} withSel={withSel} />
          </Card>
        )}
      </div>

      <Card title={t("Fix first", "ซ่อมก่อน")} note={t("Ranked by severity × safety × traffic", "เรียงตามความรุนแรง × ความปลอดภัย × จราจร")}>
        {priority.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : priority.data?.items.length ? (
          <>
            <FixFirstTable items={priority.data.items.slice(0, 5)} findingsById={stats.findingsById} currency={currency} />
            <Link
              href={withSel("/fix-first")}
              className="mt-4 inline-flex min-h-11 items-center font-medium text-link underline underline-offset-4 hover:text-brand"
            >
              {t("See the full list", "ดูรายการทั้งหมด")}
            </Link>
          </>
        ) : (
          <p className="text-muted-foreground">{t("Nothing to fix: no open defects.", "ไม่มีจุดที่ต้องซ่อม")}</p>
        )}
      </Card>
    </div>
  );
}

export default function OverviewPage() {
  const { project, survey } = useSelection();
  const t = useT();
  return (
    <>
      <PageHeader
        title={t("Overview", "ภาพรวม")}
        crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined}
        actions={<HowWeMeasure />}
      />
      <SurveyGate>
        <OverviewBody />
      </SurveyGate>
    </>
  );
}

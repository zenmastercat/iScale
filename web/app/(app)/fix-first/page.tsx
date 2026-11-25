"use client";
import { useMemo } from "react";
import { QueryError } from "@/components/surveys/query-error";
import { SummaryStrip } from "@/components/fix-first/summary-strip";
import { RankingTable } from "@/components/fix-first/ranking-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { FixFirstSkeleton } from "@/components/skeletons";
import { Download } from "lucide-react";
import { exportUrl } from "@/lib/api";
import { useAnalysis, usePriority } from "@/lib/queries";
import { APP_CURRENCY } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

function FixFirstBody() {
  const t = useT();
  const priority = usePriority(200);
  const analysis = useAnalysis();
  const byId = useMemo(() => new Map((analysis.data?.findings ?? []).map((f) => [f.id, f])), [analysis.data]);

  if (priority.isError)
    return <QueryError what={t("Could not load the ranking", "โหลดอันดับไม่ได้")} error={priority.error} onRetry={() => priority.refetch()} />;
  if (!priority.data) return <FixFirstSkeleton />;
  const items = priority.data.items;
  if (!items.length) return <EmptyState title={t("Nothing to fix", "ไม่มีอะไรต้องซ่อม")} description={t("No open defects in this survey, and no shared pins nearby.", "ไม่มีข้อบกพร่องค้างในการสำรวจนี้ และไม่มีหมุดที่แชร์ใกล้เคียง")} />;

  return (
    <section className="rounded-lg border bg-card p-5 md:p-4" aria-label={t("Ranked defects", "ข้อบกพร่องเรียงตามลำดับ")}>
      <p className="mb-5 text-sm text-muted-foreground">
        {t("Ranked by", "จัดอันดับโดย")}: <span className="font-medium text-grey-900">{priority.data.formula}</span>
      </p>
      <SummaryStrip items={items} currency={APP_CURRENCY} />
      <RankingTable items={items} findingsById={byId} currency={APP_CURRENCY} />
    </section>
  );
}

export default function FixFirstPage() {
  const t = useT();
  const { projectId, surveyId, project, survey } = useSelection();
  return (
    <>
      <PageHeader
        title={t("Fix first", "ซ่อมก่อน")}
        crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined}
        actions={
          projectId && surveyId && survey?.status === "done" ? (
            <>
              {(["csv", "geojson"] as const).map((fmt) => (
                <a
                  key={fmt}
                  href={exportUrl(projectId, surveyId, fmt)}
                  download
                  className="inline-flex min-h-11 items-center gap-2 rounded-lg border bg-card px-4 text-sm font-medium hover:bg-grey-50"
                >
                  <Download aria-hidden className="size-4" />
                  {t("Export", "ส่งออก")} {fmt === "csv" ? "CSV" : "GeoJSON"}
                </a>
              ))}
            </>
          ) : null
        }
      />
      <SurveyGate>
        <FixFirstBody />
      </SurveyGate>
    </>
  );
}

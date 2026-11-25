"use client";
import { useMemo } from "react";
import { RankingTable } from "@/components/fix-first/ranking-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { Download } from "lucide-react";
import { exportUrl } from "@/lib/api";
import { useAnalysis, usePriority } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

function FixFirstBody() {
  const t = useT();
  const priority = usePriority(200);
  const analysis = useAnalysis();
  const byId = useMemo(() => new Map((analysis.data?.findings ?? []).map((f) => [f.id, f])), [analysis.data]);

  if (priority.isError)
    return <p role="alert" className="text-sev-high-fg">{t("Could not load the ranking", "โหลดอันดับไม่ได้")}: {priority.error.message}</p>;
  if (!priority.data) return <Skeleton className="h-96 w-full" />;
  const items = priority.data.items;
  if (!items.length) return <EmptyState title={t("Nothing to fix", "ไม่มีอะไรต้องซ่อม")} description={t("No open defects in this survey, and no shared pins nearby.", "ไม่มีข้อบกพร่องค้างในการสำรวจนี้ และไม่มีหมุดที่แชร์ใกล้เคียง")} />;

  return (
    <section className="rounded-lg border bg-card p-5 md:p-4" aria-label={t("Ranked defects", "ข้อบกพร่องเรียงตามลำดับ")}>
      <p className="mb-5 text-sm text-muted-foreground">
        {t("Ranked by", "จัดอันดับโดย")}: <span className="font-medium text-grey-900">{priority.data.formula}</span>
      </p>
      <RankingTable items={items} findingsById={byId} currency="USD" />
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

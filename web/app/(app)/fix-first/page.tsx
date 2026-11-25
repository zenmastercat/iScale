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
import { useSelection } from "@/lib/selection";

function FixFirstBody() {
  const priority = usePriority(200);
  const analysis = useAnalysis();
  const byId = useMemo(() => new Map((analysis.data?.findings ?? []).map((f) => [f.id, f])), [analysis.data]);

  if (priority.isError)
    return <p role="alert" className="text-sev-high-fg">Could not load the ranking: {priority.error.message}</p>;
  if (!priority.data) return <Skeleton className="h-96 w-full" />;
  const items = priority.data.items;
  if (!items.length) return <EmptyState title="Nothing to fix" description="No open defects in this survey, and no shared pins nearby." />;

  return (
    <section className="rounded-lg border bg-card p-5 md:p-7" aria-label="Ranked defects">
      <p className="mb-5 text-sm text-muted-foreground">
        Ranked by: <span className="font-medium text-grey-900">{priority.data.formula}</span>
      </p>
      <RankingTable items={items} findingsById={byId} currency="USD" />
    </section>
  );
}

export default function FixFirstPage() {
  const { projectId, surveyId, project, survey } = useSelection();
  return (
    <>
      <PageHeader
        title="Fix first"
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
                  Export {fmt === "csv" ? "CSV" : "GeoJSON"}
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

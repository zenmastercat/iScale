"use client";
import { PageHeader, SurveyGate } from "@/components/shared";
import { useSelection } from "@/lib/selection";

/** Stub (lead). Sub-agent B replaces this. */
export default function ReportPage() {
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader title="Report" crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} />
      <SurveyGate>
        <p className="text-sm text-muted-foreground">Coming soon.</p>
      </SurveyGate>
    </>
  );
}

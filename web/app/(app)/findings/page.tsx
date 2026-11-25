"use client";
import { PageHeader, SurveyGate } from "@/components/shared";
import { useSelection } from "@/lib/selection";

/** Stub (lead). Sub-agent A replaces this: every finding in one sortable, filterable table. */
export default function FindingsPage() {
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader title="Findings" crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} />
      <SurveyGate>
        <p className="text-sm text-muted-foreground">Coming soon.</p>
      </SurveyGate>
    </>
  );
}

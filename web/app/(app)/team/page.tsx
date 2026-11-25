"use client";
import { PageHeader, SurveyGate } from "@/components/shared";
import { useSelection } from "@/lib/selection";

/** Stub (lead). The lead replaces this. */
export default function TeamPage() {
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader title="Team" crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} />
      <SurveyGate>
        <p className="text-sm text-muted-foreground">Coming soon.</p>
      </SurveyGate>
    </>
  );
}

"use client";
import { Database } from "lucide-react";
import { DemoButton } from "@/components/shared/demo-button";
import { EmptyState } from "@/components/shared/empty-state";
import { ProcessingState } from "@/components/shared/processing-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelection } from "@/lib/selection";

/**
 * Wrap a page body that needs a processed survey. Renders loading / no project / processing /
 * failed states itself and only renders children when the selected survey is "done".
 */
export function SurveyGate({ children }: { children: React.ReactNode }) {
  const { projects, projectsLoading, projectId, project, survey } = useSelection();
  if (projectsLoading || (projectId && !project)) return <Skeleton className="h-64 w-full" />;
  if (!projects?.length || !projectId)
    return (
      <EmptyState
        icon={Database}
        title="No projects yet"
        description="Load the demo street to see iScale with sample data: two drives of the same road, before and after repairs."
        action={<DemoButton />}
      />
    );
  if (!survey)
    return <EmptyState icon={Database} title="This project has no surveys yet" description="Add a drive to start." />;
  if (survey.status !== "done") return <ProcessingState survey={survey} />;
  return <>{children}</>;
}

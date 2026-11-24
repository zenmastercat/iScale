"use client";
import { useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { VerificationResults } from "@/components/verification/results";
import { VerifyPanel } from "@/components/verification/verify-panel";
import { WorkOrderList } from "@/components/verification/work-orders";
import { Skeleton } from "@/components/ui/skeleton";
import { DemoButton } from "@/components/shared/demo-button";
import { useVerification, useWorkOrders } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5 md:p-7" aria-label={title}>
      <h2 className="mb-5 text-lg font-semibold text-grey-900">{title}</h2>
      {children}
    </section>
  );
}

export default function VerificationPage() {
  const { projectId, project, projects, projectsLoading, survey } = useSelection();
  const orders = useWorkOrders();
  const verification = useVerification();
  const [picked, setSelected] = useState<string | null>(null);
  const selected = picked ?? orders.data?.[0]?.id ?? null;

  return (
    <>
      <PageHeader title="Verification" crumb={project ? `${project.name}${survey ? ` / ${survey.name}` : ""}` : undefined} />
      {projectsLoading || (projectId && !project) ? (
        <Skeleton className="h-64 w-full" />
      ) : !projects?.length || !projectId ? (
        <EmptyState title="No projects yet" description="Load the demo street to try the whole repair loop." action={<DemoButton />} />
      ) : (
        <div className="flex flex-col gap-6">
          <Card title="Work orders">
            {orders.isError ? (
              <p role="alert" className="text-sev-high-fg">Could not load work orders: {orders.error.message}</p>
            ) : orders.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <WorkOrderList orders={orders.data ?? []} selected={selected} onSelect={setSelected} />
            )}
          </Card>
          <Card title="Check the repairs">
            <VerifyPanel orders={orders.data ?? []} workorderId={selected} />
          </Card>
          <Card title="Results">
            {verification.isError ? (
              <p role="alert" className="text-sev-high-fg">Could not load results: {verification.error.message}</p>
            ) : verification.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : verification.data ? (
              <VerificationResults v={verification.data} />
            ) : (
              <EmptyState title="Not verified yet" description="Complete a work order, then compare the before and after surveys." />
            )}
          </Card>
        </div>
      )}
    </>
  );
}

"use client";
import { ArrowRight } from "lucide-react";
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
  const { projectId, project, projects, projectsLoading } = useSelection();
  const orders = useWorkOrders();
  const verification = useVerification();
  const [picked, setSelected] = useState<string | null>(null);
  const selected = picked ?? orders.data?.[0]?.id ?? null;
  const v = verification.data;
  const nameOf = (id: string) => project?.survey_list.find((x) => x.id === id)?.name ?? id;
  const woStatus = orders.data?.find((o) => o.id === v?.workorder_id)?.status.replace("_", " ");

  return (
    <>
      <PageHeader
        title="Verification"
        crumb={
          project
            ? `${project.name}${v?.workorder_id ? ` / Work order ${v.workorder_id}${woStatus ? ` · ${woStatus}` : ""}` : ""}`
            : undefined
        }
        actions={
          v && project ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg border bg-card px-4 py-2.5 text-sm">
                Before: <strong>{nameOf(v.before)}</strong>
              </span>
              <ArrowRight aria-hidden className="size-4 text-grey-600" />
              <span className="rounded-lg border bg-card px-4 py-2.5 text-sm">
                After: <strong>{nameOf(v.after)}</strong>
              </span>
            </div>
          ) : null
        }
      />
      {projectsLoading || (projectId && !project) ? (
        <Skeleton className="h-64 w-full" />
      ) : !projects?.length || !projectId ? (
        <EmptyState title="No projects yet" description="Load the demo street to try the whole repair loop." action={<DemoButton />} />
      ) : (
        <div className="flex flex-col gap-6">
          {verification.isError ? (
            <p role="alert" className="text-sev-high-fg">Could not load results: {verification.error.message}</p>
          ) : verification.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : v ? (
            <VerificationResults v={v} />
          ) : (
            <EmptyState title="Not verified yet" description="Complete a work order, then compare the before and after surveys." />
          )}
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
        </div>
      )}
    </>
  );
}

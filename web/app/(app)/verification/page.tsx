"use client";
import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { VerificationResults } from "@/components/verification/results";
import { woLabel } from "@/components/verification/words";
import { QueryError } from "@/components/surveys/query-error";
import { VerifyPanel } from "@/components/verification/verify-panel";
import { WorkOrderList } from "@/components/verification/work-orders";
import { VerificationResultsSkeleton, VerificationSkeleton, WorkOrdersSkeleton } from "@/components/skeletons";
import { DemoButton } from "@/components/shared/demo-button";
import { useVerification, useWorkOrders } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5 md:p-4" aria-label={title}>
      <h2 className="mb-5 text-lg md:text-base font-semibold text-grey-900">{title}</h2>
      {children}
    </section>
  );
}

export default function VerificationPage() {
  const t = useT();
  const { projectId, project, projects, projectsLoading, loadError, retryLoad } = useSelection();
  const orders = useWorkOrders();
  const verification = useVerification();
  const [picked, setSelected] = useState<string | null>(null);
  const selected = picked ?? orders.data?.[0]?.id ?? null;
  const v = verification.data;
  const nameOf = (id: string) => project?.survey_list.find((x) => x.id === id)?.name ?? id;
  const woStatus = orders.data?.find((o) => o.id === v?.workorder_id)?.status;

  return (
    <>
      <PageHeader
        title={t("Verification", "ตรวจยืนยัน")}
        crumb={
          project
            ? `${project.name}${v?.workorder_id ? ` / ${t("Work order", "ใบสั่งงาน")} ${v.workorder_id}${woStatus ? ` · ${woLabel(t, woStatus).toLowerCase()}` : ""}` : ""}`
            : undefined
        }
        actions={
          v && project ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg border bg-card px-4 py-2.5 text-sm">
                {t("Before", "ก่อน")}: <strong>{nameOf(v.before)}</strong>
              </span>
              <ArrowRight aria-hidden className="size-4 text-grey-600" />
              <span className="rounded-lg border bg-card px-4 py-2.5 text-sm">
                {t("After", "หลัง")}: <strong>{nameOf(v.after)}</strong>
              </span>
            </div>
          ) : null
        }
      />
      {loadError ? (
        <QueryError what={t("Could not load the project", "โหลดโครงการไม่ได้")} error={loadError} onRetry={retryLoad} />
      ) : projectsLoading || (projectId && !project) ? (
        <VerificationSkeleton />
      ) : !projects?.length || !projectId ? (
        <EmptyState title={t("No projects yet", "ยังไม่มีโครงการ")} description={t("Load the demo street to try the whole repair loop.", "โหลดถนนตัวอย่างเพื่อลองขั้นตอนซ่อมทั้งหมด")} action={<DemoButton />} />
      ) : (
        <div className="flex flex-col gap-6 md:gap-4">
          {verification.isError ? (
            <QueryError what={t("Could not load results", "โหลดผลตรวจยืนยันไม่ได้")} error={verification.error} onRetry={() => verification.refetch()} />
          ) : verification.isLoading ? (
            <VerificationResultsSkeleton />
          ) : v ? (
            <VerificationResults v={v} />
          ) : (
            (project?.survey_list.filter((x) => x.status === "done").length ?? 0) < 2 ? (
              <EmptyState
                title={t("Needs a second drive", "ต้องมีการสำรวจรอบที่สอง")}
                description={t(
                  "Verification compares this survey with a drive made after the repairs. This project has one survey so far (a camera run), so there is nothing to compare yet. Complete the repairs, drive the road again, and add that survey.",
                  "การตรวจยืนยันเปรียบเทียบการสำรวจนี้กับการสำรวจหลังซ่อม โครงการนี้มีการสำรวจเพียงรอบเดียว (วิดีโอจากกล้อง) จึงยังไม่มีอะไรให้เปรียบเทียบ ซ่อมให้เสร็จ ขับสำรวจถนนอีกครั้ง แล้วเพิ่มการสำรวจนั้น",
                )}
              />
            ) : (
              <EmptyState title={t("Not verified yet", "ยังไม่ได้ตรวจยืนยัน")} description={t("Complete a work order, then compare the before and after surveys.", "ทำใบสั่งงานให้เสร็จ แล้วเปรียบเทียบการสำรวจก่อนและหลังซ่อม")} />
            )
          )}
          <Card title={t("Work orders", "ใบสั่งงาน")}>
            {orders.isError ? (
              <QueryError what={t("Could not load work orders", "โหลดใบสั่งงานไม่ได้")} error={orders.error} onRetry={() => orders.refetch()} />
            ) : orders.isLoading ? (
              <WorkOrdersSkeleton />
            ) : (
              <WorkOrderList orders={orders.data ?? []} selected={selected} onSelect={setSelected} />
            )}
          </Card>
          <Card title={t("Check the repairs", "ตรวจงานซ่อม")}>
            <VerifyPanel orders={orders.data ?? []} workorderId={selected} />
          </Card>
        </div>
      )}
    </>
  );
}

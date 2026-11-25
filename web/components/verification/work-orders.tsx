"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/shared/empty-state";
import { Money, Num } from "@/components/shared/num";
import { Button } from "@/components/ui/button";
import { patchWorkOrder } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { invalidateRepairState } from "./invalidate";
import { WO_STATUS } from "./words";
import type { WorkOrder, WorkOrderStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const NEXT: Partial<Record<WorkOrderStatus, { to: WorkOrderStatus; label: [string, string]; icon: typeof CalendarClock }>> = {
  open: { to: "scheduled", label: ["Mark scheduled", "ทำเครื่องหมายนัดหมายแล้ว"], icon: CalendarClock },
  scheduled: { to: "completed", label: ["Mark completed", "ทำเครื่องหมายเสร็จแล้ว"], icon: CheckCircle2 },
};

export function WorkOrderList({
  orders,
  selected,
  onSelect,
}: {
  orders: WorkOrder[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const { projectId, project } = useSelection();
  const qc = useQueryClient();
  const move = useMutation({
    mutationFn: ({ id, to }: { id: string; to: WorkOrderStatus }) => patchWorkOrder(projectId!, id, to),
    onSuccess: (wo) => {
      invalidateRepairState(qc, projectId!, project?.baseline);
      toast.success(`${wo.id}: ${t(...WO_STATUS[wo.status]).toLowerCase()}`);
    },
    onError: (e: Error) => toast.error(`${t("Could not update the work order", "อัปเดตใบสั่งงานไม่ได้")}: ${e.message}`),
  });

  if (!orders.length)
    return (
      <EmptyState
        title={t("No work orders yet", "ยังไม่มีใบสั่งงาน")}
        description={t("Create one from the Repair plan: fund the repairs you want, then press Create work order.", "สร้างจากหน้าแผนซ่อม: เลือกงานซ่อมที่ต้องการแล้วกด สร้างใบสั่งงาน")}
      />
    );
  return (
    <ul className="flex flex-col gap-3">
      {orders.map((wo) => {
        const next = NEXT[wo.status];
        const on = selected === wo.id;
        return (
          <li key={wo.id} className={cn("rounded-lg border p-4", on && "border-brand bg-brand-50")}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelect(wo.id)}
                className="min-h-11 text-left"
              >
                <p className="font-medium text-grey-900">
                  <span className="num">{wo.id}</span> · {wo.title}
                </p>
                <p className="text-sm text-muted-foreground">
                  <Num value={wo.items.length} /> {t("repairs", "งานซ่อม")} · <Money amount={wo.total} currency={wo.currency} /> ·{" "}
                  {formatDate(wo.created)}
                </p>
              </button>
              <div className="flex items-center gap-3">
                <span className="rounded-md border px-2 py-1 text-sm font-medium">{t(...WO_STATUS[wo.status])}</span>
                {wo.verification && (
                  <span className="num text-sm text-muted-foreground">
                    {wo.verification.verified}/{wo.verification.total} {t("verified", "ยืนยันแล้ว")}
                  </span>
                )}
                {next && (
                  <Button
                    variant="outline"
                    className="min-h-11"
                    disabled={move.isPending}
                    onClick={() => move.mutate({ id: wo.id, to: next.to })}
                  >
                    <next.icon aria-hidden />
                    {t(...next.label)}
                  </Button>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

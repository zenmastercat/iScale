"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/shared/empty-state";
import { Money, Num } from "@/components/shared/num";
import { Button } from "@/components/ui/button";
import { patchWorkOrder } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useSelection } from "@/lib/selection";
import { invalidateRepairState } from "./invalidate";
import type { WorkOrder, WorkOrderStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL: Record<WorkOrderStatus, string> = {
  open: "Open",
  scheduled: "Scheduled",
  completed: "Completed",
  verified: "Verified",
  partially_verified: "Partly verified",
  cancelled: "Cancelled",
};
const NEXT: Partial<Record<WorkOrderStatus, { to: WorkOrderStatus; label: string; icon: typeof CalendarClock }>> = {
  open: { to: "scheduled", label: "Mark scheduled", icon: CalendarClock },
  scheduled: { to: "completed", label: "Mark completed", icon: CheckCircle2 },
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
  const { projectId, project } = useSelection();
  const qc = useQueryClient();
  const move = useMutation({
    mutationFn: ({ id, to }: { id: string; to: WorkOrderStatus }) => patchWorkOrder(projectId!, id, to),
    onSuccess: (wo) => {
      invalidateRepairState(qc, projectId!, project?.baseline);
      toast.success(`${wo.id} is now ${LABEL[wo.status].toLowerCase()}`);
    },
    onError: (e: Error) => toast.error(`Could not update the work order: ${e.message}`),
  });

  if (!orders.length)
    return (
      <EmptyState
        title="No work orders yet"
        description="Create one from the Repair plan: fund the repairs you want, then press Create work order."
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
                  <Num value={wo.items.length} /> repairs · <Money amount={wo.total} currency={wo.currency} /> ·{" "}
                  {formatDate(wo.created)}
                </p>
              </button>
              <div className="flex items-center gap-3">
                <span className="rounded-md border px-2 py-1 text-sm font-medium">{LABEL[wo.status]}</span>
                {wo.verification && (
                  <span className="num text-sm text-muted-foreground">
                    {wo.verification.verified}/{wo.verification.total} verified
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
                    {next.label}
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

import { Ban, CalendarClock, Circle, CircleSlash, EyeOff, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FindingStatus, VerifyStatus } from "@/lib/types";

export type PillStatus = FindingStatus | VerifyStatus;

const STATUS: Record<PillStatus, { label: string; icon: LucideIcon; cls: string }> = {
  open: { label: "Open", icon: Circle, cls: "bg-grey-100 text-grey-700" },
  planned: { label: "Planned", icon: CalendarClock, cls: "bg-brand-50 text-brand" },
  fixed: { label: "Fixed", icon: Wrench, cls: "bg-sev-low-bg text-sev-low-fg" },
  verified: { label: "Verified", icon: ShieldCheck, cls: "bg-sev-low-bg text-sev-low-fg" },
  not_fixed: { label: "Not fixed", icon: CircleSlash, cls: "bg-sev-high-bg text-sev-high-fg" },
  not_covered: { label: "Not covered", icon: EyeOff, cls: "bg-sev-medium-bg text-sev-medium-fg" },
  dismissed: { label: "Dismissed", icon: Ban, cls: "bg-grey-100 text-grey-600" },
};

export const statusLabel = (s: PillStatus) => STATUS[s]?.label ?? s;

/** Finding / verification status: icon + word. */
export function StatusPill({ status, className }: { status: PillStatus; className?: string }) {
  const s = STATUS[status] ?? STATUS.open;
  const Icon = s.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium whitespace-nowrap",
        s.cls,
        className,
      )}
    >
      <Icon aria-hidden className="size-3.5" strokeWidth={2.25} />
      {s.label}
    </span>
  );
}

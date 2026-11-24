import { Check, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

/** Funded / Deferred: icon + word, never colour alone. */
export function PlanPill({ funded }: { funded: boolean }) {
  const Icon = funded ? Check : Clock;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium whitespace-nowrap",
        funded ? "bg-brand-50 text-brand" : "border border-dashed bg-grey-50 text-grey-700",
      )}
    >
      <Icon aria-hidden className="size-3.5" strokeWidth={2.25} />
      {funded ? "Funded" : "Deferred"}
    </span>
  );
}

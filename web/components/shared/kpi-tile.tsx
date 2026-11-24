import { cn } from "@/lib/utils";

/** Big-number tile: label, value (+ unit), one line of context. */
export function KpiTile({
  label,
  value,
  unit,
  sub,
  className,
}: {
  label: string;
  /** already formatted (use formatNumber/formatMoney) */
  value: React.ReactNode;
  unit?: string;
  sub?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-5", className)}>
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p className="mt-2 flex items-baseline gap-2 text-brand">
        <span className="num text-4xl font-semibold tracking-tight">{value}</span>
        {unit && <span className="num text-lg text-grey-600">{unit}</span>}
      </p>
      {sub && <p className="mt-2 text-sm text-muted-foreground">{sub}</p>}
    </div>
  );
}

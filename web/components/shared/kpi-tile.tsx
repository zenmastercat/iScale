"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";

/** Big-number tile: label, value (+ unit), one line of context. With href the whole tile is a link. */
export function KpiTile({
  label,
  value,
  unit,
  sub,
  href,
  className,
}: {
  label: string;
  /** already formatted (use formatNumber/formatMoney) */
  value: React.ReactNode;
  unit?: string;
  sub?: React.ReactNode;
  /** e.g. withSel("/findings", findingsQuery({...})) */
  href?: string;
  className?: string;
}) {
  const body = (
    <>
      <p className="text-sm font-medium text-muted-foreground md:text-xs md:tracking-wide md:uppercase">{label}</p>
      <p className="mt-2 flex items-baseline gap-2 text-brand md:mt-1">
        <span className="num text-4xl font-semibold tracking-tight md:text-3xl">{value}</span>
        {unit && <span className="num text-lg text-grey-600 md:text-base">{unit}</span>}
      </p>
      {sub && <p className="mt-2 text-sm text-muted-foreground md:mt-1 md:text-[13px]">{sub}</p>}
    </>
  );
  const cls = cn("block rounded-lg border bg-card p-5 md:p-4", className);
  if (!href) return <div className={cls}>{body}</div>;
  return (
    <Link
      href={href}
      className={cn(cls, "transition-colors hover:border-accent-blue hover:bg-brand-50/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none")}
    >
      {body}
    </Link>
  );
}

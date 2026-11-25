"use client";
import { useEffect } from "react";
import { cn } from "@/lib/utils";

/** Page title block: breadcrumb line ("Demo district / Baseline drive"), h1, actions on the right. */
export function PageHeader({
  title,
  crumb,
  actions,
  className,
}: {
  title: string;
  crumb?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  // browser tab / history title: "Map · iScale"
  useEffect(() => {
    document.title = `${title} · iScale`;
  }, [title]);
  return (
    <header className={cn("mb-6 flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {crumb && <p className="truncate text-sm text-muted-foreground">{crumb}</p>}
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-brand">{title}</h1>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

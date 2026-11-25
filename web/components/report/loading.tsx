"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

/** A placeholder block with screen-reader text in the chosen language. */
export function Loading({ className }: { className?: string }) {
  const t = useT();
  return (
    <div role="status">
      <span className="sr-only">{t("Loading…", "กำลังโหลด…")}</span>
      <Skeleton className={className} aria-hidden />
    </div>
  );
}

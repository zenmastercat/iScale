"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

/** Toolbar ("Colour by" + 4 buttons), the map, the legend, and the defect list on lg+. */
export function MapSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="lg:flex lg:items-start lg:gap-3">
        <div className="min-w-0 rounded-lg border bg-card p-3 lg:flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Box className="h-4 w-20" />
            {[0, 1, 2, 3].map((i) => (
              <Box key={i} className="h-11 w-24 rounded-lg md:h-8" />
            ))}
            <Box className="ml-auto hidden h-8 w-28 rounded-lg lg:block" />
          </div>
          <Box className="h-[calc(100dvh-20rem)] min-h-[360px] w-full rounded-md bg-grey-50" />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 pt-3">
            <Box className="h-3 w-16" />
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-1.5">
                <Box className="h-1.5 w-5 rounded-full" />
                <Box className="h-3 w-14" />
              </div>
            ))}
            <Box className="h-3 w-16" />
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-1.5">
                <Box className="size-2.5 rounded-[2px]" />
                <Box className="h-3 w-10" />
              </div>
            ))}
          </div>
        </div>

        <aside className="mt-3 hidden h-[calc(100dvh-14rem)] min-h-[420px] w-80 shrink-0 overflow-hidden rounded-lg border bg-card lg:mt-0 lg:block">
          <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
            <Box className="h-4 w-24" />
            <Box className="h-4 w-24" />
          </div>
          <ul>
            {Array.from({ length: 8 }, (_, i) => (
              <li key={i} className="flex items-start gap-2 border-b px-3 py-2 last:border-b-0">
                <Box className="mt-1 size-3 rounded-[2px]" />
                <div className="min-w-0 flex-1">
                  <Box className="h-3.5 w-32" />
                  <Box className="mt-1 h-3 w-24" />
                  <Box className="mt-1 h-3 w-20" />
                </div>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}

"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

const CARD = "rounded-lg border bg-card p-5 md:p-4";

function Tiles() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-lg border bg-card p-5">
          <Box className="size-14 shrink-0 rounded-full" />
          <div>
            <Box className="h-9 w-16" />
            <Box className="mt-2 h-4 w-32" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Results summary: three status tiles and the per-repair rows. */
export function VerificationResultsSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-6">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-6">
        <Tiles />
        <section className="rounded-lg border bg-card p-4 md:p-4">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <Box className="h-4 w-64" />
            <div className="flex flex-wrap items-center gap-2">
              <Box className="h-11 w-32 rounded-lg" />
              {[0, 1, 2, 3].map((i) => (
                <Box key={i} className="h-11 w-24 rounded-lg" />
              ))}
            </div>
          </div>
          <ul className="flex flex-col gap-3 md:gap-2">
            {Array.from({ length: 4 }, (_, i) => (
              <li
                key={i}
                className="grid grid-cols-1 gap-4 rounded-lg border p-4 md:grid-cols-[minmax(0,10rem)_minmax(0,16rem)_minmax(0,1fr)_auto] md:items-center md:gap-4 md:p-3"
              >
                <div>
                  <Box className="h-4 w-36" />
                  <Box className="mt-1.5 h-3 w-20" />
                  <Box className="mt-2 h-5 w-24 rounded-full" />
                </div>
                <div className="flex flex-col gap-2">
                  <div className="grid grid-cols-[3.5rem_1fr_5.5rem] items-center gap-x-3">
                    <Box className="h-3 w-10" />
                    <Box className="h-3 w-full" />
                    <Box className="ml-auto h-3 w-12" />
                  </div>
                  <div className="grid grid-cols-[3.5rem_1fr_5.5rem] items-center gap-x-3">
                    <Box className="h-3 w-10" />
                    <Box className="h-3 w-full" />
                    <Box className="ml-auto h-3 w-12" />
                  </div>
                </div>
                <div>
                  <Box className="h-3 w-full" />
                  <Box className="mt-1.5 h-3 w-4/5" />
                </div>
                <Box className="hidden h-6 w-24 rounded-md md:block" />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

/** The work-order list inside its card. */
export function WorkOrdersSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <ul aria-hidden className="flex flex-col gap-3">
        {Array.from({ length: 3 }, (_, i) => (
          <li key={i} className="rounded-lg border p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Box className="h-4 w-64 max-w-full" />
                <Box className="mt-2 h-3 w-48" />
              </div>
              <div className="flex items-center gap-3">
                <Box className="h-7 w-24 rounded-md" />
                <Box className="h-3 w-16" />
                <Box className="h-11 w-36 rounded-lg" />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** First paint while the project loads: results tiles, then the two lower cards. */
export function VerificationSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-6 md:gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-6 md:gap-4">
        <Tiles />
        <section className={CARD}>
          <Box className="mb-5 h-4 w-40" />
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Box className="h-4 w-64 max-w-full" />
                    <Box className="mt-2 h-3 w-48" />
                  </div>
                  <Box className="h-7 w-24 rounded-md" />
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className={CARD}>
          <Box className="mb-5 h-4 w-48" />
          <Box className="h-24 w-full" />
        </section>
      </div>
    </div>
  );
}

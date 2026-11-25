"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

const CARD = "rounded-lg border bg-card p-5 md:p-4";

/** Budget card (number, slider, presets, funded bar), 4 KPI tiles, chart, then the repairs table. */
export function PlanSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-6 md:gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-6 md:gap-4">
        {/* budget */}
        <section className={CARD}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <Box className="h-3 w-16" />
              <Box className="mt-2 h-10 w-52" />
              <Box className="mt-1 h-3 w-36" />
            </div>
            <Box className="h-11 w-60 rounded-lg" />
          </div>
          <div className="mt-6 flex min-h-11 items-center">
            <Box className="h-2 w-full rounded-full" />
          </div>
          <div className="mt-1 flex justify-between">
            <Box className="h-3 w-12" />
            <Box className="h-3 w-12" />
            <Box className="h-3 w-12" />
          </div>
          <Box className="mt-2 h-3 w-full max-w-2xl" />
          <Box className="mt-1 h-3 w-2/3 max-w-xl" />
          <div className="mt-3 flex flex-wrap gap-2">
            {[0, 1, 2].map((i) => (
              <Box key={i} className="h-11 w-32 rounded-lg" />
            ))}
            <Box className="h-11 w-24 rounded-lg" />
          </div>
          <div className="mt-6">
            <Box className="h-6 w-full rounded-md" />
            <div className="mt-2 flex flex-wrap justify-between gap-x-6 gap-y-1">
              <Box className="h-3 w-36" />
              <Box className="h-3 w-36" />
            </div>
          </div>
        </section>

        {/* 4 KPI tiles */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className={CARD}>
              <Box className="h-3 w-24" />
              <Box className="mt-2 h-8 w-28 md:h-7" />
              <Box className="mt-2 h-3 w-full" />
              <Box className="mt-1.5 h-3 w-2/3" />
            </div>
          ))}
        </div>

        {/* chart */}
        <section className={CARD}>
          <Box className="h-4 w-52" />
          <Box className="mt-2 h-3 w-64" />
          <Box className="mt-3 h-56 w-full rounded-md" />
        </section>

        {/* plan items */}
        <section className={CARD}>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3 md:mb-3">
            <Box className="h-4 w-64" />
          </div>

          {/* phone cards */}
          <ul className="flex flex-col gap-3 md:hidden">
            {Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <Box className="h-5 w-20 rounded-full" />
                  <Box className="h-5 w-16 rounded-full" />
                </div>
                <Box className="mt-2 h-4 w-40" />
                <Box className="mt-1 h-3 w-28" />
                <div className="mt-3 grid grid-cols-3 gap-3">
                  {[0, 1, 2].map((c) => (
                    <div key={c}>
                      <Box className="h-3 w-12" />
                      <Box className="mt-1 h-3 w-14" />
                    </div>
                  ))}
                </div>
                <Box className="mt-3 h-11 w-full rounded-lg" />
              </li>
            ))}
          </ul>

          {/* desktop table */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b">
                  {Array.from({ length: 7 }, (_, i) => (
                    <th key={i} className="py-3 pr-4 md:py-1.5">
                      <Box className="h-3 w-14" />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 8 }, (_, r) => (
                  <tr key={r} className="border-b last:border-0">
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-5 w-20 rounded-full" /></td>
                    <td className="py-3 pr-4 md:py-1.5">
                      <Box className="h-3 w-40" />
                      <Box className="mt-1.5 h-3 w-16" />
                    </td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-3 w-28" /></td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-5 w-16 rounded-full" /></td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-3 w-12" /></td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="ml-auto h-3 w-10" /></td>
                    <td className="py-3 md:py-1.5"><Box className="ml-auto h-3 w-16" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Box className="mt-4 h-3 w-full max-w-2xl" />
        </section>
      </div>
    </div>
  );
}

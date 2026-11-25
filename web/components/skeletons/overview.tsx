"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

const CARD = "min-w-0 rounded-lg border bg-card p-5 md:p-4";

/** One grey shape. Everything sits inside an aria-hidden wrapper in each skeleton. */
function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

function CardHead({ note = true }: { note?: boolean }) {
  return (
    <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 md:mb-3">
      <Box className="h-4 w-40 md:h-4 md:w-44" />
      {note && <Box className="h-3 w-24" />}
    </div>
  );
}

function KpiRow({ n, cols }: { n: number; cols: string }) {
  return (
    <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 md:gap-3 ${cols}`}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className={CARD}>
          <Box className="h-3 w-24" />
          <Box className="mt-2 h-8 w-28 md:h-7" />
          <Box className="mt-2 h-3 w-full" />
          <Box className="mt-1.5 h-3 w-3/4" />
        </div>
      ))}
    </div>
  );
}

/** Header row plus body rows, for the small tables inside overview cards. */
function MiniTable({ cols, rows }: { cols: number; rows: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px]">
        <thead>
          <tr className="border-b">
            {Array.from({ length: cols }, (_, c) => (
              <th key={c} className="py-2 pr-2 text-left">
                <Box className={c === 0 ? "h-3 w-20" : "h-3 w-10"} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r} className="border-b last:border-0">
              {Array.from({ length: cols }, (_, c) => (
                <td key={c} className="py-2 pr-2 md:py-1.5">
                  <Box className={c === 0 ? "h-3 w-28" : "h-3 w-full"} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-6 md:gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-6 md:gap-4">
        {/* summary sentence */}
        <div className="rounded-lg border bg-card px-6 py-6 md:px-5 md:py-4">
          <Box className="h-5 w-full max-w-3xl" />
          <Box className="mt-2 h-5 w-2/3 max-w-xl" />
        </div>

        {/* 5 KPI tiles */}
        <KpiRow n={5} cols="xl:grid-cols-5" />

        {/* condition strip + defect matrix */}
        <div className="grid grid-cols-1 gap-6 md:gap-4 xl:grid-cols-5">
          <div className={`${CARD} xl:col-span-3`}>
            <CardHead />
            <Box className="h-32 w-full rounded-md" />
            <Box className="mt-6 h-3 w-full rounded-full md:mt-4" />
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
              {["w-10", "w-14", "w-8", "w-12", "w-10"].map((w, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Box className="size-3 rounded-[2px]" />
                  <Box className={`h-3 ${w}`} />
                </div>
              ))}
            </div>
          </div>
          <div className={`${CARD} xl:col-span-2`}>
            <CardHead />
            <MiniTable cols={5} rows={6} />
          </div>
        </div>

        {/* segment line diagram */}
        <div className={CARD}>
          <CardHead />
          <Box className="h-72 w-full rounded-md" />
        </div>

        {/* cost by action + condition change */}
        <div className="grid grid-cols-1 gap-6 md:gap-4 xl:grid-cols-2">
          <div className={CARD}>
            <CardHead />
            <MiniTable cols={5} rows={5} />
          </div>
          <div className={CARD}>
            <CardHead />
            <MiniTable cols={4} rows={5} />
          </div>
        </div>

        {/* fix first, top 5 */}
        <div className={CARD}>
          <CardHead />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead>
                <tr className="border-b">
                  {Array.from({ length: 7 }, (_, i) => (
                    <th key={i} className="py-3 pr-4 text-left md:py-2">
                      <Box className="h-3 w-full max-w-24" />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[0, 1, 2, 3, 4].map((r) => (
                  <tr key={r} className="border-b last:border-0">
                    <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-6" /></td>
                    <td className="py-3 pr-4 md:py-2">
                      <Box className="h-3 w-40" />
                      <Box className="mt-1.5 h-3 w-56" />
                    </td>
                    <td className="py-3 pr-4 md:py-2"><Box className="h-4 w-16 rounded-full" /></td>
                    <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-12" /></td>
                    <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-24" /></td>
                    <td className="py-3 pr-4 text-right md:py-2"><Box className="ml-auto h-3 w-16" /></td>
                    <td className="py-3 text-right md:py-2"><Box className="ml-auto h-3 w-10" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Box className="mt-4 h-4 w-28" />
        </div>
      </div>
    </div>
  );
}

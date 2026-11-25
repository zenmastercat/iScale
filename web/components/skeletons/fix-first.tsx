"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

/** Summary strip of 4 stat cells, then the ranking table (cards on phones). */
export function FixFirstSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="rounded-lg border bg-card p-5 md:p-4">
        <Box className="mb-5 h-3 w-64" />

        <div className="mb-4 grid grid-cols-2 gap-3 md:mb-3 md:grid-cols-4 md:gap-3">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="rounded-lg border bg-card px-4 py-3 md:px-3 md:py-2">
              <Box className="h-3 w-20" />
              <Box className="mt-2 h-6 w-16 md:h-5" />
              <Box className="mt-1 h-3 w-24" />
              <Box className="mt-1 h-3 w-16" />
            </div>
          ))}
        </div>

        {/* phone cards */}
        <ul className="flex flex-col gap-3 md:hidden">
          {Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="rounded-lg border p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Box className="h-4 w-48" />
                  <Box className="mt-1.5 h-3 w-32" />
                </div>
                <Box className="h-5 w-16 rounded-full" />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div>
                  <Box className="h-3 w-12" />
                  <Box className="mt-1 h-3 w-16" />
                </div>
                <div>
                  <Box className="ml-auto h-3 w-10" />
                  <Box className="mt-1 ml-auto h-3 w-20" />
                </div>
              </div>
              <Box className="mt-3 h-11 w-full rounded-lg" />
            </li>
          ))}
        </ul>

        {/* desktop table */}
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[760px] text-left">
            <colgroup>
              <col className="w-14" />
              <col />
              <col className="w-24" />
              <col className="w-36" />
              <col className="w-20" />
              <col className="w-28" />
              <col className="w-16" />
            </colgroup>
            <thead>
              <tr className="border-b">
                {Array.from({ length: 7 }, (_, i) => (
                  <th key={i} className="py-3 pr-4 md:py-2">
                    <Box className="h-3 w-14" />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 10 }, (_, r) => (
                <tr key={r} className="border-b last:border-0">
                  <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-6" /></td>
                  <td className="py-3 pr-4 md:py-2">
                    <Box className="h-3 w-56" />
                    <Box className="mt-1.5 h-3 w-80" />
                  </td>
                  <td className="py-3 pr-4 md:py-2"><Box className="h-5 w-16 rounded-full" /></td>
                  <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-12" /></td>
                  <td className="py-3 pr-4 md:py-2"><Box className="h-3 w-24" /></td>
                  <td className="py-3 pr-4 md:py-2"><Box className="ml-auto h-3 w-16" /></td>
                  <td className="py-3 md:py-2"><Box className="ml-auto h-3 w-10" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

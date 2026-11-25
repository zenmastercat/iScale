"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

/** Filter bar, then the dense 13-column table on md+ and the stacked cards on phones. */
export function FindingsSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-4">
        {/* filter bar */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1">
              <Box className="h-11 w-24 rounded-lg md:h-8" />
              <Box className="h-11 w-24 rounded-lg md:h-8" />
            </div>
            {[0, 1, 2, 3].map((i) => (
              <Box key={i} className="h-11 w-24 rounded-lg md:h-8" />
            ))}
            <Box className="h-11 min-w-48 flex-1 rounded-lg md:h-8 md:max-w-xs" />
            <Box className="h-11 w-32 rounded-lg md:ml-auto md:h-8" />
          </div>
          <Box className="h-3 w-28" />
        </div>

        <div className="hidden md:block">
          <Box className="h-8 w-40 rounded-lg" />
        </div>

        {/* desktop table */}
        <div className="hidden max-h-[calc(100dvh-16rem)] overflow-auto rounded-lg border bg-card md:block">
          <table className="w-full min-w-[1040px] border-collapse text-left">
            <thead className="bg-grey-50">
              <tr>
                <th className="w-8 border-b px-2 py-1.5">
                  <Box className="size-4 rounded-[2px]" />
                </th>
                {Array.from({ length: 13 }, (_, i) => (
                  <th key={i} className="border-b px-2 py-1.5">
                    <Box className="h-3 w-14" />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 12 }, (_, r) => (
                <tr key={r} className="border-b">
                  <td className="px-2 py-1">
                    <Box className="size-4 rounded-[2px]" />
                  </td>
                  {Array.from({ length: 13 }, (_, c) => (
                    <td key={c} className="px-2 py-1">
                      <Box className={c === 1 || c === 2 ? "h-3 w-24" : "h-3 w-full"} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-grey-50">
              <tr>
                <td className="border-t px-2 py-1.5" colSpan={9}>
                  <Box className="h-3 w-32" />
                </td>
                <td className="border-t px-2 py-1.5">
                  <Box className="ml-auto h-3 w-12" />
                </td>
                <td className="border-t px-2 py-1.5">
                  <Box className="ml-auto h-3 w-12" />
                </td>
                <td className="border-t px-2 py-1.5">
                  <Box className="ml-auto h-3 w-14" />
                </td>
                <td className="border-t px-2 py-1.5" colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>

        {/* phone cards */}
        <ul className="flex flex-col gap-2 md:hidden">
          {Array.from({ length: 8 }, (_, i) => (
            <li key={i} className="rounded-lg border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <Box className="h-4 w-40" />
                <Box className="h-3 w-16" />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Box className="h-5 w-16 rounded-full" />
                <Box className="h-5 w-16 rounded-full" />
                <Box className="h-3 w-24" />
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                <Box className="h-3 w-12" />
                <Box className="h-3 w-14" />
                <Box className="h-3 w-10" />
              </div>
            </li>
          ))}
        </ul>

        <Box className="hidden h-3 w-72 md:block" />
      </div>
    </div>
  );
}

"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

/** The survey list card: table header plus survey rows (name, source, status, stats, actions). */
export function SurveysSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-4">
        <section className="rounded-lg border bg-card p-5 md:p-4">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[820px] text-left">
              <thead>
                <tr className="border-b">
                  {Array.from({ length: 6 }, (_, i) => (
                    <th key={i} className="py-3 pr-4 md:py-1.5">
                      <Box className="h-3 w-16" />
                    </th>
                  ))}
                  <th className="py-3 md:py-1.5">
                    <Box className="ml-auto h-3 w-16" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 3 }, (_, r) => (
                  <tr key={r} className="border-b align-top last:border-0">
                    <td className="py-3 pr-4 md:py-1.5">
                      <Box className="h-4 w-40" />
                      <Box className="mt-1.5 h-3 w-16" />
                      <Box className="mt-2 h-3 w-56" />
                      <Box className="mt-1 hidden h-3 w-64 lg:block" />
                    </td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-3 w-24" /></td>
                    <td className="py-3 pr-4 md:py-1.5">
                      <div className="flex items-center gap-1.5">
                        <Box className="size-4 rounded-full" />
                        <Box className="h-3 w-16" />
                      </div>
                    </td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="ml-auto h-3 w-14" /></td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="ml-auto h-3 w-8" /></td>
                    <td className="py-3 pr-4 md:py-1.5"><Box className="h-3 w-20" /></td>
                    <td className="py-3 md:py-1.5">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Box className="h-11 w-20 rounded-lg" />
                        <Box className="h-11 w-20 rounded-lg" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

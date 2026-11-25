"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

/** The people table: header row plus member rows (name, username, role, device, actions). */
export function TeamTableSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="relative overflow-x-auto">
        <table className="w-full min-w-[560px] text-left">
          <thead>
            <tr className="border-b">
              {Array.from({ length: 5 }, (_, i) => (
                <th key={i} className="py-2 pr-3">
                  <Box className="h-3 w-16" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 4 }, (_, r) => (
              <tr key={r} className="border-b last:border-0">
                <td className="py-2 pr-3 md:py-1.5"><Box className="h-3.5 w-32" /></td>
                <td className="py-2 pr-3 md:py-1.5"><Box className="h-3 w-24" /></td>
                <td className="py-2 pr-3 md:py-1.5"><Box className="h-3 w-16" /></td>
                <td className="py-2 pr-3 md:py-1.5"><Box className="h-3 w-28" /></td>
                <td className="py-2 pr-3 md:py-1.5"><Box className="ml-auto h-8 w-32 rounded-lg" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

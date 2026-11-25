"use client";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

function Box({ className }: { className?: string }) {
  return <Skeleton aria-hidden className={className} />;
}

const KPI = "rounded-lg border bg-card p-5 md:p-4";

/**
 * The frame around every page: dark side rail (md+), top bar with the project/survey pickers,
 * and a content area. Used before the signed-in shell is known and as the Suspense fallback,
 * so the first paint already looks like the app.
 */
export function AppShellSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex min-h-dvh">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex min-h-dvh w-full">
        <nav className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col bg-sidebar px-3 py-6 md:flex">
          <Box className="mb-8 ml-3 h-8 w-32 bg-white/15" />
          <Box className="mb-2 ml-3 h-3 w-24 bg-white/10" />
          <div className="flex flex-col gap-1">
            {Array.from({ length: 9 }, (_, i) => (
              <Box key={i} className={`h-11 w-full rounded-md ${i === 0 ? "bg-white/15" : "bg-white/10"}`} />
            ))}
          </div>
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="sticky top-0 z-30 border-b bg-card/95 backdrop-blur">
            <div className="flex min-h-14 flex-wrap items-center gap-2 px-4 py-2 md:px-8">
              <Box className="h-8 w-20 rounded md:hidden" />
              <div className="order-3 flex w-full flex-wrap items-center gap-2 md:order-2 md:w-auto">
                <Box className="h-11 w-40 rounded-lg md:h-9" />
                <Box className="h-11 w-40 rounded-lg md:h-9" />
              </div>
              <div className="order-2 ml-auto flex items-center gap-2 md:order-3">
                <Box className="h-9 w-24 rounded-md" />
                <Box className="size-9 rounded-md" />
              </div>
            </div>
          </div>

          <main className="flex-1 px-4 pt-6 pb-24 md:px-8 md:pb-10">
            <Box className="h-8 w-56" />
            <Box className="mt-2 h-4 w-72 max-w-full" />

            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 md:gap-3 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className={KPI}>
                  <Box className="h-3 w-24" />
                  <Box className="mt-2 h-8 w-28 md:h-7" />
                  <Box className="mt-2 h-3 w-full" />
                  <Box className="mt-1.5 h-3 w-2/3" />
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-lg border bg-card p-5 md:p-4">
              <Box className="h-4 w-40" />
              <Box className="mt-4 h-40 w-full rounded-md" />
            </div>
          </main>
        </div>

        <div className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-6 border-t border-white/10 bg-sidebar pb-[env(safe-area-inset-bottom)] md:hidden">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="flex flex-col items-center justify-center gap-1">
              <Box className="size-5 rounded-[3px] bg-white/15" />
              <Box className="h-2 w-8 bg-white/10" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Generic page body used while the project loads: 4 KPI tiles and one card. */
export function PageSkeleton() {
  const t = useT();
  return (
    <div aria-busy="true" className="flex flex-col gap-6 md:gap-4">
      <span role="status" className="sr-only">
        {t("Loading…", "กำลังโหลด…")}
      </span>
      <div aria-hidden className="flex flex-col gap-6 md:gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:gap-3 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className={KPI}>
              <Box className="h-3 w-24" />
              <Box className="mt-2 h-8 w-28 md:h-7" />
              <Box className="mt-2 h-3 w-full" />
              <Box className="mt-1.5 h-3 w-2/3" />
            </div>
          ))}
        </div>
        <div className="rounded-lg border bg-card p-5 md:p-4">
          <Box className="h-4 w-40" />
          <Box className="mt-4 h-40 w-full rounded-md" />
        </div>
      </div>
    </div>
  );
}

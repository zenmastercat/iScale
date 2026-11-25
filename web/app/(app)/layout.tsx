"use client";
import { useRouter } from "next/navigation";
import { Suspense, useEffect } from "react";
import { BottomBar, SideRail } from "@/components/shell/side-rail";
import { TopBar } from "@/components/shell/top-bar";
import { ServerDown } from "@/components/shared/server-down";
import { AppShellSkeleton } from "@/components/skeletons";
import { useAuthState } from "@/lib/queries";
import { SelectionProvider } from "@/lib/selection";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <SelectionProvider>
      <div className="flex min-h-dvh">
        <SideRail />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main id="main" className="flex-1 px-4 pt-6 pb-24 md:px-8 md:pb-10 print:p-0">
            {children}
          </main>
        </div>
      </div>
      <BottomBar />
    </SelectionProvider>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data, isLoading, isError, error, refetch, isFetching } = useAuthState();
  // auth/state is 200 with user=null when signed out; an error means the server is unreachable
  const signedOut = !isLoading && !isError && !data?.user;

  useEffect(() => {
    if (signedOut) router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }, [signedOut, router]);

  if (isError && !data) return <ServerDown error={error} onRetry={() => refetch()} busy={isFetching} />;
  if (!data?.user) return <AppShellSkeleton />;
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-card focus:p-2">
        Skip to content
      </a>
      <Suspense fallback={<AppShellSkeleton />}>
        <Shell>{children}</Shell>
      </Suspense>
    </>
  );
}

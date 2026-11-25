"use client";
import { ServerCrash } from "lucide-react";
import { Logo } from "@/components/shell/logo";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

/**
 * Full-page "can't reach the iScale server" with Retry. /api/auth/state answers 200 even when signed out,
 * so an error there means the backend (or the proxy to it) is down, not that the user must sign in.
 */
export function ServerDown({ error, onRetry, busy }: { error?: Error | null; onRetry: () => void; busy?: boolean }) {
  const t = useT();
  return (
    <main role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-5 bg-grey-50 px-6 text-center">
      <span className="rounded-md bg-sidebar px-3 py-2">
        <Logo />
      </span>
      <ServerCrash aria-hidden className="size-10 text-grey-500" />
      <div className="max-w-md">
        <h1 className="text-2xl font-semibold text-brand">{t("Can't reach the iScale server", "เชื่อมต่อเซิร์ฟเวอร์ iScale ไม่ได้")}</h1>
        <p className="mt-2 text-muted-foreground">
          {t(
            "Check that the backend is running (uv run civil serve) and this computer is on the same network.",
            "ตรวจสอบว่าเซิร์ฟเวอร์ทำงานอยู่ (uv run civil serve) และเครื่องนี้อยู่ในเครือข่ายเดียวกัน",
          )}
        </p>
        {error && <p className="num mt-2 text-xs text-muted-foreground">{error.message}</p>}
      </div>
      <Button className="h-11 px-6" onClick={onRetry} disabled={busy}>
        {t("Retry", "ลองอีกครั้ง")}
      </Button>
    </main>
  );
}

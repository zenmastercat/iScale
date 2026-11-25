"use client";
import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

/** A failed request: what failed, the server's message, and a Retry that refetches. Never a blank page. */
export function QueryError({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  const t = useT();
  const msg = error instanceof Error ? error.message : "";
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sev-high bg-sev-high-bg p-4 text-sev-high-fg">
      <p className="flex items-start gap-2">
        <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>
          <span className="font-medium">{what}</span>
          {msg && <span className="block text-sm">{msg}</span>}
        </span>
      </p>
      <Button variant="outline" className="min-h-11 bg-card text-grey-900" onClick={onRetry}>
        <RotateCw aria-hidden />
        {t("Retry", "ลองอีกครั้ง")}
      </Button>
    </div>
  );
}

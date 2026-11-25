"use client";
import { AlertTriangle, SearchX } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

/** Visible API error with a Retry button (never a blank area). */
export function RetryError({ title, message, onRetry, busy }: { title: string; message?: string; onRetry: () => void; busy?: boolean }) {
  const t = useT();
  return (
    <div role="alert" className="flex flex-col items-center gap-2 rounded-lg border border-sev-high/40 bg-sev-high-bg px-6 py-8 text-center">
      <AlertTriangle className="size-6 text-sev-high-fg" aria-hidden />
      <p className="font-semibold text-sev-high-fg">{title}</p>
      {message && <p className="max-w-md text-sm text-sev-high-fg">{message}</p>}
      <Button type="button" variant="outline" className="mt-2 min-h-11 bg-card" disabled={busy} onClick={onRetry}>
        {busy ? t("Retrying…", "กำลังลองใหม่…") : t("Retry", "ลองใหม่")}
      </Button>
    </div>
  );
}

/** Friendly "no such thing" with a way back. */
export function NotFound({ title, description, href, linkLabel }: { title: string; description: string; href: string; linkLabel: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-12 text-center">
      <SearchX className="size-8 text-grey-500" aria-hidden />
      <h2 className="text-lg font-semibold text-brand">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      <Button className="mt-3 min-h-11 bg-brand text-white hover:bg-brand/90" render={<Link href={href} />} nativeButton={false}>
        {linkLabel}
      </Button>
    </div>
  );
}

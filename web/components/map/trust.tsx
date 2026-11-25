"use client";
import { Check, Hand, Ruler } from "lucide-react";
import type { Finding } from "@/lib/types";
import { useT } from "@/lib/i18n";

/** Trust badge from finding.source (geometry / decoder / manual). */
export function TrustBadge({ source }: { source: Finding["source"] }) {
  const t = useT();
  const map: Record<string, { label: string; Icon: typeof Check }> = {
    decoder: { label: t("Measured + detector", "วัดจริง + ตัวตรวจจับ"), Icon: Check },
    geometry: { label: t("Measured", "วัดจริง"), Icon: Ruler },
    manual: { label: t("Tagged by hand", "ปักหมุดด้วยมือ"), Icon: Hand },
  };
  const m = map[source] ?? { label: source, Icon: Check };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-accent-blue/10 px-2 py-1 text-sm font-medium whitespace-nowrap text-link">
      <m.Icon className="size-3.5" aria-hidden />
      {m.label}
    </span>
  );
}

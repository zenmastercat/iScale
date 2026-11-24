"use client";
import { Check, Hand, Ruler } from "lucide-react";
import type { Finding } from "@/lib/types";

/** Trust badge from finding.source (geometry / decoder / manual). */
export function TrustBadge({ source }: { source: Finding["source"] }) {
  const map: Record<string, { label: string; Icon: typeof Check }> = {
    decoder: { label: "Measured + detector", Icon: Check },
    geometry: { label: "Measured", Icon: Ruler },
    manual: { label: "Tagged by hand", Icon: Hand },
  };
  const m = map[source] ?? { label: source, Icon: Check };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-accent-blue/10 px-2 py-1 text-sm font-medium whitespace-nowrap text-link">
      <m.Icon className="size-3.5" aria-hidden />
      {m.label}
    </span>
  );
}

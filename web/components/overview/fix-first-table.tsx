"use client";
import Link from "next/link";
import { Money } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useSelection } from "@/lib/selection";
import type { Finding, PriorityItem } from "@/lib/types";

const EVIDENCE: Record<string, string> = {
  geometry: "Measured",
  decoder: "Measured + detector",
  manual: "Tagged by hand",
};

export function evidenceSource(f?: Finding) {
  if (!f) return "Shared pin";
  return EVIDENCE[f.source] ?? f.source;
}

/** Top-N of GET /api/priority, with the measurement sentence from the analysis. */
export function FixFirstTable({
  items,
  findingsById,
  currency,
}: {
  items: PriorityItem[];
  findingsById: Map<string, Finding>;
  currency: string;
}) {
  const { withSel } = useSelection();
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[720px] text-left">
        <thead>
          <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">Rank</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">Finding</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">Severity</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">Segment</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">Evidence</th>
            <th scope="col" className="py-3 md:py-2 pr-4 text-right font-semibold">Cost</th>
            <th scope="col" className="py-3 md:py-2"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const f = findingsById.get(it.id);
            return (
              <tr key={it.id} className="border-b last:border-0">
                <td className="num py-3 md:py-2 pr-4 font-semibold text-brand">#{it.rank}</td>
                <td className="py-3 md:py-2 pr-4">
                  <p className="font-medium text-grey-900">{it.label}</p>
                  {f?.evidence && <p className="text-sm text-muted-foreground">{f.evidence}</p>}
                </td>
                <td className="py-3 md:py-2 pr-4">
                  <SeverityBadge severity={it.severity} size="sm" />
                </td>
                <td className="num py-3 md:py-2 pr-4">{it.segment_id}</td>
                <td className="py-3 md:py-2 pr-4 text-sm text-grey-700">{evidenceSource(f)}</td>
                <td className="py-3 md:py-2 pr-4 text-right font-medium">
                  <Money amount={it.cost} currency={currency} />
                </td>
                <td className="py-3 md:py-2 text-right">
                  <Link
                    href={withSel("/map", { finding: it.id })}
                    className="inline-flex min-h-11 items-center px-1 font-medium text-link underline underline-offset-4 hover:text-brand"
                    aria-label={`Open ${it.label} ${it.id} on the map`}
                  >
                    Open
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

"use client";
import Link from "next/link";
import { useState } from "react";
import { KpiTile } from "@/components/shared/kpi-tile";
import { Num } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { StatusPill } from "@/components/shared/status-pill";
import { useCatalogLabel } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { FindingMetrics, Verification, VerifyStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | VerifyStatus;

/** The one number that best describes a defect, from its metrics. */
function headline(m: FindingMetrics | null): string {
  if (!m) return "–";
  if (m.depth_max_m !== undefined) return `${(m.depth_max_m * 100).toFixed(1)} cm deep`;
  if (m.step_m !== undefined) return `${(m.step_m * 100).toFixed(1)} cm step`;
  if (m.height_max_m !== undefined) return `${(m.height_max_m * 100).toFixed(1)} cm high`;
  if (m.area_m2 !== undefined) return `${m.area_m2.toFixed(2)} m²`;
  return "–";
}

export function VerificationResults({ v }: { v: Verification }) {
  const { withSel } = useSelection();
  const label = useCatalogLabel();
  const [filter, setFilter] = useState<Filter>("all");
  const rows = filter === "all" ? v.results : v.results.filter((r) => r.status === filter);
  const filters: { key: Filter; label: string; n: number }[] = [
    { key: "all", label: "All", n: v.results.length },
    { key: "verified", label: "Verified", n: v.counts.verified },
    { key: "not_fixed", label: "Not fixed", n: v.counts.not_fixed },
    { key: "not_covered", label: "Not covered", n: v.counts.not_covered },
  ];
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiTile label="Verified" value={v.counts.verified} sub="gone in the after survey" />
        <KpiTile label="Not fixed" value={v.counts.not_fixed} sub="still there after repair" />
        <KpiTile label="Not covered" value={v.counts.not_covered} sub="the after drive didn't reach it" />
      </div>
      <div role="group" aria-label="Filter results" className="flex flex-wrap gap-2">
        {filters.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "min-h-11 rounded-lg border px-4 text-sm font-medium",
              filter === f.key ? "border-brand bg-brand text-white" : "hover:bg-grey-50",
            )}
          >
            {f.label} <span className="num">({f.n})</span>
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="text-muted-foreground">No results in this filter.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[860px] text-left">
            <thead>
              <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
                <th scope="col" className="py-3 pr-4 font-semibold">Result</th>
                <th scope="col" className="py-3 pr-4 font-semibold">Finding</th>
                <th scope="col" className="py-3 pr-4 font-semibold">Severity</th>
                <th scope="col" className="py-3 pr-4 font-semibold">Before</th>
                <th scope="col" className="py-3 pr-4 font-semibold">After</th>
                <th scope="col" className="py-3 font-semibold">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.finding_id} className="border-b align-top last:border-0">
                  <td className="py-3 pr-4"><StatusPill status={r.status} /></td>
                  <td className="py-3 pr-4">
                    <Link
                      href={withSel("/map", { finding: r.finding_id })}
                      className="inline-flex min-h-11 flex-col justify-center font-medium text-link underline-offset-4 hover:underline"
                    >
                      {label(r.type)}
                      <span className="num text-xs font-normal text-muted-foreground">{r.finding_id}</span>
                    </Link>
                  </td>
                  <td className="py-3 pr-4"><SeverityBadge severity={r.severity} size="sm" /></td>
                  <td className="num py-3 pr-4 text-sm">{headline(r.before_metrics)}</td>
                  <td className="num py-3 pr-4 text-sm">
                    {r.status === "not_covered" ? "not surveyed" : r.after_metrics ? headline(r.after_metrics) : "gone"}
                    {r.after_match && <span className="block text-xs text-muted-foreground">{r.after_match}</span>}
                  </td>
                  <td className="py-3 text-sm">{r.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        <Num value={v.results.length} /> findings checked
        {v.workorder_id ? <> for work order <span className="num">{v.workorder_id}</span></> : null}.
      </p>
    </div>
  );
}

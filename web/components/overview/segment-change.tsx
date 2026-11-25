"use client";
import Link from "next/link";
import { ConditionChip } from "@/components/shared/condition-chip";
import { formatChainage, formatNumber } from "@/lib/format";
import type { Segment } from "@/lib/types";

/**
 * Condition per segment, baseline drive vs the other drive, matched by segment id.
 * Δ above +1 is an improvement (▲), below −1 a loss (▼); colour is never the only cue.
 */
export function SegmentChange({
  before,
  after,
  beforeName,
  afterName,
  withSel,
}: {
  before: Segment[];
  after: Segment[];
  beforeName: string;
  afterName: string;
  withSel: (path: string, extra?: Record<string, string>) => string;
}) {
  const byId = new Map(after.map((s) => [s.id, s]));
  const rows = before.map((b) => {
    const a = byId.get(b.id);
    const d = a && a.condition !== null && b.condition !== null ? a.condition - b.condition : null;
    return { b, a, d };
  });
  const improved = rows.filter((r) => r.d !== null && r.d > 1).length;
  const worse = rows.filter((r) => r.d !== null && r.d < -1).length;

  return (
    <>
      <p className="mb-3 text-sm text-muted-foreground md:text-[13px]">
        <span className="num font-medium text-grey-900">{improved}</span> better ·{" "}
        <span className="num font-medium text-grey-900">{worse}</span> worse ·{" "}
        <span className="num font-medium text-grey-900">{rows.length - improved - worse}</span> about the same
      </p>
      <div className="relative max-h-[22rem] overflow-auto">
        <table className="w-full text-sm md:text-[13px]">
          <caption className="sr-only">Condition per segment: {beforeName} compared with {afterName}</caption>
          <thead className="sticky top-0 bg-card">
            <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
              <th scope="col" className="py-2 pr-2 text-left font-semibold">Segment</th>
              <th scope="col" className="py-2 pr-2 text-left font-semibold">{beforeName}</th>
              <th scope="col" className="py-2 pr-2 text-left font-semibold">{afterName}</th>
              <th scope="col" className="py-2 text-right font-semibold">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ b, a, d }) => (
              <tr key={b.id} className="border-b last:border-0">
                <th scope="row" className="py-1 pr-2 text-left font-normal">
                  <Link href={withSel("/map", { segment: b.id })} className="inline-flex min-h-11 items-center gap-2 text-link underline-offset-4 hover:underline md:min-h-7">
                    <span className="num">{b.id}</span>
                    <span className="num text-xs text-muted-foreground">{formatChainage(b.s0)}</span>
                  </Link>
                </th>
                <td className="py-1 pr-2"><ConditionChip score={b.condition} showLabel={false} /></td>
                <td className="py-1 pr-2">{a ? <ConditionChip score={a.condition} showLabel={false} /> : <span className="text-muted-foreground">not driven</span>}</td>
                <td className="num py-1 text-right whitespace-nowrap">
                  {d === null ? (
                    <span className="text-muted-foreground">–</span>
                  ) : d > 1 ? (
                    <span className="font-medium text-sev-low-fg">▲ +{formatNumber(d, 1)}</span>
                  ) : d < -1 ? (
                    <span className="font-medium text-sev-high-fg">▼ {formatNumber(d, 1)}</span>
                  ) : (
                    <span className="text-grey-600">= {formatNumber(d, 1)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

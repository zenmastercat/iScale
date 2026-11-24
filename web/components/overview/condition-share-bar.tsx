import { conditionShares } from "@/lib/condition";
import { formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Segment } from "@/lib/types";

/** Share of route length per condition band: one stacked bar + legend with percentages. */
export function ConditionShareBar({ segments }: { segments: Segment[] }) {
  const shares = conditionShares(segments);
  // legend: the four main bands always, others only when present
  const legend = shares.filter((s, i) => i < 4 || s.share > 0);
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-grey-100" aria-hidden>
        {shares
          .filter((s) => s.share > 0)
          .map((s) => (
            <span key={s.band.rating} className={s.band.bg} style={{ width: `${s.share * 100}%` }} />
          ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-sm" aria-label="Share of road length by condition">
        {legend.map((s) => (
          <li key={s.band.rating} className="inline-flex items-center gap-2">
            <span aria-hidden className={cn("size-3 rounded-[2px]", s.band.bg)} />
            <span className="text-grey-700">
              {s.band.label}
              {s.band.range && <span className="num text-grey-600"> ({s.band.range})</span>}
            </span>
            <span className="num font-medium text-grey-900">{formatPercent(s.share)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { SeverityIcon } from "@/components/shared/severity-badge";
import { findingChainage, isOpenDefect } from "@/lib/chainage";
import { bandFor } from "@/lib/condition";
import { formatChainage, formatNumber } from "@/lib/format";
import { useSelection } from "@/lib/selection";
import { cn } from "@/lib/utils";
import type { Finding, Segment, Severity } from "@/lib/types";

interface Mark {
  id: string;
  severity: Severity;
  segment: string;
  /** 0-1 along the route */
  pos: number;
  /** stacking slot when marks are close together */
  slot: number;
  label: string;
}

/**
 * The route as a straight bar: one block per segment (width ∝ length) coloured by condition,
 * open-defect marks above, segment id + score below. Hover/focus highlights a segment and its marks.
 */
export function ChainageStrip({
  segments,
  findings,
  labelFor,
}: {
  segments: Segment[];
  findings: Finding[];
  labelFor: (type: string) => string;
}) {
  const { withSel } = useSelection();
  const [hover, setHover] = useState<string | null>(null);
  const start = segments[0]?.s0 ?? 0;
  const end = segments[segments.length - 1]?.s1 ?? 1;
  const total = end - start || 1;

  const marks = useMemo(() => {
    const out: Mark[] = [];
    const sorted = findings
      .filter(isOpenDefect)
      .map((f) => ({ f, c: findingChainage(f, segments) }))
      .filter((x): x is { f: Finding; c: number } => x.c !== null)
      .sort((a, b) => a.c - b.c);
    // nudge marks that would overlap (closer than ~1.6% of the route) into side-by-side slots
    let lastPos = -1;
    let slot = 0;
    for (const { f, c } of sorted) {
      const pos = (c - start) / total;
      slot = pos - lastPos < 0.016 ? slot + 1 : 0;
      if (slot === 0) lastPos = pos;
      out.push({ id: f.id, severity: f.severity!, segment: f.segment_id ?? "", pos, slot, label: labelFor(f.type) });
    }
    return out;
  }, [findings, segments, start, total, labelFor]);

  const showLabels = segments.length <= 16;
  const mid = start + total / 2;

  return (
    <div className="relative overflow-x-auto pb-1">
      <div className="min-w-[640px]" onMouseLeave={() => setHover(null)}>
        {/* defect marks */}
        <div className="relative h-6" aria-hidden>
          {marks.map((m) => (
            <span
              key={m.id}
              title={`${m.id} · ${m.label} · ${m.severity}`}
              className={cn(
                "absolute top-1 -translate-x-1/2 transition-opacity",
                hover && hover !== m.segment && "opacity-25",
              )}
              style={{ left: `calc(${m.pos * 100}% + ${m.slot * 14}px)` }}
            >
              <SeverityIcon severity={m.severity} size={13} />
            </span>
          ))}
        </div>

        {/* segments */}
        <ol className="flex gap-[3px]" aria-label="Route condition by segment">
          {segments.map((s) => {
            const b = bandFor(s.condition);
            const n = marks.filter((m) => m.segment === s.id).length;
            const dim = hover && hover !== s.id;
            return (
              <li key={s.id} style={{ flexGrow: s.length_m, flexBasis: 0 }} className="min-w-0">
                <Link
                  href={withSel("/map", { segment: s.id })}
                  onMouseEnter={() => setHover(s.id)}
                  onFocus={() => setHover(s.id)}
                  onBlur={() => setHover(null)}
                  aria-label={`${s.id}, chainage ${formatChainage(s.s0)} to ${formatChainage(s.s1)}, condition ${
                    s.condition === null ? "no data" : formatNumber(s.condition, 1)
                  } ${b.label}, ${n} open defect${n === 1 ? "" : "s"}. Show on map`}
                  className={cn(
                    "block h-11 rounded-[3px] outline-offset-2 transition-[opacity,box-shadow]",
                    b.bg,
                    dim && "opacity-35",
                    hover === s.id && "ring-2 ring-brand ring-offset-1",
                  )}
                />
                {showLabels && (
                  <div
                    className={cn(
                      "mt-1.5 flex flex-wrap items-baseline justify-between gap-x-1 px-0.5 text-xs transition-opacity",
                      dim && "opacity-40",
                    )}
                    aria-hidden
                  >
                    <span className="num text-grey-600">{s.id}</span>
                    <span className="num font-semibold text-grey-900">
                      {s.condition === null ? "–" : formatNumber(s.condition, 1)}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ol>

        {/* chainage ticks */}
        <div className="num mt-2 flex justify-between text-xs text-grey-600" aria-hidden>
          <span>{formatChainage(start)}</span>
          <span>{formatChainage(mid)}</span>
          <span>{formatChainage(end)}</span>
        </div>
      </div>
    </div>
  );
}

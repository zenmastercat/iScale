"use client";
import { SeverityIcon } from "@/components/shared";
import { CONDITION_BANDS } from "@/lib/condition";
import type { Severity } from "@/lib/types";

const SEV: Severity[] = ["high", "medium", "low"];

export function MapLegend({ showCondition, showDefects }: { showCondition: boolean; showDefects: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 pt-3 text-sm" aria-label="Legend">
      {showCondition && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold">Condition</span>
          {CONDITION_BANDS.map((b) => (
            <span key={b.rating} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-5 rounded-full" style={{ background: b.color }} aria-hidden />
              {b.label} <span className="num text-xs">{b.range}</span>
            </span>
          ))}
        </div>
      )}
      {showDefects && (
        <div className="flex items-center gap-3">
          <span className="font-semibold">Defects</span>
          {SEV.map((s) => (
            <span key={s} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <SeverityIcon severity={s} size={11} />
              <span className="capitalize">{s}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

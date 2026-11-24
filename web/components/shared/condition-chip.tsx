import { bandFor } from "@/lib/condition";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Condition score with its band: swatch + score + band word, e.g. "■ 77.6 Satisfactory". */
export function ConditionChip({
  score,
  showLabel = true,
  className,
}: {
  /** 0-100, or null for "no data" */
  score: number | null | undefined;
  showLabel?: boolean;
  className?: string;
}) {
  const b = bandFor(score);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm whitespace-nowrap", className)}>
      <span aria-hidden className={cn("size-2.5 shrink-0 rounded-[2px]", b.bg)} />
      {score !== null && score !== undefined && <span className="num font-medium">{formatNumber(score, 1)}</span>}
      {(showLabel || score === null || score === undefined) && <span className="text-muted-foreground">{b.label}</span>}
    </span>
  );
}

"use client";
import { SeverityIcon } from "@/components/shared";
import { Num } from "@/components/shared";
import { findingChainage } from "@/lib/chainage";
import { formatChainage } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Finding, Segment } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Bounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** Side list of defects, in Fix first order (unranked last). Hover highlights the marker; click opens the drawer. */
export function DefectList({
  findings,
  segments,
  rank,
  labelFor,
  selectedId,
  bounds,
  onlyInView,
  onOnlyInView,
  onHover,
  onSelect,
}: {
  findings: Finding[];
  segments: Segment[];
  rank: Map<string, number>;
  labelFor: (code: string) => string;
  selectedId: string | null;
  bounds: Bounds | null;
  onlyInView: boolean;
  onOnlyInView: (v: boolean) => void;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const inView = (f: Finding) => !bounds || (f.lon >= bounds.west && f.lon <= bounds.east && f.lat >= bounds.south && f.lat <= bounds.north);
  const list = findings
    .filter((f) => f.severity && (!onlyInView || inView(f)))
    .sort((a, b) => (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9) || a.id.localeCompare(b.id));
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-semibold">
          {t("Defects", "ข้อบกพร่อง")} <span className="num font-normal text-muted-foreground">{list.length}</span>
        </h2>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" className="size-4" checked={onlyInView} onChange={(e) => onOnlyInView(e.target.checked)} />
          {t("Only in view", "เฉพาะที่เห็น")}
        </label>
      </div>
      {list.length === 0 ? (
        <p className="p-3 text-sm text-muted-foreground">{t("No defects here.", "ไม่มีข้อบกพร่องในพื้นที่นี้")}</p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto pb-20">
          {list.map((f) => {
            const resolved = f.status === "fixed" || f.status === "verified" || f.status === "dismissed";
            const at = findingChainage(f, segments);
            const name = `${f.id}, ${labelFor(f.type)}${f.segment_id ? `, ${f.segment_id}` : ""}`;
            return (
              <li key={f.id} className="border-b last:border-b-0">
                <button
                  type="button"
                  onClick={() => onSelect(f.id)}
                  onMouseEnter={() => onHover(f.id)}
                  onMouseLeave={() => onHover(null)}
                  onFocus={() => onHover(f.id)}
                  onBlur={() => onHover(null)}
                  title={name}
                  aria-label={name}
                  aria-current={selectedId === f.id || undefined}
                  className={cn("flex min-h-11 w-full items-start gap-2 px-3 py-2 text-left hover:bg-grey-50 focus-visible:bg-grey-50", selectedId === f.id && "bg-brand/10", resolved && "opacity-60")}
                >
                  <span className="mt-0.5">{f.severity && <SeverityIcon severity={f.severity} size={13} title={t(`${f.severity} severity`, `ความรุนแรง${{ high: "สูง", medium: "กลาง", low: "ต่ำ" }[f.severity]}`)} />}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{labelFor(f.type)}</span>
                    <span className="num block text-xs text-muted-foreground">
                      {at !== null ? `${formatChainage(at)} m` : f.segment_id}
                      {rank.has(f.id) && ` · #${rank.get(f.id)}`}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {f.metrics.depth_max_m !== undefined && <Num value={f.metrics.depth_max_m * 100} digits={1} unit="cm" />}
                      {f.metrics.depth_max_m !== undefined && f.metrics.area_m2 !== undefined && " · "}
                      {f.metrics.area_m2 !== undefined && <Num value={f.metrics.area_m2} digits={2} unit="m²" />}
                    </span>
                    <ReviewChip f={f} />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ReviewChip({ f }: { f: Finding }) {
  const t = useT();
  const v = f.review?.verdict;
  const base = "mt-1 inline-block rounded border px-1.5 py-px text-[11px] font-medium";
  if (v === "correct") return <span className={cn(base, "border-sev-low bg-sev-low-bg text-sev-low-fg")}>✓ {t("Confirmed", "ยืนยันแล้ว")}</span>;
  if (v === "wrong") return <span className={cn(base, "border-grey-300 bg-grey-100 text-grey-600")}>✕ {t("Wrong", "ผิด")}</span>;
  if (v === "unsure") return <span className={cn(base, "border-grey-300 bg-white text-grey-700")}>? {t("Unsure", "ไม่แน่ใจ")}</span>;
  return <span className={cn(base, "border-grey-300 bg-white text-grey-700")}>{t("Needs review", "ต้องตรวจ")}</span>;
}

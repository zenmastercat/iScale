"use client";
import { SeverityIcon } from "@/components/shared";
import { CONDITION_BANDS } from "@/lib/condition";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Segment } from "@/lib/types";
import { METRICS, metricScale, type ColourBy } from "./metrics";
import type { Severity } from "@/lib/types";

const SEV: Severity[] = ["high", "medium", "low"];

export function MapLegend({ showCondition, showDefects, colourBy, segments }: { showCondition: boolean; showDefects: boolean; colourBy: ColourBy; segments: Segment[] }) {
  const t = useT();
  const band: Record<string, string> = { good: "ดี", satisfactory: "พอใช้", fair: "ปานกลาง", poor: "แย่", "very poor": "แย่มาก", failed: "ชำรุด" };
  const sev: Record<string, string> = { high: "สูง", medium: "กลาง", low: "ต่ำ" };
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 pt-3 text-sm" aria-label={t("Legend", "คำอธิบายสัญลักษณ์")}>
      {showCondition && colourBy !== "condition" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold">{t(METRICS[colourBy].en, METRICS[colourBy].th)}</span>
          {metricScale(segments, METRICS[colourBy]).steps.map((st, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-5 rounded-full" style={{ background: st.color }} aria-hidden />
              <span className="num text-xs">
                {formatNumber(st.from, METRICS[colourBy].digits)}–{formatNumber(st.to, METRICS[colourBy].digits)} {METRICS[colourBy].unit}
              </span>
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="h-1.5 w-5 rounded-full bg-[#9ca3af]" aria-hidden />
            {t("No value", "ไม่มีค่า")}
          </span>
        </div>
      )}
      {showCondition && colourBy === "condition" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold">{t("Condition", "สภาพถนน")}</span>
          {CONDITION_BANDS.map((b) => (
            <span key={b.rating} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-5 rounded-full" style={{ background: b.color }} aria-hidden />
              {t(b.label, band[b.rating])} <span className="num text-xs">{b.range}</span>
            </span>
          ))}
        </div>
      )}
      {showDefects && (
        <div className="flex items-center gap-3">
          <span className="font-semibold">{t("Defects", "ข้อบกพร่อง")}</span>
          {SEV.map((s) => (
            <span key={s} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <SeverityIcon severity={s} size={11} />
              <span className="capitalize">{t(s, sev[s])}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

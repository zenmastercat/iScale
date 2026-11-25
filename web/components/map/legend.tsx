"use client";
import { SeverityIcon } from "@/components/shared";
import { CONDITION_BANDS } from "@/lib/condition";
import { useT } from "@/lib/i18n";
import type { Severity } from "@/lib/types";

const SEV: Severity[] = ["high", "medium", "low"];

export function MapLegend({ showCondition, showDefects }: { showCondition: boolean; showDefects: boolean }) {
  const t = useT();
  const band: Record<string, string> = { good: "ดี", satisfactory: "พอใช้", fair: "ปานกลาง", poor: "แย่", "very poor": "แย่มาก", failed: "ชำรุด" };
  const sev: Record<string, string> = { high: "สูง", medium: "กลาง", low: "ต่ำ" };
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 pt-3 text-sm" aria-label={t("Legend", "คำอธิบายสัญลักษณ์")}>
      {showCondition && (
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

"use client";
import { Money, Num } from "@/components/shared/num";
import { SeverityIcon } from "@/components/shared/severity-badge";
import { useT } from "@/lib/i18n";
import type { PriorityItem, Severity } from "@/lib/types";

const SEV: Record<Severity, [string, string]> = { high: ["high", "สูง"], medium: ["medium", "กลาง"], low: ["low", "ต่ำ"] };

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3 md:px-3 md:py-2">
      <p className="text-sm text-muted-foreground md:text-[13px]">{label}</p>
      <div className="mt-1 text-brand">{children}</div>
    </div>
  );
}

/** One row of totals over the ranked list. */
export function SummaryStrip({ items, currency }: { items: PriorityItem[]; currency: string }) {
  const t = useT();
  const by: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  for (const i of items) by[i.severity]++;
  const pins = items.filter((i) => i.kind === "pin").length;
  const cost = items.reduce((a, i) => a + (i.cost ?? 0), 0);
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:mb-3 md:grid-cols-4 md:gap-3">
      <Cell label={t("To fix", "ต้องซ่อม")}>
        <p className="num text-2xl font-semibold md:text-xl">{items.length}</p>
        {pins > 0 && <p className="text-sm text-muted-foreground md:text-[13px]"><Num value={pins} /> {t("shared pins included", "รวมหมุดที่แชร์")}</p>}
      </Cell>
      <Cell label={t("By severity", "ตามความรุนแรง")}>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm md:text-[13px]">
          {(["high", "medium", "low"] as const).map((s) => (
            <li key={s} className="inline-flex items-center gap-1 text-grey-900">
              <SeverityIcon severity={s} />
              <span className="num font-semibold">{by[s]}</span> {t(SEV[s][0], SEV[s][1])}
            </li>
          ))}
        </ul>
      </Cell>
      <Cell label={t("Repair estimate", "ประมาณการซ่อม")}>
        <p className="text-2xl font-semibold md:text-xl"><Money amount={cost} currency={currency} /></p>
        <p className="text-sm text-muted-foreground md:text-[13px]">{t("excl. mobilisation", "ไม่รวมค่าเคลื่อนย้าย")}</p>
      </Cell>
      <Cell label={t("Highest priority", "ลำดับสำคัญสุด")}>
        <p className="truncate text-base font-semibold md:text-[15px]">{items[0]?.label ?? "–"}</p>
        <p className="num text-sm text-muted-foreground md:text-[13px]">{items[0] ? `#1 · ${items[0].priority.toFixed(2)}` : ""}</p>
      </Cell>
    </div>
  );
}

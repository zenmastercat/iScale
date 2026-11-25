"use client";
import { useState } from "react";
import { formatDate, humanize } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { FindingHistoryEntry } from "@/lib/types";

const MAX = 5;

/** Event words come from civil/api.py: created, edited, planned, "workorder <status>", "verification: <status>". */
function useEventLabel() {
  const t = useT();
  return (e: string) => {
    if (e === "created") return t("Created", "สร้างรายการ");
    if (e === "edited") return t("Edited", "แก้ไข");
    if (e === "planned") return t("Added to a work order", "เพิ่มในใบสั่งงาน");
    if (e.startsWith("workorder ")) return t(`Work order ${e.slice(10)}`, `ใบสั่งงาน: ${e.slice(10)}`);
    if (e.startsWith("verification: ")) return t(`Verification: ${humanize(e.slice(14)).toLowerCase()}`, `ผลตรวจสอบ: ${e.slice(14)}`);
    return humanize(e);
  };
}

export function History({ entries }: { entries: FindingHistoryEntry[] | undefined }) {
  const t = useT();
  const label = useEventLabel();
  const [all, setAll] = useState(false);
  if (!entries?.length) return null;
  const sorted = [...entries].sort((a, b) => b.t - a.t);
  const shown = all ? sorted : sorted.slice(0, MAX);
  return (
    <section className="flex flex-col gap-2 border-t pt-3" aria-label={t("History", "ประวัติ")}>
      <h3 className="text-sm font-semibold">{t("History", "ประวัติ")}</h3>
      <ol className="flex flex-col gap-2 border-l pl-3 text-sm">
        {shown.map((h, i) => (
          <li key={`${h.t}-${i}`} className="relative">
            <span className="absolute top-1.5 -left-[17px] size-2 rounded-full bg-grey-400" aria-hidden />
            <div className="font-medium">{label(h.event)}</div>
            <div className="text-xs text-muted-foreground">
              <span className="num">{formatDate(h.t)}</span>
              {h.by && ` · ${h.by}`}
              {h.workorder && <> · <span className="num">{h.workorder}</span></>}
              {h.fields?.length ? ` · ${h.fields.join(", ")}` : ""}
            </div>
          </li>
        ))}
      </ol>
      {sorted.length > MAX && (
        <button type="button" className="min-h-11 self-start text-sm font-medium text-link underline underline-offset-4 md:min-h-8" onClick={() => setAll((v) => !v)}>
          {all ? t("Show fewer", "แสดงน้อยลง") : t(`Show all ${sorted.length}`, `แสดงทั้งหมด ${sorted.length} รายการ`)}
        </button>
      )}
    </section>
  );
}

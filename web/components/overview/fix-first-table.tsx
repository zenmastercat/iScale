"use client";
import Link from "next/link";
import { Money } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { Finding, PriorityItem } from "@/lib/types";

const EVIDENCE: Record<string, string> = {
  geometry: "Measured",
  decoder: "Measured + detector",
  manual: "Tagged by hand",
};

export function evidenceSource(f?: Finding) {
  if (!f) return "Shared pin";
  return EVIDENCE[f.source] ?? f.source;
}

const EVIDENCE_TH: Record<string, string> = { geometry: "วัดจริง", decoder: "วัดจริง + ตัวตรวจจับ", manual: "บันทึกด้วยมือ" };
/** Thai label for evidenceSource (CSV exports keep the English one). */
export function evidenceSourceTh(f?: Finding) {
  if (!f) return "หมุดที่แชร์";
  return EVIDENCE_TH[f.source] ?? f.source;
}

/** Top-N of GET /api/priority, with the measurement sentence from the analysis. */
export function FixFirstTable({
  items,
  findingsById,
  currency,
}: {
  items: PriorityItem[];
  findingsById: Map<string, Finding>;
  currency: string;
}) {
  const { withSel } = useSelection();
  const t = useT();
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[720px] text-left">
        <thead>
          <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">{t("Rank", "อันดับ")}</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">{t("Finding", "รายการ")}</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">{t("Severity", "ความรุนแรง")}</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">{t("Segment", "ช่วง")}</th>
            <th scope="col" className="py-3 md:py-2 pr-4 font-semibold">{t("Evidence", "หลักฐาน")}</th>
            <th scope="col" className="py-3 md:py-2 pr-4 text-right font-semibold">{t("Cost", "ค่าซ่อม")}</th>
            <th scope="col" className="py-3 md:py-2"><span className="sr-only">{t("Open", "เปิด")}</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const f = findingsById.get(it.id);
            return (
              <tr key={it.id} className="border-b last:border-0">
                <td className="num py-3 md:py-2 pr-4 font-semibold text-brand">#{it.rank}</td>
                <td className="py-3 md:py-2 pr-4">
                  <p className="font-medium text-grey-900">{it.label}</p>
                  {f?.evidence && <p className="text-sm text-muted-foreground">{f.evidence}</p>}
                </td>
                <td className="py-3 md:py-2 pr-4">
                  <SeverityBadge severity={it.severity} size="sm" />
                </td>
                <td className="num py-3 md:py-2 pr-4">{it.segment_id}</td>
                <td className="py-3 md:py-2 pr-4 text-sm text-grey-700">{t(evidenceSource(f), evidenceSourceTh(f))}</td>
                <td className="py-3 md:py-2 pr-4 text-right font-medium">
                  <Money amount={it.cost} currency={currency} />
                </td>
                <td className="py-3 md:py-2 text-right">
                  <Link
                    href={withSel("/map", { finding: it.id })}
                    className="inline-flex min-h-11 items-center px-1 font-medium text-link underline underline-offset-4 hover:text-brand"
                    aria-label={t(`Open ${it.label} ${it.id} on the map`, `เปิด ${it.label} ${it.id} บนแผนที่`)}
                  >
                    {t("Open", "เปิด")}
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

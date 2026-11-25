"use client";
import { MapPin, Users } from "lucide-react";
import Link from "next/link";
import { Money, Num } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { humanize } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { Finding, PriorityItem } from "@/lib/types";

const TH = "py-3 md:py-1.5 pr-4 font-semibold";

export function RankingTable({
  items,
  findingsById,
  currency,
}: {
  items: PriorityItem[];
  findingsById: Map<string, Finding>;
  currency: string;
}) {
  const t = useT();
  const { withSel } = useSelection();
  const detail = (it: PriorityItem, f?: Finding) =>
    it.kind === "pin" ? (
      <span className="inline-flex flex-wrap items-center gap-x-3">
        <span className="inline-flex items-center gap-1"><MapPin aria-hidden className="size-3.5" />{t("Shared pin", "หมุดที่แชร์")}{it.reporter ? ` ${t("by", "โดย")} ${it.reporter}` : ""}</span>
        <span className="inline-flex items-center gap-1">
          <Users aria-hidden className="size-3.5" />
          <Num value={it.confirmations ?? 0} /> {it.confirmations === 1 ? t("confirmation", "คนยืนยัน") : t("confirmations", "คนยืนยัน")}
        </span>
      </span>
    ) : (
      (f?.evidence ?? it.action)
    );
  const costBlock = (it: PriorityItem) => (
    <>
      {typeof it.cost === "number" && <p className="font-medium"><Money amount={it.cost} currency={currency} /></p>}
      {it.materials && (
        <p className="text-sm md:text-[13px] text-muted-foreground">
          {t("materials", "วัสดุ")} <Money amount={it.materials.materials_cost} style="symbol" symbol={it.materials.symbol} />
        </p>
      )}
      {typeof it.cost !== "number" && !it.materials && <span className="text-muted-foreground">–</span>}
    </>
  );
  return (
    <>
    <ul className="flex flex-col gap-3 md:hidden">
      {items.map((it) => (
        <li key={`${it.kind}-${it.id}`} className="rounded-lg border p-4">
          <div className="flex items-start justify-between gap-3">
            <p className="font-medium text-grey-900">
              <span className="num mr-2 font-semibold text-brand">#{it.rank}</span>
              {it.label}
            </p>
            <SeverityBadge severity={it.severity} size="sm" />
          </div>
          <p className="mt-1 text-sm md:text-[13px] text-muted-foreground">{detail(it, findingsById.get(it.id))}</p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:text-[13px]">
            <div>
              <dt className="text-muted-foreground">{t("Segment", "ช่วง")}</dt>
              <dd className="num">{it.segment_id ?? t("Shared pin", "หมุดที่แชร์")}</dd>
            </div>
            <div className="text-right">
              <dt className="text-muted-foreground">{t("Cost", "ค่าใช้จ่าย")}</dt>
              <dd>{costBlock(it)}</dd>
            </div>
          </dl>
          {it.kind === "pin" ? (
            // shared pins are not findings of this survey, so the map drawer cannot open them: use their own map link
            it.maps_url ? (
              <a
                href={it.maps_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 flex min-h-11 w-full items-center justify-center rounded-lg border font-medium text-link hover:bg-grey-50"
                aria-label={`${t("Open in maps (new tab)", "เปิดในแผนที่ (แท็บใหม่)")}: ${it.label}`}
              >
                {t("Open in maps", "เปิดในแผนที่")}
              </a>
            ) : null
          ) : (
            <Link
              href={withSel("/map", { finding: it.id })}
              className="mt-3 flex min-h-11 w-full items-center justify-center rounded-lg border font-medium text-link hover:bg-grey-50"
              aria-label={`${t("Open on map", "เปิดบนแผนที่")}: ${it.label} ${it.id}`}
            >
              {t("Open on map", "เปิดบนแผนที่")}
            </Link>
          )}
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="md:text-[13px] w-full min-w-[860px] text-left">
        <thead>
          <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
            <th scope="col" className={TH}>{t("Rank", "ลำดับ")}</th>
            <th scope="col" className={TH}>{t("Finding", "รายการ")}</th>
            <th scope="col" className={TH}>{t("Severity", "ความรุนแรง")}</th>
            <th scope="col" className={TH}>{t("Road · traffic", "ถนน · การจราจร")}</th>
            <th scope="col" className={`${TH} text-right`}>{t("Priority", "ลำดับความสำคัญ")}</th>
            <th scope="col" className={`${TH} text-right`}>{t("Cost", "ค่าใช้จ่าย")}</th>
            <th scope="col" className="py-3 md:py-1.5"><span className="sr-only">{t("Open", "เปิด")}</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const f = findingsById.get(it.id);
            return (
              <tr key={`${it.kind}-${it.id}`} className="border-b last:border-0">
                <td className="num py-3 md:py-1.5 pr-4 font-semibold text-brand">#{it.rank}</td>
                <td className="py-3 md:py-1.5 pr-4">
                  <p className="font-medium text-grey-900">{it.label}</p>
                  <p className="text-sm md:text-[13px] text-muted-foreground">{detail(it, f)}</p>
                </td>
                <td className="py-3 md:py-1.5 pr-4"><SeverityBadge severity={it.severity} size="sm" /></td>
                <td className="py-3 md:py-1.5 pr-4 text-sm md:text-[13px]">
                  {it.road ? humanize(it.road) : t("Unclassified", "ไม่ระบุประเภท")}
                  <span className="text-muted-foreground"> · {t("traffic", "จราจร")} ×</span>
                  <Num value={it.traffic_factor} digits={2} />
                </td>
                <td className="py-3 md:py-1.5 pr-4 text-right"><Num value={it.priority} digits={2} /></td>
                <td className="py-3 md:py-1.5 pr-4 text-right">{costBlock(it)}
                </td>
                <td className="py-3 md:py-1.5 text-right">
                  {it.kind === "pin" ? (
                    it.maps_url ? (
                      <a
                        href={it.maps_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-11 items-center px-1 font-medium text-link underline underline-offset-4 hover:text-brand"
                        aria-label={`${t("Open in maps (new tab)", "เปิดในแผนที่ (แท็บใหม่)")}: ${it.label}`}
                      >
                        {t("Maps", "แผนที่")}
                      </a>
                    ) : null
                  ) : (
                    <Link
                      href={withSel("/map", { finding: it.id })}
                      className="inline-flex min-h-11 items-center px-1 font-medium text-link underline underline-offset-4 hover:text-brand"
                      aria-label={`${t("Open on map", "เปิดบนแผนที่")}: ${it.label} ${it.id}`}
                    >
                      {t("Open", "เปิด")}
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}

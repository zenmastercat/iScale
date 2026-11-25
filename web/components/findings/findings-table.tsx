"use client";
import { ArrowDown, ArrowUp } from "lucide-react";
import Link from "next/link";
import { Money, Num, SeverityBadge, StatusPill } from "@/components/shared";
import { formatChainage } from "@/lib/format";
import type { FindingsFilter, SortKey } from "@/lib/findings-filter";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { cn } from "@/lib/utils";
import type { Row } from "./rows";

const COLS: { key: SortKey; label: string; th: string; num?: boolean }[] = [
  { key: "rank", label: "Rank", th: "อันดับ", num: true },
  { key: "id", label: "ID", th: "รหัส" },
  { key: "type", label: "Type", th: "ประเภท" },
  { key: "severity", label: "Severity", th: "ความรุนแรง" },
  { key: "status", label: "Status", th: "สถานะ" },
  { key: "segment", label: "Segment", th: "ช่วง" },
  { key: "chainage", label: "Chainage", th: "ระยะทาง", num: true },
  { key: "depth", label: "Depth", th: "ความลึก", num: true },
  { key: "area", label: "Area", th: "พื้นที่", num: true },
  { key: "volume", label: "Volume", th: "ปริมาตร", num: true },
  { key: "cost", label: "Materials", th: "วัสดุ", num: true },
  { key: "source", label: "Source", th: "แหล่งที่มา" },
  { key: "workorder", label: "Work order", th: "ใบสั่งงาน" },
];

const sum = (rows: Row[], pick: (r: Row) => number | null) => rows.reduce((a, r) => a + (pick(r) ?? 0), 0);

export function FindingsTable({ rows, filter, setFilter }: { rows: Row[]; filter: FindingsFilter; setFilter: (f: FindingsFilter) => void }) {
  const t = useT();
  const { withSel } = useSelection();
  const sort = filter.sort ?? { key: "chainage" as SortKey, desc: false };
  const symbol = rows.find((r) => r.f.cost)?.f.cost?.symbol ?? "฿";
  const toggle = (key: SortKey) =>
    setFilter({ ...filter, sort: sort.key === key && !sort.desc ? { key, desc: true } : { key, desc: false } });
  const link = (id: string) => withSel("/map", { finding: id });

  return (
    <>
      {/* desktop table */}
      <div className="hidden max-h-[calc(100dvh-16rem)] overflow-auto rounded-lg border bg-card md:block">
        <table className="w-full border-collapse text-left md:text-[13px]">
          <thead className="sticky top-0 z-10 bg-grey-50">
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}
                  className={cn("border-b px-2 py-1.5 font-medium whitespace-nowrap", c.num && "text-right")}
                >
                  <button type="button" onClick={() => toggle(c.key)} className={cn("inline-flex items-center gap-1 hover:text-brand", c.num && "flex-row-reverse")}>
                    {t(c.label, c.th)}
                    {sort.key === c.key && (sort.desc ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUp className="size-3" aria-hidden />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.f.id} className="border-b last:border-b-0 hover:bg-grey-50">
                <td className="px-2 py-1.5 text-right">{r.rank !== null ? <span className="num">{r.rank}</span> : "–"}</td>
                <td className="px-2 py-1.5">
                  <Link href={link(r.f.id)} className="num text-link underline underline-offset-2 hover:text-brand" aria-label={t(`Open ${r.label} ${r.f.id} on the map`, `เปิด ${r.label} ${r.f.id} บนแผนที่`)}>{r.f.id}</Link>
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap">{r.label}</td>
                <td className="px-2 py-1.5">{r.f.severity ? <SeverityBadge severity={r.f.severity} size="sm" /> : <span className="text-muted-foreground">{t("Asset", "สินทรัพย์")}</span>}</td>
                <td className="px-2 py-1.5"><StatusPill status={r.f.status} /></td>
                <td className="num px-2 py-1.5">{r.f.segment_id ?? "–"}</td>
                <td className="num px-2 py-1.5 text-right">{r.chainage !== null ? formatChainage(r.chainage) : "–"}</td>
                <td className="px-2 py-1.5 text-right"><Num value={r.depthCm} digits={1} unit="cm" /></td>
                <td className="px-2 py-1.5 text-right"><Num value={r.area} digits={2} unit="m²" /></td>
                <td className="px-2 py-1.5 text-right"><Num value={r.volumeL} digits={1} unit="L" /></td>
                <td className="px-2 py-1.5 text-right">{r.cost !== null ? <Money amount={r.cost} style="symbol" symbol={r.f.cost?.symbol} /> : "–"}</td>
                <td className="px-2 py-1.5 whitespace-nowrap">{r.source}</td>
                <td className="num px-2 py-1.5">{r.workorder ?? "–"}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-grey-50 font-medium">
            <tr>
              <td className="border-t px-2 py-1.5" colSpan={7}>{t("Total", "รวม")} · <span className="num">{rows.length}</span> {t("findings", "รายการ")}</td>
              <td className="border-t px-2 py-1.5" />
              <td className="border-t px-2 py-1.5 text-right"><Num value={sum(rows, (r) => r.area)} digits={2} unit="m²" /></td>
              <td className="border-t px-2 py-1.5 text-right"><Num value={sum(rows, (r) => r.volumeL)} digits={1} unit="L" /></td>
              <td className="border-t px-2 py-1.5 text-right"><Money amount={sum(rows, (r) => r.cost)} style="symbol" symbol={symbol} /></td>
              <td className="border-t px-2 py-1.5" colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* phone cards */}
      <ul className="flex flex-col gap-2 md:hidden">
        {rows.map((r) => (
          <li key={r.f.id}>
            <Link href={link(r.f.id)} className="flex min-h-11 flex-col gap-1.5 rounded-lg border bg-card p-3">
              <span className="flex items-center justify-between gap-2">
                <span className="font-semibold">{r.label}</span>
                <span className="num text-xs text-muted-foreground">{r.f.id}</span>
              </span>
              <span className="flex flex-wrap items-center gap-2">
                {r.f.severity && <SeverityBadge severity={r.f.severity} size="sm" />}
                <StatusPill status={r.f.status} />
                <span className="num text-xs text-muted-foreground">{r.f.segment_id}{r.chainage !== null && ` · ${formatChainage(r.chainage)}`}</span>
              </span>
              <span className="flex flex-wrap gap-x-3 text-sm text-muted-foreground">
                {r.depthCm !== null && <Num value={r.depthCm} digits={1} unit="cm" />}
                {r.area !== null && <Num value={r.area} digits={2} unit="m²" />}
                {r.cost !== null && <Money amount={r.cost} style="symbol" symbol={r.f.cost?.symbol} />}
              </span>
            </Link>
          </li>
        ))}
        <li className="rounded-lg border bg-grey-50 p-3 text-sm font-medium">
          {t("Total", "รวม")} · <span className="num">{rows.length}</span> · <Num value={sum(rows, (r) => r.area)} digits={2} unit="m²" /> ·{" "}
          <Num value={sum(rows, (r) => r.volumeL)} digits={1} unit="L" /> · <Money amount={sum(rows, (r) => r.cost)} style="symbol" symbol={symbol} />
        </li>
      </ul>
    </>
  );
}

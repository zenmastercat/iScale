"use client";
import { ArrowDown, ArrowUp, Check, ChevronDown, ChevronRight, CircleHelp, Hand, Ruler, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef } from "react";
import { ConditionChip, Money, Num, SeverityBadge, StatusPill } from "@/components/shared";
import { formatChainage } from "@/lib/format";
import type { FindingsFilter, SortKey } from "@/lib/findings-filter";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { Segment } from "@/lib/types";
import { cn } from "@/lib/utils";
import { groupRows, type Row } from "./rows";

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

/** Compact Source cell: an icon with the full words in the tooltip and for screen readers. */
function SourceIcon({ source, label }: { source: string; label: string }) {
  const Icon = source === "decoder" ? ShieldCheck : source === "manual" ? Hand : Ruler;
  return (
    <span className="inline-flex items-center text-grey-700">
      <Icon className="size-4" aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
}

const sum = (rows: Row[], pick: (r: Row) => number | null) => rows.reduce((a, r) => a + (pick(r) ?? 0), 0);

/** Only open defects can go into a work order (assets and resolved/planned rows have no checkbox). */
export const isSelectable = (r: Row) => !!r.f.severity && r.f.status === "open";

export function FindingsTable({
  rows,
  filter,
  setFilter,
  segments,
  selected,
  onToggle,
  onToggleAll,
  focusId,
  groupBySegment,
  collapsed,
  onCollapse,
}: {
  rows: Row[];
  filter: FindingsFilter;
  setFilter: (f: FindingsFilter) => void;
  segments: Segment[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (checked: boolean) => void;
  focusId: string | null;
  groupBySegment: boolean;
  collapsed: Set<string>;
  onCollapse: (segmentId: string) => void;
}) {
  const t = useT();
  const { withSel } = useSelection();
  const sort = filter.sort ?? { key: "chainage" as SortKey, desc: false };
  const symbol = rows.find((r) => r.f.cost)?.f.cost?.symbol ?? "฿";
  const toggle = (key: SortKey) =>
    setFilter({ ...filter, sort: sort.key === key && !sort.desc ? { key, desc: true } : { key, desc: false } });
  const link = (id: string) => withSel("/map", { finding: id });

  const selectable = useMemo(() => rows.filter(isSelectable), [rows]);
  const picked = selectable.filter((r) => selected.has(r.f.id)).length;
  const allRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (allRef.current) allRef.current.indeterminate = picked > 0 && picked < selectable.length;
  }, [picked, selectable.length]);

  // keyboard row focus: keep it in view
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  useEffect(() => {
    if (!focusId) return;
    bodyRef.current?.querySelector<HTMLElement>(`[data-row-id="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusId]);

  // rows keep their sort order inside each group; groups run along the road
  const groups = useMemo(() => (groupBySegment ? groupRows(rows, segments) : null), [groupBySegment, rows, segments]);

  const rowEl = (r: Row) => {
    const can = isSelectable(r);
    return (
      <tr
        key={r.f.id}
        data-row-id={r.f.id}
        aria-selected={focusId === r.f.id || undefined}
        className={cn("border-b last:border-b-0 hover:bg-grey-50", focusId === r.f.id && "bg-brand/10 outline-2 -outline-offset-2 outline-brand", selected.has(r.f.id) && "bg-accent-blue/5")}
      >
        <td className="px-2 py-1">
          {can && (
            <input
              type="checkbox"
              className="size-4 align-middle"
              checked={selected.has(r.f.id)}
              onChange={() => onToggle(r.f.id)}
              aria-label={t(`Select ${r.f.id}`, `เลือก ${r.f.id}`)}
            />
          )}
        </td>
        <td className="px-2 py-1 text-right">{r.rank !== null ? <span className="num">{r.rank}</span> : "–"}</td>
        <td className="px-2 py-1">
          <Link href={link(r.f.id)} className="num whitespace-nowrap text-link underline underline-offset-2 hover:text-brand" aria-label={t(`Open ${r.label} ${r.f.id} on the map`, `เปิด ${r.label} ${r.f.id} บนแผนที่`)}>{r.f.id}</Link>
          {r.f.needs_review && <span className="ml-1.5 rounded border border-sev-medium bg-sev-medium-bg px-1 text-[11px] font-medium text-sev-medium-fg">▲ {t("Check first", "ตรวจก่อน")}</span>}
          {r.f.review && (
            <span
              className="ml-1.5 inline-flex align-middle text-grey-700"
              title={t(`3D check: ${r.f.review.verdict}`, `ตรวจ 3D: ${{ correct: "ถูกต้อง", wrong: "ผิด", unsure: "ไม่แน่ใจ" }[r.f.review.verdict]}`)}
            >
              {r.f.review.verdict === "correct" ? <Check className="size-3.5" aria-hidden /> : r.f.review.verdict === "wrong" ? <X className="size-3.5" aria-hidden /> : <CircleHelp className="size-3.5" aria-hidden />}
              <span className="sr-only">{t(`Reviewed: ${r.f.review.verdict}`, `ตรวจแล้ว: ${{ correct: "ถูกต้อง", wrong: "ผิด", unsure: "ไม่แน่ใจ" }[r.f.review.verdict]}`)}</span>
            </span>
          )}
        </td>
        <td className="max-w-36 truncate px-2 py-1" title={r.label}>{r.label}</td>
        <td className="px-2 py-1">{r.f.severity ? <SeverityBadge severity={r.f.severity} size="sm" className="py-0" /> : <span className="text-muted-foreground">{t("Asset", "สินทรัพย์")}</span>}</td>
        <td className="px-2 py-1"><StatusPill status={r.f.status} className="gap-1 py-0 text-xs" /></td>
        <td className="num px-2 py-1">{r.f.segment_id ?? "–"}</td>
        <td className="num px-2 py-1 text-right whitespace-nowrap">{r.chainage !== null ? formatChainage(r.chainage) : "–"}</td>
        <td className="px-2 py-1 text-right">{r.depthCm !== null && r.f.metrics.depth_assumed ? <span title={t("Assumed depth: not measured (camera only)", "ความลึกสมมติ: ไม่ได้วัด (กล้องอย่างเดียว)")}>~<Num value={r.depthCm} digits={1} unit="cm" /></span> : <Num value={r.depthCm} digits={1} unit="cm" />}</td>
        <td className="px-2 py-1 text-right"><Num value={r.area} digits={2} unit="m²" /></td>
        <td className="px-2 py-1 text-right"><Num value={r.volumeL} digits={1} unit="L" /></td>
        <td className="px-2 py-1 text-right">{r.cost !== null ? <Money amount={r.cost} style="symbol" symbol={r.f.cost?.symbol} /> : "–"}</td>
        <td className="px-2 py-1" title={r.source}>
          <SourceIcon source={r.f.source} label={r.source} />
        </td>
        <td className="num px-2 py-1 whitespace-nowrap">{r.workorder ?? "–"}</td>
      </tr>
    );
  };

  return (
    <>
      {/* desktop table */}
      <div className="hidden max-h-[calc(100dvh-16rem)] overflow-auto rounded-lg border bg-card md:block">
        <table className="w-full min-w-[1040px] border-collapse text-left md:text-[13px]">
          <thead className="sticky top-0 z-10 bg-grey-50">
            <tr>
              <th scope="col" className="w-8 border-b px-2 py-1.5">
                <input
                  ref={allRef}
                  type="checkbox"
                  className="size-4 align-middle"
                  disabled={selectable.length === 0}
                  checked={selectable.length > 0 && picked === selectable.length}
                  onChange={(e) => onToggleAll(e.target.checked)}
                  aria-label={t("Select all open defects shown", "เลือกข้อบกพร่องที่ยังไม่ซ่อมทั้งหมดที่แสดง")}
                />
              </th>
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
          <tbody ref={bodyRef}>
            {groups
              ? groups.map((g) => {
                  const closed = collapsed.has(g.id);
                  return [
                    <tr key={`g-${g.id}`} className="border-b bg-grey-50 font-medium">
                      <td className="px-2 py-1" colSpan={8}>
                        <button
                          type="button"
                          className="inline-flex items-center gap-2"
                          aria-expanded={!closed}
                          aria-label={t(`${closed ? "Expand" : "Collapse"} segment ${g.id || "none"}`, `${closed ? "ขยาย" : "ยุบ"}ช่วง ${g.id || "ไม่ระบุ"}`)}
                          onClick={() => onCollapse(g.id)}
                        >
                          {closed ? <ChevronRight className="size-4" aria-hidden /> : <ChevronDown className="size-4" aria-hidden />}
                          <span className="num">{g.id || "–"}</span>
                          {g.seg && <span className="num text-muted-foreground">{formatChainage(g.seg.s0)}–{formatChainage(g.seg.s1)}</span>}
                          {g.seg && <ConditionChip score={g.seg.condition} showLabel />}
                          <span className="text-muted-foreground"><span className="num">{g.list.length}</span> {t("findings", "รายการ")}</span>
                        </button>
                      </td>
                      <td className="px-2 py-1" />
                      <td className="px-2 py-1 text-right"><Num value={sum(g.list, (r) => r.area)} digits={2} unit="m²" /></td>
                      <td className="px-2 py-1 text-right"><Num value={sum(g.list, (r) => r.volumeL)} digits={1} unit="L" /></td>
                      <td className="px-2 py-1 text-right"><Money amount={sum(g.list, (r) => r.cost)} style="symbol" symbol={symbol} /></td>
                      <td className="px-2 py-1" colSpan={2} />
                    </tr>,
                    ...(closed ? [] : g.list.map(rowEl)),
                  ];
                })
              : rows.map(rowEl)}
          </tbody>
          <tfoot className="sticky bottom-0 bg-grey-50 font-medium">
            <tr>
              <td className="border-t px-2 py-1.5" colSpan={8}>{t("Total", "รวม")} · <span className="num">{rows.length}</span> {t("findings", "รายการ")}</td>
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
                {r.depthCm !== null && <>{r.f.metrics.depth_assumed && <span title={t("Assumed depth", "ความลึกสมมติ")}>~</span>}<Num value={r.depthCm} digits={1} unit="cm" /></>}
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

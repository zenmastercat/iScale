"use client";
/*
 * Straight-line diagram, as road agencies draw it: chainage runs left to right, one lane per measure.
 * Lanes: Condition (band blocks + score) · Defects (severity marks) · Road width · Coverage · Surface roughness.
 * Every segment column is a link to /map?segment=<id>; hover or focus highlights it across all lanes.
 */
import { Check } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { SEVERITY, SeverityIcon } from "@/components/shared";
import { findingChainage } from "@/lib/chainage";
import { bandFor } from "@/lib/condition";
import { formatChainage, formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Selection } from "@/lib/selection";
import type { Finding, Segment } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL_W = 128; // px, left label column
const MIN_TRACK_W = 640; // px, below this the box scrolls horizontally
const PX_PER_M = 4;
const TICK_M = 50;
const MARK = 16; // px per stacked defect mark

type Measure = (s: Segment) => number | null;

export function SegmentDiagram({
  segments,
  findings,
  labelFor,
  withSel,
}: {
  segments: Segment[];
  findings: Finding[];
  labelFor: (code: string) => string;
  withSel: Selection["withSel"];
}) {
  const t = useT();
  const [active, setActive] = useState<string | null>(null);

  const total = useMemo(() => Math.max(1, ...segments.map((s) => s.s1)), [segments]);
  const trackW = Math.max(MIN_TRACK_W, Math.round(total * PX_PER_M));
  const pct = (m: number) => `${(m / total) * 100}%`;
  const ticks = useMemo(() => Array.from({ length: Math.floor(total / TICK_M) + 1 }, (_, i) => i * TICK_M), [total]);

  // defects with their chainage; marks within 4 m of each other are stacked so none hides another
  const marks = useMemo(() => {
    const placed = findings
      .filter((f) => f.severity)
      .map((f) => ({ f, at: findingChainage(f, segments) }))
      .filter((m): m is { f: Finding; at: number } => m.at !== null)
      .sort((a, b) => a.at - b.at);
    const lastAt: number[] = []; // per stack row: chainage of the last mark placed there
    return placed.map((m) => {
      let row = lastAt.findIndex((x) => m.at - x > 4);
      if (row === -1) row = lastAt.length;
      lastAt[row] = m.at;
      return { ...m, row };
    });
  }, [findings, segments]);
  const rows = Math.max(1, ...marks.map((m) => m.row + 1));

  const seg = segments.find((s) => s.id === active);
  const describe = (s: Segment) =>
    [
      `${s.id}, ${formatChainage(s.s0)} ${t("to", "ถึง")} ${formatChainage(s.s1)}`,
      s.condition === null ? t("no condition data", "ไม่มีข้อมูลสภาพ") : `${t("condition", "สภาพ")} ${formatNumber(s.condition)} ${bandFor(s.condition).label}`,
      `${s.defect_count} ${t(s.defect_count === 1 ? "defect" : "defects", "ข้อบกพร่อง")}`,
      `${t("road width", "ความกว้างถนน")} ${formatNumber(s.metrics.road_width_m, 1)} m`,
      `${t("coverage", "ความครอบคลุม")} ${formatNumber(s.metrics.coverage * 100)}%`,
      `${t("roughness", "ความขรุขระ")} ${formatNumber(s.metrics.surface_std_mm, 1)} mm`,
    ].join(", ");

  const lane = (key: string, label: string, height: number, children: React.ReactNode) => (
    <div key={key} className="flex border-b last:border-b-0" role="group" aria-label={label}>
      <div className="sticky left-0 z-20 flex shrink-0 items-center border-r bg-card px-2 text-xs font-medium text-grey-700" style={{ width: LABEL_W }}>
        {label}
      </div>
      <div className="relative flex-1" style={{ height }}>
        {children}
      </div>
    </div>
  );

  const bars = (key: string, label: string, pick: Measure, unit: string, digits: number, max: number) =>
    lane(
      key,
      label,
      64,
      segments.map((s) => {
        const v = pick(s);
        return (
          <div key={s.id} className="pointer-events-none absolute inset-y-0 flex flex-col justify-end px-0.5 pt-4 pb-1" style={{ left: pct(s.s0), width: pct(s.s1 - s.s0) }}>
            <span className="num absolute top-0.5 left-0 w-full text-center text-[11px] text-grey-700">
              {v === null ? "–" : `${formatNumber(v, digits)}${unit}`}
            </span>
            <span className="block w-full rounded-t-sm bg-accent-blue/60" style={{ height: v === null || max <= 0 ? 0 : `${Math.min(100, (v / max) * 100) * 0.7}%` }} />
          </div>
        );
      }),
    );

  const maxOf = (pick: Measure) => Math.max(0, ...segments.map((s) => pick(s) ?? 0));
  const width: Measure = (s) => s.metrics.road_width_m;
  const coverage: Measure = (s) => s.metrics.coverage * 100;
  const rough: Measure = (s) => s.metrics.surface_std_mm;

  if (!segments.length) return <p className="text-sm text-muted-foreground">{t("No segments to draw.", "ไม่มีช่วงถนนให้แสดง")}</p>;

  return (
    <figure className="flex flex-col gap-2">
      <div className="relative overflow-x-auto rounded-lg border bg-card">
        <div className="relative" style={{ minWidth: LABEL_W + trackW }}>
          {/* axis */}
          <div className="flex border-b bg-grey-50">
            <div className="sticky left-0 z-20 shrink-0 border-r bg-grey-50 px-2 py-1 text-xs text-muted-foreground" style={{ width: LABEL_W }}>
              {t("Chainage", "ระยะทาง")}
            </div>
            <div className="relative h-6 flex-1">
              {ticks.map((m) => (
                <span key={m} className="num absolute top-1 -translate-x-1/2 text-[11px] text-muted-foreground first:translate-x-0" style={{ left: pct(m) }}>
                  {formatChainage(m)}
                </span>
              ))}
            </div>
          </div>

          {/* tick gridlines under every lane */}
          <div className="pointer-events-none absolute top-6 right-0 bottom-0 z-0" style={{ left: LABEL_W }} aria-hidden>
            {ticks.map((m) => (
              <span key={m} className="absolute inset-y-0 w-px bg-grey-100" style={{ left: pct(m) }} />
            ))}
          </div>

          {lane(
            "condition",
            t("Condition", "สภาพถนน"),
            44,
            segments.map((s) => {
              const b = bandFor(s.condition);
              return (
                <div
                  key={s.id}
                  className="pointer-events-none absolute inset-y-1 grid place-items-center border-x border-white"
                  style={{ left: pct(s.s0), width: pct(s.s1 - s.s0), background: b.color }}
                >
                  <span className="num rounded bg-white/90 px-1 text-xs font-medium text-grey-900">{s.condition === null ? "–" : formatNumber(s.condition)}</span>
                </div>
              );
            }),
          )}

          {lane(
            "defects",
            t("Defects", "ข้อบกพร่อง"),
            Math.max(40, rows * MARK + 12),
            marks.map(({ f, at, row }) => {
              const resolved = f.status === "fixed" || f.status === "verified" || f.status === "dismissed";
              const name = `${f.id}, ${labelFor(f.type)}, ${t(`${f.severity} severity`, `ความรุนแรง${{ high: "สูง", medium: "กลาง", low: "ต่ำ" }[f.severity!]}`)}${resolved ? `, ${t("resolved", "แก้ไขแล้ว")} (${f.status})` : ""}`;
              return (
                <Link
                  key={f.id}
                  href={withSel("/map", { finding: f.id })}
                  aria-label={name}
                  title={name}
                  className="absolute z-30 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-brand"
                  style={{ left: pct(at), top: 8 + row * MARK + MARK / 2 }}
                >
                  {resolved ? (
                    <span className="grid size-4 place-items-center rounded-full border border-grey-300 bg-grey-100 opacity-70">
                      <Check className="size-3 text-grey-500" aria-hidden />
                    </span>
                  ) : (
                    <SeverityIcon severity={f.severity!} size={12} className={SEVERITY[f.severity!].fill} />
                  )}
                </Link>
              );
            }),
          )}

          {bars("width", t("Road width", "ความกว้างถนน"), width, " m", 1, maxOf(width))}
          {bars("coverage", t("Coverage", "ความครอบคลุม"), coverage, "%", 0, 100)}
          {bars("rough", t("Surface roughness", "ความขรุขระผิวทาง"), rough, " mm", 1, maxOf(rough))}

          {/* segment columns: one link per segment, spanning every lane */}
          <div className="absolute right-0 bottom-0 z-10" style={{ left: LABEL_W, top: 24 }}>
            {segments.map((s) => (
              <Link
                key={s.id}
                href={withSel("/map", { segment: s.id })}
                aria-label={describe(s)}
                onMouseEnter={() => setActive(s.id)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(s.id)}
                onBlur={() => setActive(null)}
                className={cn(
                  "absolute inset-y-0 outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-inset",
                  active === s.id && "bg-brand/10 ring-1 ring-brand ring-inset",
                )}
                style={{ left: pct(s.s0), width: pct(s.s1 - s.s0) }}
              />
            ))}
          </div>
        </div>
      </div>

      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label={t("Defect marks", "สัญลักษณ์ข้อบกพร่อง")}>
        {(["high", "medium", "low"] as const).map((sv) => (
          <li key={sv} className="inline-flex items-center gap-1.5">
            <SeverityIcon severity={sv} size={11} />
            {t(sv[0].toUpperCase() + sv.slice(1), { high: "สูง", medium: "กลาง", low: "ต่ำ" }[sv])}
          </li>
        ))}
        <li className="inline-flex items-center gap-1.5">
          <span className="grid size-3.5 place-items-center rounded-full border border-grey-300 bg-grey-100">
            <Check className="size-2.5 text-grey-500" aria-hidden />
          </span>
          {t("Resolved", "แก้ไขแล้ว")}
        </li>
      </ul>
      <figcaption className="min-h-5 text-sm text-muted-foreground" aria-live="polite">
        {seg ? (
          <span className="num">{describe(seg)}</span>
        ) : (
          t("Hover or focus a segment to read its measures. Select it to open it on the map.", "เลื่อนเมาส์หรือโฟกัสที่ช่วงถนนเพื่ออ่านค่า เลือกเพื่อเปิดบนแผนที่")
        )}
      </figcaption>
    </figure>
  );
}

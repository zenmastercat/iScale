"use client";
import { Check, Circle, Download, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { reviewOf } from "@/components/report/review";
import { useAnalysis, useCatalogLabel } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { FindingMetrics, Verification, VerificationResult, VerifyStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | VerifyStatus;

const WORDS: Record<VerifyStatus, [string, string]> = {
  verified: ["Verified", "ยืนยันแล้ว"],
  not_fixed: ["Still present", "ยังพบอยู่"],
  not_covered: ["Not covered", "สำรวจไม่ถึง"],
};

type Kind = "cm" | "m2";
interface Measure {
  kind: Kind;
  value: number;
}

/** The measure a defect has: depth/step/height in cm, else area in m². null when it has neither. */
function measure(m: FindingMetrics | null | undefined): Measure | null {
  if (!m) return null;
  const cm = m.depth_max_m ?? m.step_m ?? m.height_max_m;
  if (cm !== undefined) return { kind: "cm", value: cm * 100 };
  if (m.area_m2 !== undefined) return { kind: "m2", value: m.area_m2 };
  return null;
}

const fmt = (x: Measure) => (x.kind === "cm" ? `${x.value.toFixed(1)} cm` : `${x.value.toFixed(2)} m²`);

const signed = (cm: number) => {
  const r = Math.round(cm * 10) / 10;
  return r === 0 ? "0.0 cm" : `${r < 0 ? "−" : "+"}${Math.abs(r).toFixed(1)} cm`;
};

function Pill({ status }: { status: VerifyStatus }) {
  const t = useT();
  const cfg = {
    verified: { icon: Check, cls: "bg-sev-low-bg text-sev-low-fg", dashed: false },
    not_fixed: { icon: X, cls: "bg-sev-high-bg text-sev-high-fg", dashed: false },
    not_covered: { icon: Circle, cls: "bg-grey-100 text-grey-700", dashed: true },
  }[status];
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold whitespace-nowrap", cfg.cls)}>
      <Icon aria-hidden className={cn("size-4", cfg.dashed && "[stroke-dasharray:3_3]")} strokeWidth={2.25} />
      {t(...WORDS[status])}
    </span>
  );
}

function Tile({ status, n, label }: { status: VerifyStatus; n: number; label: string }) {
  const cfg = {
    verified: { icon: Check, cls: "bg-sev-low-bg text-sev-low-fg", dashed: false },
    not_fixed: { icon: X, cls: "bg-sev-high-bg text-sev-high-fg", dashed: false },
    not_covered: { icon: Circle, cls: "bg-grey-100 text-grey-700", dashed: true },
  }[status];
  const Icon = cfg.icon;
  return (
    <div className="flex items-center gap-4 rounded-lg border bg-card p-5">
      <span className={cn("flex size-14 shrink-0 items-center justify-center rounded-full", cfg.cls)}>
        <Icon aria-hidden className={cn("size-6", cfg.dashed && "[stroke-dasharray:3_3]")} strokeWidth={2.25} />
      </span>
      <div>
        <p className="num text-4xl leading-none font-semibold text-brand">{n}</p>
        <p className="mt-1 text-base text-grey-700">{label}</p>
      </div>
    </div>
  );
}

/** value null + tone "grey" = full grey bar ("no data"); tone "none" = no bar at all. */
function Bar({ value, max, tone }: { value: number | null; max: number; tone: "red" | "grey" | "none" }) {
  const pct = tone === "none" ? 0 : value === null ? 100 : Math.min(100, Math.max(0, (Math.max(value, 0) / max) * 100));
  return (
    <div className="h-3 w-full overflow-hidden rounded-sm bg-grey-100" aria-hidden>
      <div className={cn("h-full", tone === "red" ? "bg-sev-high" : "bg-grey-300")} style={{ width: `${pct}%` }} />
    </div>
  );
}

function BeforeAfter({ r, max }: { r: VerificationResult; max: Record<Kind, number> }) {
  const t = useT();
  const before = measure(r.before_metrics);
  const after = measure(r.after_metrics);
  const covered = r.status !== "not_covered";
  const kind: Kind = before?.kind ?? after?.kind ?? "cm";
  // fixed: nothing left to measure, so show how the surface sits relative to its surroundings (cm)
  const afterText = !covered
    ? t("no data", "ไม่มีข้อมูล")
    : r.status === "not_fixed" && after
      ? fmt(after)
      : signed(r.surface_delta_m * 100);
  const rows = [
    {
      label: t("Before", "ก่อน"),
      text: before ? fmt(before) : t("no value", "ไม่มีค่า"),
      bar: <Bar value={before?.value ?? null} max={max[kind]} tone={before ? "red" : "none"} />,
    },
    {
      label: t("After", "หลัง"),
      text: afterText,
      bar: !covered ? (
        <Bar value={null} max={max[kind]} tone="grey" />
      ) : r.status === "not_fixed" && after ? (
        <Bar value={after.value} max={max[after.kind]} tone="red" />
      ) : (
        <Bar value={0} max={max[kind]} tone="none" />
      ),
    },
  ];
  return (
    <div className="grid grid-cols-[3.5rem_1fr_5.5rem] items-center gap-x-3 gap-y-2 text-sm">
      {rows.map((x) => (
        <div key={x.label} className="contents">
          <span className="text-muted-foreground">{x.label}</span>
          {x.bar}
          <span className="num text-right">{x.text}</span>
        </div>
      ))}
    </div>
  );
}

const PLAIN_NUMBER = /^-?\d+(\.\d+)?$/;
/** CSV cell; text that a spreadsheet could read as a formula gets a leading ' (plain numbers, even negative ones, are left alone). */
const csvCell = (v: string | number) => {
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s) && !PLAIN_NUMBER.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
};

/** Client-side CSV of the rows on screen (there is no server export for verification). */
function downloadCsv(v: Verification, rows: VerificationResult[], name: (type: string) => string) {
  const head = ["finding_id", "name", "type", "severity", "result", "before", "after", "surface_delta_cm", "evidence", "lat", "lon"];
  const lines = rows.map((r) => {
    const b = measure(r.before_metrics);
    const a = measure(r.after_metrics);
    return [
      r.finding_id, name(r.type), r.type, r.severity, r.status,
      b ? fmt(b) : "", a ? fmt(a) : "", (r.surface_delta_m * 100).toFixed(1), r.evidence, r.lat, r.lon,
    ].map(csvCell).join(",");
  });
  const blob = new Blob(["\ufeff" + [head.join(","), ...lines].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `verification-${v.before}-${v.after}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function VerificationResults({ v }: { v: Verification }) {
  const t = useT();
  const { withSel } = useSelection();
  const label = useCatalogLabel();
  const analysis = useAnalysis();
  const confirmed = new Set(
    (analysis.data?.findings ?? []).filter((f) => reviewOf(f)?.verdict === "correct").map((f) => f.id),
  );
  const [filter, setFilter] = useState<Filter>("all");
  const rows = filter === "all" ? v.results : v.results.filter((r) => r.status === filter);
  // one scale per unit, so cm rows are compared with cm rows and m² rows with m² rows
  const max: Record<Kind, number> = { cm: 1, m2: 1 };
  for (const r of v.results)
    for (const x of [measure(r.before_metrics), measure(r.after_metrics)])
      if (x) max[x.kind] = Math.max(max[x.kind], x.value);
  const filters: { key: Filter; label: string; n?: number }[] = [
    { key: "all", label: t("All", "ทั้งหมด"), n: v.results.length },
    { key: "verified", label: t(...WORDS.verified) },
    { key: "not_fixed", label: t(...WORDS.not_fixed) },
    { key: "not_covered", label: t(...WORDS.not_covered) },
  ];
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Tile status="verified" n={v.counts.verified} label={t("Verified fixed", "ซ่อมแล้วและยืนยัน")} />
        <Tile status="not_fixed" n={v.counts.not_fixed} label={t("Still present", "ยังพบอยู่")} />
        <Tile status="not_covered" n={v.counts.not_covered} label={t("Not covered by the after drive", "รอบหลังสำรวจไม่ถึง")} />
      </div>

      <section aria-label={t("Each repair, before and after", "งานซ่อมแต่ละรายการ ก่อนและหลัง")} className="rounded-lg border bg-card p-4 md:p-4">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-grey-900 md:text-base">{t("Each repair, before and after", "งานซ่อมแต่ละรายการ ก่อนและหลัง")}</h2>
          <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => downloadCsv(v, rows, label)}
            disabled={!rows.length}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border bg-card px-4 text-sm font-medium hover:bg-grey-50 disabled:opacity-50"
          >
            <Download aria-hidden className="size-4" />
            {t("Export CSV", "ส่งออก CSV")}
          </button>
          <div role="group" aria-label={t("Filter results", "กรองผลลัพธ์")} className="flex flex-wrap gap-2">
            {filters.map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "min-h-11 rounded-lg border px-4 text-sm font-medium",
                  filter === f.key ? "border-brand bg-brand text-white" : "bg-card hover:bg-grey-50",
                )}
              >
                {f.label}
                {f.n !== undefined && <span className="num"> ({f.n})</span>}
              </button>
            ))}
          </div>
          </div>
        </div>
        {rows.length === 0 ? (
          <p className="text-muted-foreground">{t("No results in this filter.", "ไม่มีผลลัพธ์ในตัวกรองนี้")}</p>
        ) : (
          <ul className="flex flex-col gap-3 md:gap-2">
            {rows.map((r) => (
              <li
                key={r.finding_id}
                className="grid grid-cols-1 gap-4 rounded-lg border p-4 md:grid-cols-[minmax(0,10rem)_minmax(0,16rem)_minmax(0,1fr)_auto] md:items-center md:gap-4 md:p-3"
              >
                <div className="flex items-start justify-between gap-3 md:block">
                  <div>
                    <Link
                      href={withSel("/map", { finding: r.finding_id })}
                      className="font-semibold text-grey-900 underline-offset-4 hover:underline"
                    >
                      {label(r.type)}
                    </Link>
                    <p className="num text-sm text-muted-foreground">{r.finding_id}</p>
                    {confirmed.has(r.finding_id) && (
                      <p className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-sev-low-fg">
                        <Check aria-hidden className="size-3.5" />
                        {t("Confirmed by engineer", "วิศวกรยืนยันแล้ว")}
                      </p>
                    )}
                  </div>
                  <span className="md:hidden"><Pill status={r.status} /></span>
                </div>
                <BeforeAfter r={r} max={max} />
                <p className="text-sm text-grey-800 md:text-[13px]">{r.evidence}</p>
                <span className="hidden justify-self-end md:block"><Pill status={r.status} /></span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

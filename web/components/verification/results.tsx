"use client";
import { Check, Circle, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useCatalogLabel } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { FindingMetrics, Verification, VerificationResult, VerifyStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | VerifyStatus;

const WORDS: Record<VerifyStatus, string> = {
  verified: "Verified",
  not_fixed: "Still present",
  not_covered: "Not covered",
};

/** Size of a defect in cm (depth, step or height), or null when it has none of those. */
function sizeCm(m: FindingMetrics | null | undefined): number | null {
  if (!m) return null;
  const v = m.depth_max_m ?? m.step_m ?? m.height_max_m;
  return v === undefined ? null : v * 100;
}

const signed = (cm: number) => `${cm < 0 ? "−" : "+"}${Math.abs(cm).toFixed(1)} cm`;

function Pill({ status }: { status: VerifyStatus }) {
  const cfg = {
    verified: { icon: Check, cls: "bg-sev-low-bg text-sev-low-fg", dashed: false },
    not_fixed: { icon: X, cls: "bg-sev-high-bg text-sev-high-fg", dashed: false },
    not_covered: { icon: Circle, cls: "bg-grey-100 text-grey-700", dashed: true },
  }[status];
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold whitespace-nowrap", cfg.cls)}>
      <Icon aria-hidden className={cn("size-4", cfg.dashed && "[stroke-dasharray:3_3]")} strokeWidth={2.25} />
      {WORDS[status]}
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

function Bar({ cm, max, tone }: { cm: number | null; max: number; tone: "red" | "grey" | "none" }) {
  const pct = cm === null ? 100 : Math.min(100, Math.max(0, (Math.max(cm, 0) / max) * 100));
  return (
    <div className="h-3 w-full overflow-hidden rounded-sm bg-grey-100" aria-hidden>
      <div
        className={cn("h-full", tone === "red" ? "bg-sev-high" : "bg-grey-300")}
        style={{ width: tone === "none" ? 0 : `${pct}%` }}
      />
    </div>
  );
}

function BeforeAfter({ r, max }: { r: VerificationResult; max: number }) {
  const before = sizeCm(r.before_metrics);
  const afterSize = sizeCm(r.after_metrics);
  const covered = r.status !== "not_covered";
  // fixed: nothing left, show how the surface sits relative to its surroundings
  const afterText = !covered ? "no data" : r.status === "not_fixed" && afterSize !== null ? `${afterSize.toFixed(1)} cm` : signed(r.surface_delta_m * 100);
  const rows = [
    { label: "Before", text: before === null ? "–" : `${before.toFixed(1)} cm`, bar: <Bar cm={before} max={max} tone="red" /> },
    {
      label: "After",
      text: afterText,
      bar: !covered ? (
        <Bar cm={null} max={max} tone="grey" />
      ) : r.status === "not_fixed" ? (
        <Bar cm={afterSize} max={max} tone="red" />
      ) : (
        <Bar cm={0} max={max} tone="none" />
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

export function VerificationResults({ v }: { v: Verification }) {
  const { withSel } = useSelection();
  const label = useCatalogLabel();
  const [filter, setFilter] = useState<Filter>("all");
  const rows = filter === "all" ? v.results : v.results.filter((r) => r.status === filter);
  const max = Math.max(
    1,
    ...v.results.flatMap((r) => [sizeCm(r.before_metrics) ?? 0, sizeCm(r.after_metrics) ?? 0]),
  );
  const filters: { key: Filter; label: string; n?: number }[] = [
    { key: "all", label: "All", n: v.results.length },
    { key: "verified", label: "Verified" },
    { key: "not_fixed", label: "Still present" },
    { key: "not_covered", label: "Not covered" },
  ];
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Tile status="verified" n={v.counts.verified} label="Verified fixed" />
        <Tile status="not_fixed" n={v.counts.not_fixed} label="Still present" />
        <Tile status="not_covered" n={v.counts.not_covered} label="Not covered by the after drive" />
      </div>

      <section aria-label="Each repair, before and after" className="rounded-lg border bg-card p-4 md:p-7">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-grey-900">Each repair, before and after</h2>
          <div role="group" aria-label="Filter results" className="flex flex-wrap gap-2">
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
        {rows.length === 0 ? (
          <p className="text-muted-foreground">No results in this filter.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {rows.map((r) => (
              <li
                key={r.finding_id}
                className="grid grid-cols-1 gap-4 rounded-lg border p-4 md:grid-cols-[minmax(0,12rem)_minmax(0,18rem)_minmax(0,1fr)_auto] md:items-center"
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
                  </div>
                  <span className="md:hidden"><Pill status={r.status} /></span>
                </div>
                <BeforeAfter r={r} max={max} />
                <p className="text-sm text-grey-800">{r.evidence}</p>
                <span className="hidden justify-self-end md:block"><Pill status={r.status} /></span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

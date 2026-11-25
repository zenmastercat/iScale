import { evidenceSource } from "@/components/overview/fix-first-table";
import { findingChainage } from "@/lib/chainage";
import type { FindingsFilter, SortKey } from "@/lib/findings-filter";
import { matchesFilter } from "@/lib/findings-filter";
import type { Finding, Segment } from "@/lib/types";

export interface Row {
  f: Finding;
  label: string;
  rank: number | null;
  chainage: number | null;
  depthCm: number | null;
  area: number | null;
  volumeL: number | null;
  cost: number | null;
  source: string;
  workorder: string | null;
  /** repair cost from /api/priority (plan currency), when the finding is ranked */
  planCost: number | null;
}

export function buildRows(findings: Finding[], segments: Segment[], labelFor: (c: string) => string, rankById: Map<string, { rank: number; cost?: number }>): Row[] {
  return findings.map((f) => ({
    f,
    label: labelFor(f.type),
    rank: rankById.get(f.id)?.rank ?? null,
    planCost: rankById.get(f.id)?.cost ?? null,
    chainage: findingChainage(f, segments),
    depthCm: f.metrics.depth_max_m !== undefined ? f.metrics.depth_max_m * 100 : null,
    area: f.metrics.area_m2 ?? null,
    volumeL: f.metrics.volume_m3 !== undefined ? f.metrics.volume_m3 * 1000 : null,
    cost: f.cost?.materials_cost ?? null,
    source: evidenceSource(f),
    workorder: f.workorder_id ?? null,
  }));
}

const SEV_ORDER = { high: 0, medium: 1, low: 2 } as const;

function sortValue(r: Row, key: SortKey): number | string | null {
  switch (key) {
    case "rank": return r.rank;
    case "id": return r.f.id;
    case "type": return r.label;
    case "severity": return r.f.severity ? SEV_ORDER[r.f.severity] : null;
    case "status": return r.f.status;
    case "segment": return r.f.segment_id;
    case "chainage": return r.chainage;
    case "depth": return r.depthCm;
    case "area": return r.area;
    case "volume": return r.volumeL;
    case "cost": return r.cost;
    case "source": return r.source;
    case "workorder": return r.workorder;
  }
}

export function filterAndSort(rows: Row[], filter: FindingsFilter): Row[] {
  const q = filter.q?.toLowerCase();
  const out = rows.filter(
    (r) => matchesFilter(r.f, filter) && (!q || `${r.f.id} ${r.label} ${r.f.evidence}`.toLowerCase().includes(q)),
  );
  const s = filter.sort ?? { key: "chainage" as SortKey, desc: false };
  const dir = s.desc ? -1 : 1;
  return out.sort((a, b) => {
    const x = sortValue(a, s.key);
    const y = sortValue(b, s.key);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // empty values always last
    if (y === null) return -1;
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * dir;
  });
}

export function toCsv(rows: Row[]): string {
  const head = ["id", "type", "severity", "status", "segment", "chainage_m", "depth_cm", "area_m2", "volume_l", "materials_cost", "currency", "source", "work_order", "rank"];
  const esc = (v: unknown) => {
    let s = v === null || v === undefined ? "" : String(v);
    // spreadsheet formula guard; real numbers (e.g. -1.5) stay numbers
    if (/^[=+\-@]/.test(s) && Number.isNaN(Number(s))) s = `'${s}`;
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const num = (n: number | null, d: number) => (n === null ? "" : n.toFixed(d));
  const lines = rows.map((r) =>
    [
      r.f.id, r.label, r.f.severity ?? "", r.f.status, r.f.segment_id ?? "", num(r.chainage, 1), num(r.depthCm, 1), num(r.area, 2),
      num(r.volumeL, 1), num(r.cost, 0), r.f.cost?.currency ?? "", r.source, r.workorder ?? "", r.rank ?? "",
    ].map(esc).join(","),
  );
  return [head.join(","), ...lines].join("\n");
}

/** Rows grouped by segment, groups in road order; rows keep their (sorted) order inside each group. */
export function groupRows(rows: Row[], segments: Segment[]) {
  const by = new Map<string, Row[]>();
  for (const r of rows) {
    const k = r.f.segment_id ?? "";
    by.set(k, [...(by.get(k) ?? []), r]);
  }
  const order = (id: string) => segments.find((s) => s.id === id)?.s0 ?? Number.MAX_SAFE_INTEGER;
  return [...by.entries()].sort((a, b) => order(a[0]) - order(b[0])).map(([id, list]) => ({ id, seg: segments.find((s) => s.id === id), list }));
}

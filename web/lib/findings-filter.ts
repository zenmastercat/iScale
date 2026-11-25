/*
 * URL filters for /findings. The Overview links in with these; the Findings page reads them.
 *   /findings?kind=defect&severity=high,medium&status=open,planned&type=pothole&segment=S003&q=FD91&sort=-depth
 * Lists are comma-separated. Missing = no filter. "sort" is a column key, "-" prefix = descending.
 */
import type { Finding, FindingStatus, Severity } from "@/lib/types";

export const SORT_KEYS = [
  "rank", "id", "type", "severity", "status", "segment", "chainage", "depth", "area", "volume", "cost", "source", "workorder",
] as const;
export type SortKey = (typeof SORT_KEYS)[number];

export interface FindingsFilter {
  kind?: "defect" | "asset";
  severity?: Severity[];
  status?: FindingStatus[];
  type?: string[];
  segment?: string[];
  q?: string;
  sort?: { key: SortKey; desc: boolean };
}

const SEVERITIES: Severity[] = ["high", "medium", "low"];
const STATUSES: FindingStatus[] = ["open", "planned", "fixed", "verified", "not_fixed", "dismissed"];
const list = (v: string | null) => (v ? v.split(",").map((s) => s.trim()).filter(Boolean) : undefined);

/** Parse from URLSearchParams (unknown values are dropped, so a crafted URL can't break the page). */
export function parseFindingsFilter(sp: URLSearchParams): FindingsFilter {
  const f: FindingsFilter = {};
  const kind = sp.get("kind");
  if (kind === "defect" || kind === "asset") f.kind = kind;
  const sev = list(sp.get("severity"))?.filter((s): s is Severity => SEVERITIES.includes(s as Severity));
  if (sev?.length) f.severity = sev;
  const st = list(sp.get("status"))?.filter((s): s is FindingStatus => STATUSES.includes(s as FindingStatus));
  if (st?.length) f.status = st;
  const type = list(sp.get("type"))?.filter((s) => /^[a-z0-9_]{1,64}$/.test(s));
  if (type?.length) f.type = type;
  const seg = list(sp.get("segment"))?.filter((s) => /^[A-Za-z0-9_-]{1,32}$/.test(s));
  if (seg?.length) f.segment = seg;
  const q = sp.get("q")?.slice(0, 100).trim();
  if (q) f.q = q;
  const sort = sp.get("sort");
  if (sort) {
    const desc = sort.startsWith("-");
    const key = (desc ? sort.slice(1) : sort) as SortKey;
    if (SORT_KEYS.includes(key)) f.sort = { key, desc };
  }
  return f;
}

/** Query-param record for withSel("/findings", findingsQuery({...})). */
export function findingsQuery(f: FindingsFilter): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.kind) out.kind = f.kind;
  if (f.severity?.length) out.severity = f.severity.join(",");
  if (f.status?.length) out.status = f.status.join(",");
  if (f.type?.length) out.type = f.type.join(",");
  if (f.segment?.length) out.segment = f.segment.join(",");
  if (f.q) out.q = f.q;
  if (f.sort) out.sort = (f.sort.desc ? "-" : "") + f.sort.key;
  return out;
}

/** Does a finding pass the filter (everything but sorting and q, which need labels/chainage)? */
export function matchesFilter(x: Finding, f: FindingsFilter): boolean {
  if (f.kind === "defect" && x.severity === null) return false;
  if (f.kind === "asset" && x.severity !== null) return false;
  if (f.severity && (!x.severity || !f.severity.includes(x.severity))) return false;
  if (f.status && !f.status.includes(x.status)) return false;
  if (f.type && !f.type.includes(x.type)) return false;
  if (f.segment && (!x.segment_id || !f.segment.includes(x.segment_id))) return false;
  return true;
}

"use client";
import Link from "next/link";
import { SEVERITY, SeverityIcon } from "@/components/shared/severity-badge";
import { isOpenDefect } from "@/lib/chainage";
import { findingsQuery, OPEN_STATUSES } from "@/lib/findings-filter";
import { useT } from "@/lib/i18n";
import type { Finding, Severity } from "@/lib/types";

const SEVS: Severity[] = ["high", "medium", "low"];

/** Open defects counted by type (rows) × severity (columns). Every non-zero count links to /findings. */
export function DefectMatrix({
  findings,
  labelFor,
  withSel,
}: {
  findings: Finding[];
  labelFor: (code: string) => string;
  withSel: (path: string, extra?: Record<string, string>) => string;
}) {
  const t = useT();
  const open = findings.filter(isOpenDefect);
  const rows = new Map<string, Record<Severity, number>>();
  for (const f of open) {
    const r = rows.get(f.type) ?? { high: 0, medium: 0, low: 0 };
    r[f.severity!]++;
    rows.set(f.type, r);
  }
  const sorted = [...rows.entries()].sort(
    (a, b) => b[1].high - a[1].high || b[1].medium - a[1].medium || sum(b[1]) - sum(a[1]),
  );
  const col = { high: 0, medium: 0, low: 0 } as Record<Severity, number>;
  for (const [, r] of sorted) for (const s of SEVS) col[s] += r[s];

  if (!open.length) return <p className="text-sm text-muted-foreground">{t("No open defects.", "ไม่มีข้อบกพร่องที่ยังไม่ซ่อม")}</p>;

  const href = (type?: string, sev?: Severity) =>
    withSel("/findings", findingsQuery({ kind: "defect", status: OPEN_STATUSES, type: type ? [type] : undefined, severity: sev ? [sev] : undefined }));

  const cell = (n: number, h: string, strong = false, label = "") =>
    n ? (
      <Link href={h} aria-label={label} className={`num inline-flex min-h-11 min-w-11 items-center justify-end px-2 text-link underline-offset-4 hover:underline md:min-h-7 ${strong ? "font-semibold" : ""}`}>
        {n}
      </Link>
    ) : (
      <span className="num inline-flex min-w-11 justify-end px-2 text-grey-400">
        <span aria-hidden>·</span>
        <span className="sr-only">{t("none", "ไม่มี")}</span>
      </span>
    );

  return (
    <div className="relative overflow-x-auto">
    <table className="w-full text-sm md:text-[13px]">
      <caption className="sr-only">Open defects by type and severity</caption>
      <thead>
        <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
          <th scope="col" className="py-2 pr-2 text-left font-semibold">{t("Type", "ชนิด")}</th>
          {SEVS.map((s) => (
            <th key={s} scope="col" className="py-2 text-right font-semibold">
              <span className="inline-flex items-center gap-1 px-2">
                <SeverityIcon severity={s} size={10} />
                {t(SEVERITY[s].label, SEVERITY[s].th)}
              </span>
            </th>
          ))}
          <th scope="col" className="py-2 text-right font-semibold"><span className="px-2">{t("Total", "รวม")}</span></th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(([type, r]) => (
          <tr key={type} className="border-b last:border-0">
            <th scope="row" className="py-0.5 pr-2 text-left font-normal text-grey-900">{labelFor(type)}</th>
            {SEVS.map((s) => (
              <td key={s} className="text-right">{cell(r[s], href(type, s), false, `${r[s]} ${SEVERITY[s].label.toLowerCase()} ${labelFor(type)}`)}</td>
            ))}
            <td className="text-right">{cell(sum(r), href(type), true, `${sum(r)} open ${labelFor(type)}`)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t-2">
          <th scope="row" className="py-0.5 pr-2 text-left font-semibold">{t("All types", "ทุกชนิด")}</th>
          {SEVS.map((s) => (
            <td key={s} className="text-right">{cell(col[s], href(undefined, s), true, `${col[s]} ${SEVERITY[s].label.toLowerCase()} open defects`)}</td>
          ))}
          <td className="text-right">{cell(open.length, href(), true, `${open.length} open defects`)}</td>
        </tr>
      </tfoot>
    </table>
    </div>
  );
}

const sum = (r: Record<Severity, number>) => r.high + r.medium + r.low;

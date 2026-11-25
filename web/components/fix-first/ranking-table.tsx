"use client";
import { MapPin, Users } from "lucide-react";
import Link from "next/link";
import { Money, Num } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { humanize } from "@/lib/format";
import { useSelection } from "@/lib/selection";
import type { Finding, PriorityItem } from "@/lib/types";

const TH = "py-3 pr-4 font-semibold";

export function RankingTable({
  items,
  findingsById,
  currency,
}: {
  items: PriorityItem[];
  findingsById: Map<string, Finding>;
  currency: string;
}) {
  const { withSel } = useSelection();
  const detail = (it: PriorityItem, f?: Finding) =>
    it.kind === "pin" ? (
      <span className="inline-flex flex-wrap items-center gap-x-3">
        <span className="inline-flex items-center gap-1"><MapPin aria-hidden className="size-3.5" />Shared pin{it.reporter ? ` by ${it.reporter}` : ""}</span>
        <span className="inline-flex items-center gap-1">
          <Users aria-hidden className="size-3.5" />
          <Num value={it.confirmations ?? 0} /> {it.confirmations === 1 ? "confirmation" : "confirmations"}
        </span>
      </span>
    ) : (
      (f?.evidence ?? it.action)
    );
  const costBlock = (it: PriorityItem) => (
    <>
      {typeof it.cost === "number" && <p className="font-medium"><Money amount={it.cost} currency={currency} /></p>}
      {it.materials && (
        <p className="text-sm text-muted-foreground">
          materials <Money amount={it.materials.materials_cost} style="symbol" symbol={it.materials.symbol} />
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
          <p className="mt-1 text-sm text-muted-foreground">{detail(it, findingsById.get(it.id))}</p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Segment</dt>
              <dd className="num">{it.segment_id ?? "Shared pin"}</dd>
            </div>
            <div className="text-right">
              <dt className="text-muted-foreground">Cost</dt>
              <dd>{costBlock(it)}</dd>
            </div>
          </dl>
          <Link
            href={withSel("/map", { finding: it.id })}
            className="mt-3 flex min-h-11 w-full items-center justify-center rounded-lg border font-medium text-link hover:bg-grey-50"
            aria-label={`Open ${it.label} ${it.id} on the map`}
          >
            Open on map
          </Link>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[860px] text-left">
        <thead>
          <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
            <th scope="col" className={TH}>Rank</th>
            <th scope="col" className={TH}>Finding</th>
            <th scope="col" className={TH}>Severity</th>
            <th scope="col" className={TH}>Road · traffic</th>
            <th scope="col" className={`${TH} text-right`}>Priority</th>
            <th scope="col" className={`${TH} text-right`}>Cost</th>
            <th scope="col" className="py-3"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const f = findingsById.get(it.id);
            return (
              <tr key={`${it.kind}-${it.id}`} className="border-b last:border-0">
                <td className="num py-3 pr-4 font-semibold text-brand">#{it.rank}</td>
                <td className="py-3 pr-4">
                  <p className="font-medium text-grey-900">{it.label}</p>
                  <p className="text-sm text-muted-foreground">{detail(it, f)}</p>
                </td>
                <td className="py-3 pr-4"><SeverityBadge severity={it.severity} size="sm" /></td>
                <td className="py-3 pr-4 text-sm">
                  {it.road ? humanize(it.road) : "Unclassified"}
                  <span className="text-muted-foreground"> · traffic ×</span>
                  <Num value={it.traffic_factor} digits={2} />
                </td>
                <td className="py-3 pr-4 text-right"><Num value={it.priority} digits={2} /></td>
                <td className="py-3 pr-4 text-right">{costBlock(it)}
                </td>
                <td className="py-3 text-right">
                  <Link
                    href={withSel("/map", { finding: it.id })}
                    className="inline-flex min-h-11 items-center px-1 font-medium text-link underline underline-offset-4 hover:text-brand"
                    aria-label={`Open ${it.label} ${it.id} on the map`}
                  >
                    Open
                  </Link>
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

"use client";
import Link from "next/link";
import { Money, Num } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useSelection } from "@/lib/selection";
import type { PlanItem, SegmentPlanItem } from "@/lib/types";
import { PlanPill } from "./plan-pill";

const TH = "py-3 pr-4 font-semibold";

function Head({ cols }: { cols: { label: string; right?: boolean }[] }) {
  return (
    <thead>
      <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
        {cols.map((c) => (
          <th key={c.label} scope="col" className={`${TH} ${c.right ? "text-right" : ""}`}>
            {c.label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

export function SpotTable({ items, deferred, currency }: { items: PlanItem[]; deferred: PlanItem[]; currency: string }) {
  const { withSel } = useSelection();
  const rows = [...items.map((i) => ({ i, funded: true })), ...deferred.map((i) => ({ i, funded: false }))];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left">
        <Head
          cols={[
            { label: "Status" },
            { label: "Finding" },
            { label: "Action" },
            { label: "Severity" },
            { label: "Segment" },
            { label: "Priority", right: true },
            { label: "Cost", right: true },
          ]}
        />
        <tbody>
          {rows.map(({ i, funded }) => (
            <tr key={i.finding_id} className={`border-b last:border-0 ${funded ? "" : "text-grey-700"}`}>
              <td className="py-3 pr-4"><PlanPill funded={funded} /></td>
              <td className="py-3 pr-4">
                <Link
                  href={withSel("/map", { finding: i.finding_id })}
                  className="inline-flex min-h-11 flex-col justify-center font-medium text-link underline-offset-4 hover:underline"
                >
                  {i.label}
                  <span className="num text-xs font-normal text-muted-foreground">{i.finding_id}</span>
                </Link>
              </td>
              <td className="py-3 pr-4 text-sm">{i.action_label}</td>
              <td className="py-3 pr-4"><SeverityBadge severity={i.severity} size="sm" /></td>
              <td className="num py-3 pr-4">{i.segment_id}</td>
              <td className="py-3 pr-4 text-right"><Num value={i.priority} digits={1} /></td>
              <td className="py-3 text-right font-medium"><Money amount={i.cost} currency={currency} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SegmentTable({
  items,
  deferred,
  currency,
}: {
  items: SegmentPlanItem[];
  deferred: SegmentPlanItem[];
  currency: string;
}) {
  const { withSel } = useSelection();
  const rows = [...items.map((i) => ({ i, funded: true })), ...deferred.map((i) => ({ i, funded: false }))];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left">
        <Head
          cols={[
            { label: "Status" },
            { label: "Segment" },
            { label: "Treatment" },
            { label: "Condition", right: true },
            { label: "Area", right: true },
            { label: "Urgency", right: true },
            { label: "Cost", right: true },
          ]}
        />
        <tbody>
          {rows.map(({ i, funded }) => (
            <tr key={i.segment_id} className={`border-b last:border-0 ${funded ? "" : "text-grey-700"}`}>
              <td className="py-3 pr-4"><PlanPill funded={funded} /></td>
              <td className="py-3 pr-4">
                <Link
                  href={withSel("/map", { segment: i.segment_id })}
                  className="num inline-flex min-h-11 items-center font-medium text-link underline-offset-4 hover:underline"
                >
                  {i.segment_id}
                </Link>
                {i.road && <span className="ml-2 text-sm text-muted-foreground">{i.road}</span>}
              </td>
              <td className="py-3 pr-4 text-sm">{i.label}</td>
              <td className="py-3 pr-4 text-right">
                <Num value={i.condition} /> <span className="text-sm text-muted-foreground">{i.rating}</span>
              </td>
              <td className="py-3 pr-4 text-right"><Num value={i.area_m2} unit="m²" /></td>
              <td className="py-3 pr-4 text-right"><Num value={i.urgency} digits={1} /></td>
              <td className="py-3 text-right font-medium"><Money amount={i.cost} currency={currency} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

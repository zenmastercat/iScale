"use client";
import { formatMoney, formatNumber } from "@/lib/format";
import type { SpotPlan } from "@/lib/types";

const UNIT: Record<string, string> = { m2: "m²", m: "m", each: "" };

/** Repair estimate split by action (plan.by_action), biggest first, with a bar for the share of the total. */
export function CostByAction({ plan }: { plan: SpotPlan }) {
  const rows = [...plan.by_action].sort((a, b) => b.cost - a.cost);
  const max = Math.max(...rows.map((r) => r.cost), 1);
  const cur = plan.currency;
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing to repair.</p>;
  return (
    <table className="w-full text-sm md:text-[13px]">
      <caption className="sr-only">Repair cost by action ({cur})</caption>
      <thead>
        <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
          <th scope="col" className="py-2 pr-2 text-left font-semibold">Action</th>
          <th scope="col" className="py-2 pr-2 text-right font-semibold">Repairs</th>
          <th scope="col" className="py-2 pr-2 text-right font-semibold">Quantity</th>
          <th scope="col" className="w-1/3 py-2 pr-2 text-left font-semibold"><span className="sr-only">Share</span></th>
          <th scope="col" className="py-2 text-right font-semibold">Cost</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.action} className="border-b last:border-0">
            <th scope="row" className="py-2 pr-2 text-left font-normal text-grey-900 md:py-1.5">{r.label}</th>
            <td className="num py-2 pr-2 text-right md:py-1.5">{r.count}</td>
            <td className="num py-2 pr-2 text-right whitespace-nowrap text-grey-700 md:py-1.5">
              {r.unit === "each" ? "–" : `${formatNumber(r.quantity, r.quantity < 10 ? 1 : 0)} ${UNIT[r.unit] ?? r.unit}`}
            </td>
            <td className="py-2 pr-2 md:py-1.5" aria-hidden>
              <div className="h-2 rounded-full bg-grey-100">
                <div className="h-2 rounded-full bg-accent-blue" style={{ width: `${(r.cost / max) * 100}%` }} />
              </div>
            </td>
            <td className="num py-2 text-right whitespace-nowrap md:py-1.5">{formatMoney(r.cost, cur)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot className="text-grey-700">
        <tr className="border-t">
          <th scope="row" colSpan={4} className="py-1.5 pr-2 text-left font-normal">Mobilisation (once)</th>
          <td className="num py-1.5 text-right whitespace-nowrap">{formatMoney(plan.mobilization, cur)}</td>
        </tr>
        <tr className="border-t-2 text-grey-900">
          <th scope="row" colSpan={4} className="py-1.5 pr-2 text-left font-semibold">Total</th>
          <td className="num py-1.5 text-right font-semibold whitespace-nowrap">{formatMoney(plan.total, cur)}</td>
        </tr>
      </tfoot>
    </table>
  );
}

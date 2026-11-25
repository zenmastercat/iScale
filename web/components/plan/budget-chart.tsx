"use client";
import { useMemo } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { SpotPlan } from "@/lib/types";

/** Same greedy rule as civil/planning.py spot_plan: priority order, mobilisation once per segment, skip what doesn't fit. */
function fund(all: SpotPlan, budget: number) {
  const items = [...all.items, ...all.deferred].sort((a, b) => b.priority - a.priority || a.cost - b.cost);
  const segs = new Set(items.map((i) => i.segment_id));
  const mob = segs.size ? all.mobilization / segs.size : 0;
  const used = new Set<string>();
  let spent = 0;
  let n = 0;
  let high = 0;
  for (const it of items) {
    const extra = it.cost + (used.has(it.segment_id) ? 0 : mob);
    if (spent + extra <= budget) {
      spent += extra;
      used.add(it.segment_id);
      n++;
      if (it.severity === "high") high++;
    }
  }
  return { n, high };
}

/** What each budget buys: repairs funded and high-severity repairs covered, with the current budget marked. */
export function BudgetChart({ all, max, current }: { all: SpotPlan; max: number; current: number }) {
  const t = useT();
  const data = useMemo(() => {
    const steps = 40;
    return Array.from({ length: steps + 1 }, (_, k) => {
      const budget = Math.round((max * k) / steps);
      return { budget, ...fund(all, budget) };
    });
  }, [all, max]);
  const totalHigh = [...all.items, ...all.deferred].filter((i) => i.severity === "high").length;
  const now = fund(all, current);
  const nRepairs = all.items.length + all.deferred.length;

  return (
    <section aria-label={t("What each budget buys", "งบแต่ละระดับซ่อมได้เท่าไร")} className="rounded-lg border bg-card p-5 md:p-4">
      <h2 className="text-lg font-semibold text-grey-900 md:text-base">{t("What each budget buys", "งบแต่ละระดับซ่อมได้เท่าไร")}</h2>
      <p className="num mb-3 text-sm text-muted-foreground md:text-[13px]">
        {t("At the current budget:", "ที่งบปัจจุบัน:")} {now.n}/{nRepairs} {t("repairs", "งานซ่อม")} · {now.high}/{totalHigh} {t("high severity", "รุนแรงสูง")}
      </p>
      <div className="h-56 w-full" role="img" aria-label={t("Chart of repairs funded as the budget grows", "กราฟจำนวนงานซ่อมที่ได้รับงบเมื่องบเพิ่มขึ้น")}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--color-grey-200)" vertical={false} />
            <XAxis dataKey="budget" type="number" domain={[0, max]} tickFormatter={(v: number) => formatMoney(v, all.currency)} tick={{ fontSize: 12 }} />
            <YAxis allowDecimals={false} domain={[0, nRepairs]} width={28} tick={{ fontSize: 12 }} />
            <Tooltip
              formatter={(v, name) => [v, name]}
              labelFormatter={(l) => `${t("Budget", "งบ")} ${formatMoney(Number(l), all.currency)}`}
            />
            <Legend />
            <ReferenceLine x={Math.min(current, max)} stroke="var(--color-grey-700)" strokeDasharray="4 3" />
            <Line type="stepAfter" dataKey="n" name={t("Repairs funded", "งานซ่อมที่ได้รับงบ")} stroke="var(--color-brand)" strokeWidth={2} dot={false} />
            <Line type="stepAfter" dataKey="high" name={t("High severity covered", "รุนแรงสูงที่ได้รับงบ")} stroke="var(--color-sev-high)" strokeWidth={2} strokeDasharray="6 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

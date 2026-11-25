"use client";
import { TypeLabel } from "@/components/surveys/type-label";
import Link from "next/link";
import { ConditionChip } from "@/components/shared/condition-chip";
import { Money, Num } from "@/components/shared/num";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import type { PlanItem, SegmentPlanItem } from "@/lib/types";
import { PlanPill } from "./plan-pill";

const TH = "py-3 md:py-1.5 pr-4 font-semibold";

const TH_WORDS: Record<string, string> = {"Status": "สถานะ", "Finding": "รายการ", "Action": "วิธีซ่อม", "Severity": "ความรุนแรง", "Segment": "ช่วง", "Priority": "ลำดับความสำคัญ", "Cost": "ค่าใช้จ่าย", "Treatment": "วิธีบำรุง", "Condition": "สภาพ", "Area": "พื้นที่", "Urgency": "ความเร่งด่วน"};

function Head({ cols }: { cols: { label: string; right?: boolean }[] }) {
  const t = useT();
  return (
    <thead>
      <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
        {cols.map((c) => (
          <th key={c.label} scope="col" className={`${TH} ${c.right ? "text-right" : ""}`}>
            {t(c.label, TH_WORDS[c.label] ?? c.label)}
          </th>
        ))}
      </tr>
    </thead>
  );
}

export function SpotTable({ items, deferred, currency }: { items: PlanItem[]; deferred: PlanItem[]; currency: string }) {
  const t = useT();
  const { withSel } = useSelection();
  const rows = [...items.map((i) => ({ i, funded: true })), ...deferred.map((i) => ({ i, funded: false }))];
  return (
    <>
    <ul className="flex flex-col gap-3 md:hidden">
      {rows.map(({ i, funded }) => (
        <li key={i.finding_id} className={`rounded-lg border p-4 md:p-3 ${funded ? "" : "bg-grey-50"}`}>
          <div className="flex items-start justify-between gap-3">
            <PlanPill funded={funded} />
            <SeverityBadge severity={i.severity} size="sm" />
          </div>
          <p className="mt-2 font-medium text-grey-900"><TypeLabel type={i.type} fallback={i.label} /></p>
          <p className="text-sm md:text-[13px] text-muted-foreground">{i.action_label}</p>
          <dl className="mt-3 grid grid-cols-3 gap-3 text-sm md:text-[13px]">
            <div><dt className="text-muted-foreground">{t("Segment", "ช่วง")}</dt><dd className="num">{i.segment_id}</dd></div>
            <div><dt className="text-muted-foreground">{t("Priority", "ลำดับความสำคัญ")}</dt><dd><Num value={i.priority} digits={2} /></dd></div>
            <div className="text-right"><dt className="text-muted-foreground">{t("Cost", "ค่าใช้จ่าย")}</dt><dd className="font-medium"><Money amount={i.cost} currency={currency} /></dd></div>
          </dl>
          <Link
            href={withSel("/map", { finding: i.finding_id })}
            className="mt-3 flex min-h-11 w-full items-center justify-center rounded-lg border font-medium text-link hover:bg-grey-50"
            aria-label={`${t("Open on map", "เปิดบนแผนที่")}: ${i.label} ${i.finding_id}`}
          >
            {t("Open on map", "เปิดบนแผนที่")}
          </Link>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="md:text-[13px] w-full min-w-[760px] text-left">
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
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4"><PlanPill funded={funded} /></td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4">
                <Link
                  href={withSel("/map", { finding: i.finding_id })}
                  className="inline-flex min-h-11 flex-col justify-center font-medium text-link underline-offset-4 hover:underline"
                >
                  <TypeLabel type={i.type} fallback={i.label} />
                  <span className="num text-xs font-normal text-muted-foreground">{i.finding_id}</span>
                </Link>
              </td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-sm md:text-[13px]">{i.action_label}</td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4"><SeverityBadge severity={i.severity} size="sm" /></td>
              <td className="num py-3 md:py-1.5 pr-4">{i.segment_id}</td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-right"><Num value={i.priority} digits={2} /></td>
              <td className="py-3 md:py-1.5 text-right font-medium"><Money amount={i.cost} currency={currency} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
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
  const t = useT();
  const { withSel } = useSelection();
  const rows = [...items.map((i) => ({ i, funded: true })), ...deferred.map((i) => ({ i, funded: false }))];
  return (
    <>
    <ul className="flex flex-col gap-3 md:hidden">
      {rows.map(({ i, funded }) => (
        <li key={i.segment_id} className={`rounded-lg border p-4 md:p-3 ${funded ? "" : "bg-grey-50"}`}>
          <div className="flex items-start justify-between gap-3">
            <PlanPill funded={funded} />
            <span className="num font-medium">{i.segment_id}</span>
          </div>
          <p className="mt-2 font-medium text-grey-900">{i.label}</p>
          <p className="mt-1"><ConditionChip score={i.condition} /></p>
          <dl className="mt-3 grid grid-cols-3 gap-3 text-sm md:text-[13px]">
            <div><dt className="text-muted-foreground">{t("Area", "พื้นที่")}</dt><dd><Num value={i.area_m2} unit="m²" /></dd></div>
            <div><dt className="text-muted-foreground">{t("Urgency", "ความเร่งด่วน")}</dt><dd><Num value={i.urgency} digits={1} /></dd></div>
            <div className="text-right"><dt className="text-muted-foreground">{t("Cost", "ค่าใช้จ่าย")}</dt><dd className="font-medium"><Money amount={i.cost} currency={currency} /></dd></div>
          </dl>
          <Link
            href={withSel("/map", { segment: i.segment_id })}
            className="mt-3 flex min-h-11 w-full items-center justify-center rounded-lg border font-medium text-link hover:bg-grey-50"
          >
            {t("Open on map", "เปิดบนแผนที่")}
          </Link>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="md:text-[13px] w-full min-w-[760px] text-left">
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
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4"><PlanPill funded={funded} /></td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4">
                <Link
                  href={withSel("/map", { segment: i.segment_id })}
                  className="num inline-flex min-h-11 items-center font-medium text-link underline-offset-4 hover:underline"
                >
                  {i.segment_id}
                </Link>
                {i.road && <span className="ml-2 text-sm md:text-[13px] text-muted-foreground">{i.road}</span>}
              </td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-sm md:text-[13px]">{i.label}</td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-right">
                <ConditionChip score={i.condition} />
              </td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-right"><Num value={i.area_m2} unit="m²" /></td>
              <td className="py-3 md:py-1.5 md:py-1.5 pr-4 text-right"><Num value={i.urgency} digits={1} /></td>
              <td className="py-3 md:py-1.5 text-right font-medium"><Money amount={i.cost} currency={currency} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

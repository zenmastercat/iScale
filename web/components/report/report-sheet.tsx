"use client";
import { useMemo, useState } from "react";
import { usePlan } from "@/components/plan/use-plan";
import { Money, Num } from "@/components/shared/num";
import { SeverityIcon } from "@/components/shared/severity-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { isOpenDefect } from "@/lib/chainage";
import { bandFor, conditionShares, routeCondition } from "@/lib/condition";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAnalysis, useAuthState, useVerification, useWorkOrders } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { Severity, SpotPlan, WorkOrderStatus } from "@/lib/types";

const BAND_TH: Record<string, string> = {
  good: "ดี",
  satisfactory: "พอใช้",
  fair: "ปานกลาง",
  poor: "แย่",
  "very poor": "แย่มาก",
  failed: "ชำรุดหนัก",
  "no data": "ไม่มีข้อมูล",
};
const WO_TH: Record<WorkOrderStatus, string> = {
  open: "เปิด",
  scheduled: "นัดหมายแล้ว",
  completed: "เสร็จแล้ว",
  verified: "ตรวจยืนยันแล้ว",
  partially_verified: "ยืนยันบางส่วน",
  cancelled: "ยกเลิก",
};
const WO_EN: Record<WorkOrderStatus, string> = {
  open: "Open",
  scheduled: "Scheduled",
  completed: "Completed",
  verified: "Verified",
  partially_verified: "Partly verified",
  cancelled: "Cancelled",
};
const SEV: Record<Severity, [string, string]> = {
  high: ["High", "สูง"],
  medium: ["Medium", "กลาง"],
  low: ["Low", "ต่ำ"],
};

const TH = "border-b border-grey-400 py-1 pr-3 text-left text-[10px] font-semibold tracking-wider uppercase text-grey-700 print:text-black";
const TD = "border-b border-grey-200 py-1 pr-3 align-top print:break-inside-avoid";

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="mt-5 mb-2 border-b border-grey-900 pb-1 text-sm font-semibold text-grey-900 print:break-after-avoid print:text-black">{children}</h2>;
}

function Figure({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-grey-300 p-3 print:break-inside-avoid">
      <p className="text-[11px] text-grey-700 print:text-black">{label}</p>
      <p className="num mt-1 text-2xl leading-none font-semibold text-brand print:text-black">{value}</p>
      {sub && <p className="mt-1 text-[11px] text-grey-700 print:text-black">{sub}</p>}
    </div>
  );
}

/** The one-page council report. White A4 sheet on screen; the same markup is what gets printed. */
export function ReportSheet() {
  const t = useT();
  const [today] = useState(() => Date.now() / 1000);
  const { project, survey } = useSelection();
  const { data: auth } = useAuthState();
  const analysis = useAnalysis();
  const planQ = usePlan("spot", null);
  const orders = useWorkOrders();
  const verification = useVerification();

  const stats = useMemo(() => {
    const an = analysis.data;
    if (!an) return null;
    const open = an.findings.filter(isOpenDefect);
    const by: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
    for (const f of open) by[f.severity!]++;
    return {
      by,
      open: open.length,
      score: routeCondition(an.segments),
      lengthM: survey?.stats?.length_m ?? an.segments.reduce((a, s) => a + s.length_m, 0),
      shares: conditionShares(an.segments).filter((s) => s.share > 0),
    };
  }, [analysis.data, survey]);

  if (analysis.isError || planQ.isError)
    return <p role="alert" className="text-sev-high-fg">{t("Could not load the report data.", "โหลดข้อมูลรายงานไม่ได้")}</p>;
  if (!stats || !planQ.data || planQ.data.mode !== "spot") return <Skeleton className="mx-auto h-[600px] w-full max-w-[210mm]" />;

  const plan: SpotPlan = planQ.data;
  const top = [...plan.items, ...plan.deferred].sort((a, b) => b.priority - a.priority).slice(0, 10);
  const band = bandFor(stats.score);
  const v = verification.data;
  const nameOf = (id: string) => project?.survey_list.find((s) => s.id === id)?.name ?? id;
  const woList = orders.data ?? [];

  return (
    <article
      aria-label={t("Council report", "รายงานสำหรับเทศบาล")}
      className="mx-auto w-full max-w-[210mm] bg-white p-6 text-[12px] text-grey-900 [print-color-adjust:exact] md:p-[12mm] print:max-w-none print:p-0 print:text-black print:shadow-none"
    >
      <header className="flex items-start justify-between gap-4 border-b-2 border-grey-900 pb-3">
        <div>
          <p className="text-[11px] tracking-wider text-grey-700 uppercase print:text-black">iScale · {t("Road condition report", "รายงานสภาพถนน")}</p>
          <h1 className="mt-1 text-xl font-semibold text-brand print:text-black">{project?.name}</h1>
          <p className="text-grey-700 print:text-black">{survey?.name}</p>
        </div>
        <dl className="text-right text-[11px]">
          <dt className="sr-only">{t("Date", "วันที่")}</dt>
          <dd className="num">{formatDate(today, false)}</dd>
          {auth?.user && <dd>{auth.user.company}</dd>}
        </dl>
      </header>

      <section aria-label={t("Headline figures", "ตัวเลขสำคัญ")} className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label={t("Condition index", "ดัชนีสภาพถนน")}
          value={<>{stats.score === null ? "–" : formatNumber(stats.score)}<span className="text-sm text-grey-700 print:text-black">/100</span></>}
          sub={t(band.label, BAND_TH[band.rating])}
        />
        <Figure
          label={t("Open defects", "ข้อบกพร่องที่ยังไม่ซ่อม")}
          value={stats.open}
          sub={
            <span className="num">
              {(["high", "medium", "low"] as const).map((s) => `${stats.by[s]} ${t(SEV[s][0].toLowerCase(), SEV[s][1])}`).join(" · ")}
            </span>
          }
        />
        <Figure
          label={t("Repair estimate", "ประมาณการซ่อม")}
          value={<Money amount={plan.total} currency={plan.currency} />}
          sub={t("incl. mobilisation", "รวมค่าเคลื่อนย้าย")}
        />
        <Figure label={t("Road surveyed", "ถนนที่สำรวจ")} value={<Num value={stats.lengthM} unit="m" />} sub={`${analysis.data!.segments.length} ${t("segments", "ช่วงถนน")}`} />
      </section>

      <H>{t("Condition by share of road length", "สภาพถนนตามสัดส่วนความยาว")}</H>
      <div className="flex h-3 overflow-hidden rounded-sm border border-grey-300" aria-hidden>
        {stats.shares.map((s) => (
          <span key={s.band.rating} className={s.band.bg} style={{ width: `${s.share * 100}%` }} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label={t("Share of road length by condition", "สัดส่วนความยาวถนนตามสภาพ")}>
        {stats.shares.map((s) => (
          <li key={s.band.rating} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={`size-2.5 rounded-[2px] ${s.band.bg}`} />
            {t(s.band.label, BAND_TH[s.band.rating])}
            <span className="num font-medium">{formatPercent(s.share)}</span>
          </li>
        ))}
      </ul>

      <H>{t("Top 10 repairs", "งานซ่อมสำคัญ 10 อันดับแรก")}</H>
      {top.length === 0 ? (
        <p className="text-grey-700 print:text-black">{t("No open defects.", "ไม่มีข้อบกพร่องที่ต้องซ่อม")}</p>
      ) : (
        <div className="overflow-x-auto print:overflow-visible">
          <table className="w-full min-w-[480px]">
            <thead>
              <tr>
                <th scope="col" className={TH}>{t("Rank", "ลำดับ")}</th>
                <th scope="col" className={TH}>{t("Finding", "รายการ")}</th>
                <th scope="col" className={TH}>{t("Severity", "ความรุนแรง")}</th>
                <th scope="col" className={TH}>{t("Segment", "ช่วง")}</th>
                <th scope="col" className={TH}>{t("Action", "วิธีซ่อม")}</th>
                <th scope="col" className={`${TH} text-right`}>{t("Cost", "ค่าใช้จ่าย")}</th>
              </tr>
            </thead>
            <tbody>
              {top.map((i, n) => (
                <tr key={i.finding_id}>
                  <td className={`${TD} num`}>{n + 1}</td>
                  <td className={TD}>{i.label} <span className="num text-grey-600 print:text-black">{i.finding_id}</span></td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1">
                      <SeverityIcon severity={i.severity} />
                      {t(SEV[i.severity][0], SEV[i.severity][1])}
                    </span>
                  </td>
                  <td className={`${TD} num`}>{i.segment_id}</td>
                  <td className={TD}>{i.action_label}</td>
                  <td className={`${TD} text-right`}><Money amount={i.cost} currency={plan.currency} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <H>{t("Work orders", "ใบสั่งงาน")}</H>
      {woList.length === 0 ? (
        <p className="text-grey-700 print:text-black">{t("No work orders yet.", "ยังไม่มีใบสั่งงาน")}</p>
      ) : (
        <table className="w-full">
          <thead>
            <tr>
              <th scope="col" className={TH}>{t("Order", "ใบสั่งงาน")}</th>
              <th scope="col" className={TH}>{t("Status", "สถานะ")}</th>
              <th scope="col" className={`${TH} text-right`}>{t("Repairs", "งานซ่อม")}</th>
              <th scope="col" className={`${TH} text-right`}>{t("Cost", "ค่าใช้จ่าย")}</th>
            </tr>
          </thead>
          <tbody>
            {woList.map((w) => (
              <tr key={w.id}>
                <td className={TD}><span className="num">{w.id}</span> {w.title}</td>
                <td className={TD}>{t(WO_EN[w.status], WO_TH[w.status])}</td>
                <td className={`${TD} num text-right`}>{w.items.length}</td>
                <td className={`${TD} text-right`}><Money amount={w.total} currency={w.currency} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <H>{t("Verification", "การตรวจยืนยัน")}</H>
      {v ? (
        <div className="print:break-inside-avoid">
          <p className="text-grey-700 print:text-black">
            {t("Before", "ก่อน")}: <strong>{nameOf(v.before)}</strong> → {t("After", "หลัง")}: <strong>{nameOf(v.after)}</strong>
          </p>
          <p className="mt-1">
            <span className="num font-semibold">{v.counts.verified}</span> {t("verified fixed", "ซ่อมแล้วและยืนยัน")} ·{" "}
            <span className="num font-semibold">{v.counts.not_fixed}</span> {t("still present", "ยังพบอยู่")} ·{" "}
            <span className="num font-semibold">{v.counts.not_covered}</span> {t("not covered by the after drive", "รอบหลังสำรวจไม่ถึง")}
          </p>
        </div>
      ) : (
        <p className="text-grey-700 print:text-black">{t("No verification yet.", "ยังไม่มีการตรวจยืนยัน")}</p>
      )}

      <footer className="mt-5 border-t border-grey-400 pt-2 text-[10px] leading-snug text-grey-700 print:break-inside-avoid print:text-black">
        <p className="font-semibold">{t("How these numbers are made", "ตัวเลขเหล่านี้คำนวณอย่างไร")}</p>
        <p>
          {t(
            "Condition is a 0–100 index from the measured road surface. Severity comes from measured depth or area. Repair costs use the plan's unit rates in USD (placeholder rates); materials-only costs are in THB.",
            "ดัชนีสภาพถนน 0–100 คำนวณจากผิวถนนที่วัดได้ ความรุนแรงมาจากความลึกหรือพื้นที่ที่วัดได้ ค่าซ่อมใช้อัตราต่อหน่วยของแผนเป็นดอลลาร์สหรัฐ (อัตราชั่วคราว) ส่วนค่าวัสดุอย่างเดียวเป็นบาท",
          )}
        </p>
        {plan.note && <p className="mt-1">{plan.note}</p>}
      </footer>
    </article>
  );
}

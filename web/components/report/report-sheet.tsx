"use client";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { usePlan } from "@/components/plan/use-plan";
import { Money, Num } from "@/components/shared/num";
import { SeverityIcon } from "@/components/shared/severity-badge";
import { reviewOf, VERDICT, type Review } from "@/components/report/review";
import { woLabel, woTitle } from "@/components/verification/words";
import { TypeLabel } from "@/components/surveys/type-label";
import { Loading } from "@/components/report/loading";
import { QueryError } from "@/components/surveys/query-error";
import { findingChainage, isOpenDefect } from "@/lib/chainage";
import { bandFor, conditionShares, routeCondition } from "@/lib/condition";
import { getAnalysis, qk } from "@/lib/api";
import { formatChainage, formatDate, formatNumber, formatPercent } from "@/lib/format";
import { useLang, useT } from "@/lib/i18n";
import { useAnalysis, useAuthState, useCatalogLabel, useVerification, useWorkOrders } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { Severity, SpotPlan } from "@/lib/types";

const BAND_TH: Record<string, string> = {
  good: "ดี",
  satisfactory: "พอใช้",
  fair: "ปานกลาง",
  poor: "แย่",
  "very poor": "แย่มาก",
  failed: "ชำรุดหนัก",
  "no data": "ไม่มีข้อมูล",
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
  const { lang } = useLang();
  const labelFor = useCatalogLabel();
  const [today] = useState(() => Date.now() / 1000);
  const { project, survey } = useSelection();
  const { data: auth } = useAuthState();
  const analysis = useAnalysis();
  const planQ = usePlan("spot", null);
  const orders = useWorkOrders();
  const verification = useVerification();
  // condition change needs both drives of the verification
  const vd = verification.data;
  const beforeQ = useQuery({ queryKey: qk.analysis(project?.id ?? "", vd?.before ?? ""), queryFn: () => getAnalysis(project!.id, vd!.before), enabled: !!project && !!vd });
  const afterQ = useQuery({ queryKey: qk.analysis(project?.id ?? "", vd?.after ?? ""), queryFn: () => getAnalysis(project!.id, vd!.after), enabled: !!project && !!vd });

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
      review: (() => {
        // AI findings = defects the pipeline detected (not tagged by hand)
        const ai = an.findings.filter((f) => f.severity && f.source !== "manual");
        const counts: Record<Review["verdict"], number> = { correct: 0, wrong: 0, unsure: 0 };
        for (const f of ai) {
          const r = reviewOf(f);
          if (r) counts[r.verdict]++;
        }
        const reviewed = an.findings
          .map((f) => ({ f, r: reviewOf(f) }))
          .filter((x): x is { f: (typeof an.findings)[number]; r: Review } => !!x.r)
          .sort((a, b) => (b.r.at ?? 0) - (a.r.at ?? 0));
        return { ai: ai.length, counts, left: ai.length - counts.correct - counts.wrong - counts.unsure, reviewed };
      })(),
    };
  }, [analysis.data, survey]);
  // a camera-only survey (the Sukhumvit sample): defects come from a detector, depth is assumed
  const cameraOnly = !!analysis.data?.findings.length && analysis.data.findings.every((f) => f.source === "detector" && f.metrics.depth_assumed);

  if (analysis.isError || planQ.isError)
    return (
      <QueryError
        what={t("Could not load the report data.", "โหลดข้อมูลรายงานไม่ได้")}
        error={analysis.error ?? planQ.error}
        onRetry={() => { analysis.refetch(); planQ.refetch(); }}
      />
    );
  if (!stats || !planQ.data || planQ.data.mode !== "spot") return <Loading className="mx-auto h-[600px] w-full max-w-[210mm]" />;

  const plan: SpotPlan = planQ.data;
  const top = [...plan.items, ...plan.deferred].sort((a, b) => b.priority - a.priority).slice(0, 10);
  const band = bandFor(stats.score);
  const v = verification.data;
  const nameOf = (id: string) => project?.survey_list.find((s) => s.id === id)?.name ?? id;
  const woList = orders.data ?? [];
  const cb = beforeQ.data ? routeCondition(beforeQ.data.segments) : null;
  const ca = afterQ.data ? routeCondition(afterQ.data.segments) : null;
  const change = cb !== null && ca !== null ? { before: cb, after: ca, delta: ca - cb } : null;

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
        <dl className="shrink-0 text-right text-[11px] whitespace-nowrap">
          <dt className="sr-only">{t("Date", "วันที่")}</dt>
          <dd className="num">{formatDate(today, false, lang)}</dd>
          {auth?.user && <dd>{auth.user.company}</dd>}
        </dl>
      </header>

      {stats.open === 0 && (
        <p className="mt-3 rounded-md border border-grey-300 p-2 font-medium">{t("No open defects were found in this survey.", "ไม่พบข้อบกพร่องค้างในการสำรวจนี้")}</p>
      )}

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
        <div
          tabIndex={0}
          role="region"
          aria-label={t("Top 10 repairs table, scrolls sideways", "ตารางงานซ่อม 10 อันดับแรก เลื่อนไปด้านข้างได้")}
          className="overflow-x-auto print:overflow-visible"
        >
          <table className="w-full sm:min-w-[480px]">
            <thead>
              <tr>
                <th scope="col" className={TH}>{t("Rank", "ลำดับ")}</th>
                <th scope="col" className={TH}>{t("Finding", "รายการ")}</th>
                <th scope="col" className={TH}>{t("Severity", "ความรุนแรง")}</th>
                <th scope="col" className={`${TH} hidden sm:table-cell`}>{t("Segment", "ช่วง")}</th>
                <th scope="col" className={TH}>{t("Chainage", "ระยะทาง")}</th>
                <th scope="col" className={`${TH} hidden sm:table-cell`}>{t("Action", "วิธีซ่อม")}</th>
                <th scope="col" className={`${TH} text-right`}>{t("Cost", "ค่าใช้จ่าย")}</th>
              </tr>
            </thead>
            <tbody>
              {top.map((i, n) => (
                <tr key={i.finding_id}>
                  <td className={`${TD} num`}>{n + 1}</td>
                  <td className={TD}><TypeLabel type={i.type} fallback={i.label} /> <span className="num text-grey-600 print:text-black">{i.finding_id}</span></td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1">
                      <SeverityIcon severity={i.severity} />
                      {t(SEV[i.severity][0], SEV[i.severity][1])}
                    </span>
                  </td>
                  <td className={`${TD} num hidden sm:table-cell`}>{i.segment_id}</td>
                  <td className={`${TD} num`}>{(() => { const c = findingChainage(i, analysis.data!.segments); return c === null ? "–" : formatChainage(c); })()}</td>
                  <td className={`${TD} hidden sm:table-cell`}>{i.action_label}</td>
                  <td className={`${TD} text-right`}><Money amount={i.cost} currency={plan.currency} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <H>{t("Human review", "การตรวจโดยคน")}</H>
      <p>
        {t("AI found", "AI พบข้อบกพร่อง")} <span className="num font-semibold">{stats.review.ai}</span> {t("defects;", "จุด")}{" "}
        {t("engineers confirmed", "วิศวกรยืนยัน")} <span className="num font-semibold">{stats.review.counts.correct}</span>,{" "}
        {t("rejected", "ปฏิเสธ")} <span className="num font-semibold">{stats.review.counts.wrong}</span>,{" "}
        {t("unsure", "ไม่แน่ใจ")} <span className="num font-semibold">{stats.review.counts.unsure}</span>,{" "}
        {t("not yet reviewed", "ยังไม่ได้ตรวจ")} <span className="num font-semibold">{stats.review.left}</span>.
      </p>
      <p className="mt-1 text-grey-700 print:text-black">
        {t("AI proposes, people decide: only confirmed findings go to the crew.", "AI เสนอ คนตัดสิน: เฉพาะรายการที่ยืนยันแล้วจึงส่งให้ทีมช่าง")}
      </p>
      {stats.review.reviewed.length > 0 && (
        <div
          tabIndex={0}
          role="region"
          aria-label={t("Reviewed findings table, scrolls sideways", "ตารางรายการที่ตรวจแล้ว เลื่อนไปด้านข้างได้")}
          className="mt-2 overflow-x-auto print:overflow-visible"
        >
          <table className="w-full">
            <thead>
              <tr>
                <th scope="col" className={TH}>{t("Finding", "รายการ")}</th>
                <th scope="col" className={TH}>{t("Type", "ประเภท")}</th>
                <th scope="col" className={TH}>{t("Verdict", "ผลตรวจ")}</th>
                <th scope="col" className={TH}>{t("By", "โดย")}</th>
                <th scope="col" className={TH}>{t("When", "เมื่อ")}</th>
              </tr>
            </thead>
            <tbody>
              {stats.review.reviewed.slice(0, 12).map(({ f, r }) => (
                <tr key={f.id}>
                  <td className={`${TD} num`}>{f.id}</td>
                  <td className={TD}>{labelFor(f.type)}</td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1 font-medium">
                      <span aria-hidden>{r.verdict === "correct" ? "✓" : r.verdict === "wrong" ? "✗" : "?"}</span>
                      {t(...VERDICT[r.verdict])}
                    </span>
                  </td>
                  <td className={TD}>
                    {/* `by` is a user id; only the signed-in user can be named without another request */}
                    {r.by_name ?? (r.by && auth?.user && r.by === auth.user.username ? auth.user.display_name : t("Engineer", "วิศวกร"))}
                  </td>
                  <td className={`${TD} num`}>{r.at ? formatDate(r.at > 1e12 ? r.at / 1000 : r.at, false, lang) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {stats.review.reviewed.length > 12 && (
            <p className="mt-1 text-[11px] text-grey-700 print:text-black">
              {t(`and ${stats.review.reviewed.length - 12} more`, `และอีก ${stats.review.reviewed.length - 12} รายการ`)}
            </p>
          )}
        </div>
      )}

      <H>{t("Work orders", "ใบสั่งงาน")}</H>
      {orders.isError ? (
        <QueryError what={t("Could not load work orders", "โหลดใบสั่งงานไม่ได้")} error={orders.error} onRetry={() => orders.refetch()} />
      ) : orders.isLoading ? (
        <Loading className="h-10 w-full" />
      ) : woList.length === 0 ? (
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
                <td className={TD}><span className="num">{w.id}</span> {woTitle(t, w.title)}</td>
                <td className={TD}>{woLabel(t, w.status)}</td>
                <td className={`${TD} num text-right`}>{w.items.length}</td>
                <td className={`${TD} text-right`}><Money amount={w.total} currency={w.currency} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <H>{t("Verification", "การตรวจยืนยัน")}</H>
      {verification.isError ? (
        <QueryError what={t("Could not load the verification", "โหลดผลตรวจยืนยันไม่ได้")} error={verification.error} onRetry={() => verification.refetch()} />
      ) : verification.isLoading ? (
        <Loading className="h-10 w-full" />
      ) : v ? (
        <div className="print:break-inside-avoid">
          <p className="text-grey-700 print:text-black">
            {t("Before", "ก่อน")}: <strong>{nameOf(v.before)}</strong> → {t("After", "หลัง")}: <strong>{nameOf(v.after)}</strong>
          </p>
          <p className="mt-1">
            <span className="num font-semibold">{v.counts.verified}</span> {t("verified fixed", "ซ่อมแล้วและยืนยัน")} ·{" "}
            <span className="num font-semibold">{v.counts.not_fixed}</span> {t("still present", "ยังพบอยู่")} ·{" "}
            <span className="num font-semibold">{v.counts.not_covered}</span> {t("not covered by the after drive", "รอบหลังสำรวจไม่ถึง")}
          </p>
          {change && (
            <p className="mt-1">
              {t("Condition index", "ดัชนีสภาพถนน")}: <span className="num font-semibold">{formatNumber(change.before, 1)}</span> →{" "}
              <span className="num font-semibold">{formatNumber(change.after, 1)}</span>{" "}
              <span className="num">({change.delta >= 0 ? "+" : "−"}{formatNumber(Math.abs(change.delta), 1)})</span>{" "}
              {t("between the two drives", "ระหว่างการสำรวจสองรอบ")}
            </p>
          )}
        </div>
      ) : (
        <p className="text-grey-700 print:text-black">{t("No verification yet.", "ยังไม่มีการตรวจยืนยัน")}</p>
      )}

      <footer className="mt-5 border-t border-grey-400 pt-2 text-[10px] leading-snug text-grey-700 print:break-inside-avoid print:text-black">
        <p className="font-semibold">{t("How these numbers are made", "ตัวเลขเหล่านี้คำนวณอย่างไร")}</p>
        <p>
          {cameraOnly
            ? t(
                "This survey is a camera run with no 3D surface. Defects were found by an AI detector in the video, and their size comes from the detector's box. Depth is assumed (5 cm), not measured; road width and surface roughness are unknown. Condition is a 0–100 index from those defects only. All amounts are in Thai baht. Repair costs use the plan's unit rates, which are placeholders in the demo; materials-only costs are shown separately.",
                "การสำรวจนี้เป็นการขับถ่ายวิดีโอ ไม่มีผิวถนน 3 มิติ AI ตรวจพบข้อบกพร่องจากวิดีโอ ขนาดมาจากกรอบของตัวตรวจจับ ความลึกเป็นค่าสมมติ (5 ซม.) ไม่ได้วัดจริง ความกว้างถนนและความขรุขระไม่ทราบค่า ดัชนีสภาพถนน 0–100 คำนวณจากข้อบกพร่องเหล่านี้เท่านั้น ทุกจำนวนเงินเป็นบาท ค่าซ่อมใช้อัตราต่อหน่วยของแผน ซึ่งเป็นอัตราชั่วคราวในข้อมูลตัวอย่าง ส่วนค่าวัสดุอย่างเดียวแสดงแยกต่างหาก",
              )
            : t(
                "Condition is a 0–100 index from the measured road surface. Severity comes from measured depth or area. All amounts are in Thai baht. Repair costs use the plan's unit rates, which are placeholders in the demo; materials-only costs are shown separately.",
                "ดัชนีสภาพถนน 0–100 คำนวณจากผิวถนนที่วัดได้ ความรุนแรงมาจากความลึกหรือพื้นที่ที่วัดได้ ทุกจำนวนเงินเป็นบาท ค่าซ่อมใช้อัตราต่อหน่วยของแผน ซึ่งเป็นอัตราชั่วคราวในข้อมูลตัวอย่าง ส่วนค่าวัสดุอย่างเดียวแสดงแยกต่างหาก",
              )}
        </p>
        {plan.note && <p className="mt-1">{plan.note}</p>}
      </footer>
    </article>
  );
}

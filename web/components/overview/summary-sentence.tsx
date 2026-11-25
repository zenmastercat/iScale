"use client";
import { formatMoney, formatNumber } from "@/lib/format";
import { useLang } from "@/lib/i18n";

export function SummarySentence({
  lengthM,
  score,
  open,
  high,
  cost,
  currency,
}: {
  lengthM: number;
  score: number | null;
  open: number;
  high: number;
  cost: number | null;
  currency: string;
}) {
  const { lang } = useLang();
  if (lang === "th")
    return (
      <section aria-label="สรุป" className="rounded-lg border bg-card px-6 py-6 md:px-5 md:py-4">
        <p className="text-xl leading-relaxed text-grey-900 md:text-xl md:leading-relaxed">
          ถนน <b className="num font-semibold">{formatNumber(lengthM)} ม.</b> ได้คะแนน{" "}
          <b className="font-semibold">{score === null ? "ไม่มีข้อมูล" : `${formatNumber(score)} จาก 100`}</b>{" "}
          {open === 0 ? (
            <>ไม่มีข้อบกพร่องที่ต้องซ่อม</>
          ) : (
            <>
              มีข้อบกพร่องที่ยังไม่ซ่อม <b className="font-semibold">{open} จุด</b>
              {high > 0 && (
                <>
                  {" "}รุนแรงสูง <b className="font-semibold">{high}</b> จุด
                </>
              )}
              {cost !== null && (
                <>
                  {" "}ประมาณค่าซ่อม <b className="num font-semibold">{formatMoney(cost, currency)}</b>
                </>
              )}
            </>
          )}
        </p>
      </section>
    );
  return (
    <section aria-label="Summary" className="rounded-lg border bg-card px-6 py-6 md:px-5 md:py-4">
      <p className="text-xl leading-relaxed text-grey-900 md:text-xl md:leading-relaxed">
        <b className="num font-semibold">{formatNumber(lengthM)} m</b> of road scored{" "}
        <b className="font-semibold">{score === null ? "no score" : `${formatNumber(score)} out of 100`}</b>.{" "}
        {open === 0 ? (
          <>There are no open defects.</>
        ) : (
          <>
            There {open === 1 ? "is" : "are"} <b className="font-semibold">{open} open defect{open === 1 ? "" : "s"}</b>
            {high > 0 && (
              <>
                , <b className="font-semibold">{high}</b> of them high severity
              </>
            )}
            {cost !== null && (
              <>
                , and fixing them is estimated at <b className="num font-semibold">{formatMoney(cost, currency)}</b>
              </>
            )}
            .
          </>
        )}
      </p>
    </section>
  );
}

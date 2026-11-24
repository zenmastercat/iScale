import { formatMoney, formatNumber } from "@/lib/format";

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
  return (
    <section aria-label="Summary" className="rounded-lg border bg-card px-6 py-6 md:px-8">
      <p className="text-xl leading-relaxed text-grey-900 md:text-2xl md:leading-relaxed">
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

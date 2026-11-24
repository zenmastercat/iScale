import { formatMoney } from "@/lib/format";

/** Stacked bar: funded (solid) vs deferred (hatched), with the numbers spelled out underneath. */
export function BudgetBar({
  funded,
  deferred,
  currency,
}: {
  funded: number;
  deferred: number;
  currency: string;
}) {
  const total = funded + deferred;
  const fp = total > 0 ? (funded / total) * 100 : 0;
  return (
    <div>
      <div
        role="img"
        aria-label={`Funded ${formatMoney(funded, currency)}, deferred ${formatMoney(deferred, currency)}`}
        className="flex h-6 w-full overflow-hidden rounded-md border bg-grey-50"
      >
        <div className="h-full bg-brand transition-[width] duration-200" style={{ width: `${fp}%` }} />
        <div
          className="h-full flex-1"
          style={{
            backgroundImage:
              "repeating-linear-gradient(45deg, var(--color-grey-300) 0 4px, transparent 4px 8px)",
          }}
        />
      </div>
      <div className="mt-2 flex flex-wrap justify-between gap-x-6 gap-y-1 text-sm">
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block size-3 rounded-sm bg-brand" />
          Funded <span className="num font-medium">{formatMoney(funded, currency)}</span>
        </span>
        <span className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block size-3 rounded-sm border"
            style={{ backgroundImage: "repeating-linear-gradient(45deg, var(--color-grey-300) 0 2px, transparent 2px 4px)" }}
          />
          Deferred <span className="num font-medium">{formatMoney(deferred, currency)}</span>
        </span>
      </div>
    </div>
  );
}

import { formatMoney, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A number in Plex Mono with tabular figures: <Num value={7.8} digits={1} unit="cm" /> */
export function Num({
  value,
  digits = 0,
  unit,
  className,
}: {
  value: number | null | undefined;
  digits?: number;
  unit?: string;
  className?: string;
}) {
  return (
    <span className={cn("num whitespace-nowrap", className)}>
      {formatNumber(value, digits)}
      {unit && value !== null && value !== undefined ? ` ${unit}` : ""}
    </span>
  );
}

/** Money in Plex Mono: <Money amount={2585} currency="USD" /> → "USD 2,585"; style="symbol" → "฿1,645" */
export function Money({
  amount,
  currency = "USD",
  style = "code",
  symbol,
  digits = 0,
  className,
}: {
  amount: number | null | undefined;
  currency?: string;
  style?: "code" | "symbol";
  symbol?: string;
  digits?: number;
  className?: string;
}) {
  return <span className={cn("num whitespace-nowrap", className)}>{formatMoney(amount, currency, { style, symbol, digits })}</span>;
}

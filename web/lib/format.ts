/* Number, money, length and date formatting. Render figures with class="num" (Plex Mono, tabular). */

const nf = (digits: number) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** 1234.5 → "1,235" (digits=0) or "1,234.5" (digits=1). null/undefined → "–" */
export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return nf(digits).format(n);
}

const SYMBOLS: Record<string, string> = { THB: "฿", USD: "$", EUR: "€" };

/** The app's currency. Plan, work-order and materials costs are all in baht (config/unit_costs.json). */
export const APP_CURRENCY = "THB";

/**
 * Money, rounded to whole units unless digits is given. Baht is always "฿2,585" (Thai convention);
 * other currencies: style "code" → "USD 2,585", style "symbol" → "$2,585".
 */
export function formatMoney(
  amount: number | null | undefined,
  currency = APP_CURRENCY,
  { style = "code", digits = 0, symbol }: { style?: "code" | "symbol"; digits?: number; symbol?: string } = {},
): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "–";
  const n = formatNumber(amount, digits);
  if (currency === "THB") return `${amount < 0 ? "−" : ""}฿${formatNumber(Math.abs(amount), digits)}`;
  if (style === "symbol") return `${symbol ?? SYMBOLS[currency] ?? currency + " "}${n}`;
  return `${currency} ${n}`;
}

/** metres → "242 m"; ≥ 1000 → "1.24 km" */
export function formatLength(m: number | null | undefined): string {
  if (m === null || m === undefined) return "–";
  return m >= 1000 ? `${formatNumber(m / 1000, 2)} km` : `${formatNumber(m, 0)} m`;
}

/** chainage in metres → "0+121" (km+metres), as engineers write it */
export function formatChainage(m: number): string {
  const km = Math.floor(m / 1000);
  const rest = Math.round(m - km * 1000);
  return `${km}+${String(rest).padStart(3, "0")}`;
}

/** metres → "7.8 cm" */
export const formatCm = (m: number | null | undefined, digits = 1) =>
  m === null || m === undefined ? "–" : `${formatNumber(m * 100, digits)} cm`;

/** 0.7 → "70%" */
export const formatPercent = (share: number, digits = 0) => `${formatNumber(share * 100, digits)}%`;

/** unix seconds → "24 Nov 2026, 17:40" */
export function formatDate(unixSeconds: number, withTime = true): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(new Date(unixSeconds * 1000));
}

/** "manhole_sunken" → "Manhole sunken" (fallback when the catalog has no label) */
export const humanize = (code: string) => {
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

/* Condition bands, exactly as civil/analysis/condition.py BANDS. */
import type { Rating, Segment } from "@/lib/types";

export interface Band {
  rating: Rating;
  label: string;
  /** Thai label */
  th: string;
  /** lowest score in the band (inclusive) */
  min: number;
  color: string;
  /** Tailwind bg class for the band colour */
  bg: string;
  /** "85+" / "70–84" for legends */
  range: string;
}

export const CONDITION_BANDS: Band[] = [
  { rating: "good", label: "Good", th: "ดี", min: 85, color: "#3fb37f", bg: "bg-cond-good", range: "85+" },
  { rating: "satisfactory", label: "Satisfactory", th: "ค่อนข้างดี", min: 70, color: "#9fc84a", bg: "bg-cond-satisfactory", range: "70–84" },
  { rating: "fair", label: "Fair", th: "พอใช้", min: 55, color: "#e8c547", bg: "bg-cond-fair", range: "55–69" },
  { rating: "poor", label: "Poor", th: "แย่", min: 40, color: "#ef8f36", bg: "bg-cond-poor", range: "40–54" },
  { rating: "very poor", label: "Very poor", th: "แย่มาก", min: 25, color: "#e0503a", bg: "bg-cond-very-poor", range: "25–39" },
  { rating: "failed", label: "Failed", th: "ใช้งานไม่ได้", min: 0, color: "#8c1d2c", bg: "bg-cond-failed", range: "0–24" },
];

export const NO_DATA_BAND: Band = {
  rating: "no data",
  label: "No data", th: "ไม่มีข้อมูล",
  min: -1,
  color: "#6b7280",
  bg: "bg-cond-none",
  range: "",
};

/** Band for a 0-100 score; null → "no data". */
export function bandFor(score: number | null | undefined): Band {
  if (score === null || score === undefined) return NO_DATA_BAND;
  return CONDITION_BANDS.find((b) => score >= b.min) ?? CONDITION_BANDS[CONDITION_BANDS.length - 1];
}

export function bandByRating(rating: Rating): Band {
  return CONDITION_BANDS.find((b) => b.rating === rating) ?? NO_DATA_BAND;
}

/** Length-weighted mean condition of the segments that have data. null when none do. */
export function routeCondition(segments: Segment[]): number | null {
  let w = 0;
  let sum = 0;
  for (const s of segments) {
    if (s.condition === null) continue;
    w += s.length_m;
    sum += s.condition * s.length_m;
  }
  return w ? sum / w : null;
}

/** Share of route length in each band (including "no data"), in band order. Shares sum to 1. */
export function conditionShares(segments: Segment[]): { band: Band; share: number; length_m: number }[] {
  const total = segments.reduce((a, s) => a + s.length_m, 0) || 1;
  return [...CONDITION_BANDS, NO_DATA_BAND].map((band) => {
    const length_m = segments.filter((s) => bandFor(s.condition).rating === band.rating).reduce((a, s) => a + s.length_m, 0);
    return { band, share: length_m / total, length_m };
  });
}

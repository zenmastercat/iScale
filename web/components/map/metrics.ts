import type { Segment } from "@/lib/types";

export const COLOUR_KEYS = ["condition", "roughness", "coverage", "width"] as const;
export type ColourBy = (typeof COLOUR_KEYS)[number];
export const parseColour = (v: string | null): ColourBy => (COLOUR_KEYS as readonly string[]).includes(v ?? "") ? (v as ColourBy) : "condition";

/** Single-hue scale (accent blue), light to dark. Higher value = darker. */
export const BLUE_STEPS = ["#d6e6f5", "#9cc2e8", "#5b95d1", "#2a5f9e"];
const NO_VALUE = "#9ca3af";

export interface MetricDef {
  en: string;
  th: string;
  unit: string;
  digits: number;
  pick: (s: Segment) => number | null;
}

export const METRICS: Record<Exclude<ColourBy, "condition">, MetricDef> = {
  roughness: { en: "Roughness", th: "ความขรุขระ", unit: "mm", digits: 1, pick: (s) => s.metrics?.surface_std_mm ?? null },
  coverage: { en: "Coverage", th: "ความครอบคลุม", unit: "%", digits: 0, pick: (s) => (s.metrics?.coverage != null ? s.metrics.coverage * 100 : null) },
  width: { en: "Road width", th: "ความกว้างถนน", unit: "m", digits: 1, pick: (s) => s.metrics?.road_width_m ?? null },
};

/** Four equal-width steps between the min and max of the metric over these segments. */
export function metricScale(segments: Segment[], m: MetricDef) {
  const vals = segments.map(m.pick).filter((v): v is number => v !== null);
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 0;
  const w = (hi - lo) / BLUE_STEPS.length;
  const steps = BLUE_STEPS.map((color, i) => ({ color, from: lo + w * i, to: i === BLUE_STEPS.length - 1 ? hi : lo + w * (i + 1) }));
  const colorFor = (v: number | null) => {
    if (v === null) return NO_VALUE;
    if (w <= 0) return BLUE_STEPS[1];
    return BLUE_STEPS[Math.min(BLUE_STEPS.length - 1, Math.max(0, Math.floor((v - lo) / w)))];
  };
  return { steps, colorFor };
}

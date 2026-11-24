import { cn } from "@/lib/utils";
import type { Severity } from "@/lib/types";

export const SEVERITY: Record<Severity, { label: string; text: string; bg: string; fill: string; color: string }> = {
  high: { label: "High", text: "text-sev-high-fg", bg: "bg-sev-high-bg", fill: "fill-sev-high", color: "#c2361f" },
  medium: { label: "Medium", text: "text-sev-medium-fg", bg: "bg-sev-medium-bg", fill: "fill-sev-medium", color: "#c27a12" },
  low: { label: "Low", text: "text-sev-low-fg", bg: "bg-sev-low-bg", fill: "fill-sev-low", color: "#23775a" },
};

/** Shape per severity so colour is never the only cue: high ▲, medium ●, low ▼. */
export function SeverityIcon({
  severity,
  size = 12,
  className,
  title,
}: {
  severity: Severity;
  size?: number;
  className?: string;
  /** set when the icon stands alone (no visible word next to it) */
  title?: string;
}) {
  const fill = SEVERITY[severity].fill;
  return (
    <svg
      viewBox="0 0 12 12"
      width={size}
      height={size}
      className={cn("shrink-0", fill, className)}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {severity === "high" && <path d="M6 1 11.2 10.5H.8Z" />}
      {severity === "medium" && <circle cx="6" cy="6" r="4.6" />}
      {severity === "low" && <path d="M6 11 .8 1.5h10.4Z" />}
    </svg>
  );
}

/** Colour + icon + word. Pass severity null for assets (renders nothing). */
export function SeverityBadge({
  severity,
  size = "md",
  className,
}: {
  severity: Severity | null | undefined;
  size?: "sm" | "md";
  className?: string;
}) {
  if (!severity) return null;
  const s = SEVERITY[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md font-medium whitespace-nowrap",
        s.text,
        s.bg,
        size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm",
        className,
      )}
    >
      <SeverityIcon severity={severity} size={size === "sm" ? 9 : 11} />
      {s.label}
    </span>
  );
}

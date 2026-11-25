"use client";
import { isUnreviewed } from "@/lib/findings-filter";
import { useAnalysis, useVerification } from "@/lib/queries";

/** Numbers for the Overview's next-step card and the side rail's badges. null = not loaded yet. */
export function useReviewCounts() {
  const analysis = useAnalysis();
  const verification = useVerification();
  return {
    /** AI findings still waiting for an engineer */
    unreviewed: analysis.data ? analysis.data.findings.filter(isUnreviewed).length : null,
    /** repairs the re-drive found still present */
    stillPresent: verification.data ? verification.data.counts.not_fixed : null,
  };
}

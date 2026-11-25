import type { Finding } from "@/lib/types";

/** Engineer review of an AI finding (finding.review, saved with the analysis). Declared here until lib/types.ts has it. */
export interface Review {
  verdict: "correct" | "wrong" | "unsure";
  note?: string;
  /** user id (not a name) */
  by?: string;
  /** display name added by the server when it can */
  by_name?: string;
  /** unix seconds */
  at?: number;
}

export const reviewOf = (f: Finding): Review | null => {
  const r = (f as Finding & { review?: Review | null }).review;
  return r && (r.verdict === "correct" || r.verdict === "wrong" || r.verdict === "unsure") ? r : null;
};

/** [English, Thai] for each verdict, as the report words it. */
export const VERDICT: Record<Review["verdict"], [string, string]> = {
  correct: ["Confirmed", "ยืนยันว่าถูกต้อง"],
  wrong: ["Rejected", "ปฏิเสธ"],
  unsure: ["Unsure", "ไม่แน่ใจ"],
};

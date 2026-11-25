"use client";
import { useCallback } from "react";
import { statusLabel } from "@/components/shared";
import { useT } from "@/lib/i18n";
import type { FindingStatus } from "@/lib/types";

const STATUS_TH: Record<FindingStatus, string> = {
  open: "ยังไม่ซ่อม",
  planned: "วางแผนแล้ว",
  fixed: "ซ่อมแล้ว",
  verified: "ยืนยันแล้ว",
  not_fixed: "ยังพบอยู่",
  dismissed: "ยกเลิก",
};

export const BAND_TH: Record<string, string> = {
  good: "ดี",
  satisfactory: "พอใช้",
  fair: "ปานกลาง",
  poor: "แย่",
  "very poor": "แย่มาก",
  failed: "ชำรุดหนัก",
  "no data": "ไม่มีข้อมูล",
};

/** Status and condition-band words in the current language (the shared pills are English only). */
export function useWords() {
  const t = useT();
  const status = useCallback((s: string) => t(statusLabel(s as FindingStatus), STATUS_TH[s as FindingStatus] ?? s), [t]);
  const band = useCallback((rating: string, label: string) => t(label, BAND_TH[rating] ?? label), [t]);
  return { status, band };
}

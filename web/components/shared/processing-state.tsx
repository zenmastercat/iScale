"use client";
import { AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Survey } from "@/lib/types";
import { useT } from "@/lib/i18n";

/** Shown while a survey is queued/running, or when it failed. Pass the survey record. */
export function ProcessingState({ survey, action, className }: { survey?: Survey; action?: React.ReactNode; className?: string }) {
  const t = useT();
  const failed = survey?.status === "error";
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("flex flex-col items-center justify-center rounded-lg border bg-card px-6 py-12 text-center", className)}
    >
      {failed ? (
        <AlertTriangle aria-hidden className="mb-3 size-8 text-sev-high" />
      ) : (
        <Loader2 aria-hidden className="mb-3 size-8 animate-spin text-accent-blue" />
      )}
      <h2 className="text-lg font-semibold text-brand">
        {failed ? t("This survey failed to process", "ประมวลผลการสำรวจนี้ไม่สำเร็จ") : survey ? t(`Processing “${survey.name}”`, `กำลังประมวลผล “${survey.name}”`) : t("Loading…", "กำลังโหลด…")}
      </h2>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">
        {failed
          ? survey?.error || t("Unknown error.", "ข้อผิดพลาดที่ไม่ทราบสาเหตุ")
          : survey?.status === "queued"
            ? t("Waiting in the queue.", "รอคิว")
            : survey?.stage
              ? t(`Now: ${survey.stage}.`, `ขณะนี้: ${survey.stage}`)
              : t("Decoding the drive and measuring the road. The demo takes about 20 seconds.", "กำลังถอดข้อมูลการขับและวัดผิวถนน ตัวอย่างใช้เวลาประมาณ 20 วินาที")}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

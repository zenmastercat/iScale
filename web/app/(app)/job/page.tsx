"use client";
import { ClipboardList } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { JobCardView } from "@/components/jobcard/job-card";
import { SurveyGate } from "@/components/shared";
import { EmptyState } from "@/components/shared/empty-state";
import { useT } from "@/lib/i18n";

export default function JobcardPage() {
  const t = useT();
  const id = useSearchParams().get("finding");
  return (
    <SurveyGate>
      {id ? (
        <JobCardView findingId={id} />
      ) : (
        <EmptyState
          icon={ClipboardList}
          title={t("Choose a finding", "เลือกรายการ")}
          description={t("Open a finding from the map or Fix first and press Open job card.", "เปิดรายการจากแผนที่หรือหน้าซ่อมก่อน แล้วกด เปิดใบงาน")}
        />
      )}
    </SurveyGate>
  );
}

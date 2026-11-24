"use client";
import { useSearchParams } from "next/navigation";
import { JobCardView } from "@/components/jobcard/job-card";
import { SurveyGate } from "@/components/shared";
import { EmptyState } from "@/components/shared/empty-state";
import { ClipboardList } from "lucide-react";

export default function JobcardPage() {
  const id = useSearchParams().get("finding");
  return (
    <SurveyGate>
      {id ? (
        <JobCardView findingId={id} />
      ) : (
        <EmptyState icon={ClipboardList} title="Choose a finding" description="Open a finding from the map or Fix first and press Open job card." />
      )}
    </SurveyGate>
  );
}

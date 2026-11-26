"use client";
import { ReviewQueue } from "@/components/review/review-queue";
import { SurveyGate } from "@/components/shared";

export default function ReviewPage() {
  return (
    <SurveyGate>
      <ReviewQueue />
    </SurveyGate>
  );
}

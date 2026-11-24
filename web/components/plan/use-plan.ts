"use client";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getPlan, qk } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import type { Plan } from "@/lib/types";

/** Plan for one mode and budget. Keeps the previous result on screen while a new budget loads. */
export function usePlan(mode: "spot" | "segment", budget: number | null) {
  const { projectId, surveyId, survey } = useSelection();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  return useQuery<Plan>({
    queryKey: qk.plan(pid, sid, mode, budget),
    queryFn: () => (mode === "spot" ? getPlan(pid, sid, "spot", budget) : getPlan(pid, sid, "segment", budget)),
    enabled: !!projectId && !!surveyId && survey?.status === "done",
    placeholderData: keepPreviousData,
  });
}

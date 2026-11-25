"use client";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getPlan, qk } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import type { Plan } from "@/lib/types";

/**
 * Budget 0 means "fund nothing". The API helper treats 0 like "no budget" (`budget || undefined`), so a
 * zero-budget plan is built here from the unlimited plan instead of asking the server.
 */
export function zeroBudgetPlan(all: Plan): Plan {
  const deferred = [...all.items, ...all.deferred] as typeof all.deferred;
  return all.mode === "spot"
    ? { ...all, budget: 0, items: [], deferred: deferred as typeof all.deferred, mobilization: 0, total: 0, by_action: [] }
    : { ...all, budget: 0, items: [], deferred: deferred as typeof all.deferred, total: 0 };
}

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

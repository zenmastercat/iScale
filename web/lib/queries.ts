"use client";
/* Ready-made TanStack Query hooks for the current selection. Prefer these over raw useQuery
   so every page shares one cache entry per resource. */
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  getAnalysis,
  getAuthState,
  getMeta,
  getPlan,
  getPriority,
  getVerification,
  listWorkOrders,
  qk,
} from "@/lib/api";
import { CATALOG_TH } from "@/lib/catalog-th";
import { humanize } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

export function useAuthState() {
  return useQuery({ queryKey: qk.authState, queryFn: getAuthState, staleTime: 60_000 });
}

export function useMeta() {
  return useQuery({ queryKey: qk.meta, queryFn: getMeta, staleTime: Infinity });
}

/** label("manhole_sunken") → "Sunken manhole" (from /api/meta catalog), humanized fallback */
export function useCatalogLabel() {
  const { data } = useMeta();
  const { lang } = useLang();
  return useCallback(
    (code: string) =>
      (lang === "th" ? CATALOG_TH[code] : undefined) ?? data?.catalog.find((c) => c.code === code)?.label ?? humanize(code),
    [data, lang],
  );
}

/** true when the selected survey exists and finished processing */
function useReadySurvey() {
  const { projectId, surveyId, survey } = useSelection();
  return { pid: projectId ?? "", sid: surveyId ?? "", ready: !!projectId && !!surveyId && survey?.status === "done" };
}

export function useAnalysis() {
  const { pid, sid, ready } = useReadySurvey();
  return useQuery({ queryKey: qk.analysis(pid, sid), queryFn: () => getAnalysis(pid, sid), enabled: ready });
}

export function usePriority(limit = 100) {
  const { pid, sid, ready } = useReadySurvey();
  // limit is part of the key: usePriority(5) must not fill the cache that usePriority() reads.
  // Invalidating qk.priority(pid, sid) still hits every limit (prefix match).
  return useQuery({ queryKey: [...qk.priority(pid, sid), limit], queryFn: () => getPriority(pid, sid, limit), enabled: ready });
}

export function useSpotPlan(budget?: number | null) {
  const { pid, sid, ready } = useReadySurvey();
  return useQuery({
    queryKey: qk.plan(pid, sid, "spot", budget),
    queryFn: () => getPlan(pid, sid, "spot", budget),
    enabled: ready,
    placeholderData: (prev) => prev, // keep the last plan on screen while the slider moves
  });
}

export function useSegmentPlan(budget?: number | null) {
  const { pid, sid, ready } = useReadySurvey();
  return useQuery({
    queryKey: qk.plan(pid, sid, "segment", budget),
    queryFn: () => getPlan(pid, sid, "segment", budget),
    enabled: ready,
    placeholderData: (prev) => prev,
  });
}

export function useWorkOrders() {
  const { projectId } = useSelection();
  return useQuery({ queryKey: qk.workOrders(projectId ?? ""), queryFn: () => listWorkOrders(projectId!), enabled: !!projectId });
}

export function useVerification() {
  const { projectId } = useSelection();
  return useQuery({ queryKey: qk.verification(projectId ?? ""), queryFn: () => getVerification(projectId!), enabled: !!projectId });
}

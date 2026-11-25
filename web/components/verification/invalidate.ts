import type { QueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/api";

/** Everything that changes when a work order moves or a verification runs: Overview, Fix first, Map, Plan. */
export function invalidateRepairState(qc: QueryClient, pid: string, baseline?: string | null) {
  qc.invalidateQueries({ queryKey: qk.workOrders(pid) });
  qc.invalidateQueries({ queryKey: qk.verification(pid) });
  if (baseline) {
    qc.invalidateQueries({ queryKey: qk.analysis(pid, baseline) });
    qc.invalidateQueries({ queryKey: qk.priority(pid, baseline) });
  }
  // every survey of the project (analysis, priority, plan) and the project record itself
  qc.invalidateQueries({ queryKey: qk.project(pid) });
}

"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { runVerify } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import type { WorkOrder } from "@/lib/types";

const NONE = "__none__";

export function VerifyPanel({ orders, workorderId }: { orders: WorkOrder[]; workorderId: string | null }) {
  const { projectId, project } = useSelection();
  const qc = useQueryClient();
  const surveys = project?.survey_list.filter((s) => s.status === "done") ?? [];
  // user choices; null = use the default derived from the project
  const [beforeSel, setBefore] = useState<string | null>(null);
  const [afterSel, setAfter] = useState<string | null>(null);
  const [woSel, setWo] = useState<string | null>(null);
  const before = beforeSel ?? project?.baseline ?? surveys[0]?.id ?? "";
  const after = afterSel ?? surveys.find((s) => s.id !== before)?.id ?? "";
  const wo = woSel ?? workorderId ?? NONE;

  const run = useMutation({
    mutationFn: () =>
      runVerify(projectId!, { before, after, workorder_id: wo === NONE ? null : wo }),
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ["project", projectId!] });
      toast.success(`Verified ${v.counts.verified}, not fixed ${v.counts.not_fixed}, not covered ${v.counts.not_covered}`);
    },
    onError: (e: Error) => toast.error(`Verification failed: ${e.message}`),
  });

  const sItems = surveys.map((s) => ({ value: s.id, label: s.name }));
  const woItems = [
    { value: NONE, label: "All repaired findings" },
    ...orders.map((o) => ({ value: o.id, label: `${o.id} · ${o.title}` })),
  ];
  const ok = !!before && !!after && before !== after;

  const field = (label: string, id: string, items: { value: string; label: string }[], value: string, set: (v: string) => void) => (
    <div className="flex min-w-48 flex-1 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-grey-700">{label}</label>
      <Select items={items} value={value} onValueChange={(v) => v && set(v as string)}>
        <SelectTrigger id={id} className="h-11 w-full"><SelectValue placeholder="Choose…" /></SelectTrigger>
        <SelectContent>
          {items.map((i) => (
            <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <div>
      <div className="flex flex-wrap items-end gap-4">
        {field("Before survey (baseline)", "verify-before", sItems, before, setBefore)}
        {field("After survey (repairs done)", "verify-after", sItems, after, setAfter)}
        {field("Work order", "verify-wo", woItems, wo, setWo)}
        <Button className="min-h-11" disabled={!ok || run.isPending} onClick={() => run.mutate()}>
          <ShieldCheck aria-hidden />
          {run.isPending ? "Checking…" : "Run verification"}
        </Button>
      </div>
      {surveys.length < 2 && (
        <p className="mt-3 text-sm text-muted-foreground">Verification needs two processed surveys: a before and an after.</p>
      )}
      {before && before === after && <p role="alert" className="mt-3 text-sm text-sev-high-fg">Pick two different surveys.</p>}
    </div>
  );
}

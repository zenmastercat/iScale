"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { useEffect, useRef } from "react";
import { Money, Num, SeverityBadge, StatusPill } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, createWorkOrder, getJobCard, qk } from "@/lib/api";
import { findingChainage } from "@/lib/chainage";
import { formatChainage } from "@/lib/format";
import { useAnalysis, useCatalogLabel } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { Finding } from "@/lib/types";
import { TrustBadge } from "./trust";
import { useMediaQuery } from "./use-media";

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md bg-grey-50 px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="num text-lg font-medium text-grey-900">{children}</div>
    </div>
  );
}

export function FindingDrawer({ findingId, onClose }: { findingId: string | null; onClose: () => void }) {
  const wide = useMediaQuery("(min-width: 768px)");
  const lastId = useRef(findingId);
  useEffect(() => {
    if (findingId) lastId.current = findingId;
  }, [findingId]);
  const analysis = useAnalysis();
  const finding = findingId ? analysis.data?.findings.find((f) => f.id === findingId) : undefined;
  return (
    <Sheet open={!!findingId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        initialFocus={() => document.querySelector<HTMLElement>('[data-slot="sheet-close"]')}
        finalFocus={() => (lastId.current ? document.querySelector<HTMLElement>(`[data-finding-id="${CSS.escape(lastId.current)}"]`) : null)}
        className={wide ? "w-full sm:max-w-md" : "max-h-[85dvh] overflow-y-auto rounded-t-lg"}
      >
        {findingId && analysis.data && !finding ? (
          <SheetHeader>
            <SheetTitle>Finding not found</SheetTitle>
            <SheetDescription>No finding {findingId} in this survey.</SheetDescription>
          </SheetHeader>
        ) : finding && analysis.data ? (
          <DrawerBody f={finding} segments={analysis.data.segments} />
        ) : (
          <div className="p-4"><Skeleton className="h-64 w-full" /></div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function DrawerBody({ f, segments }: { f: Finding; segments: import("@/lib/types").Segment[] }) {
  const { projectId, surveyId, withSel } = useSelection();
  const label = useCatalogLabel();
  const qc = useQueryClient();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  const card = useQuery({ queryKey: qk.jobCard(pid, sid, f.id), queryFn: () => getJobCard(pid, sid, f.id), enabled: !!pid && !!sid });
  const chain = findingChainage(f, segments);
  const m = f.metrics;
  const photo = card.data?.location.photo;
  const cost = card.data?.cost.available ? card.data.cost : null;
  const addWO = useMutation({
    mutationFn: () => createWorkOrder(pid, { survey_id: sid, finding_ids: [f.id] }),
    onSuccess: (wo) => {
      toast.success(`Added to work order ${wo.id}`);
      qc.invalidateQueries({ queryKey: qk.workOrders(pid) });
      qc.invalidateQueries({ queryKey: qk.analysis(pid, sid) });
      qc.invalidateQueries({ queryKey: qk.priority(pid, sid) });
      qc.invalidateQueries({ queryKey: qk.jobCard(pid, sid, f.id) });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not create the work order"),
  });
  const canAdd = !!f.severity && f.status === "open";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 pt-5">
      <div>
        <p className="num text-sm text-muted-foreground">
          {f.id}
          {f.segment_id && ` · ${f.segment_id}`}
          {chain !== null && ` · chainage ${formatChainage(chain)}`}
        </p>
        <SheetTitle className="mt-1 text-2xl font-semibold">{label(f.type)}</SheetTitle>
        <SheetDescription className="sr-only">Finding details</SheetDescription>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={f.severity} />
          <TrustBadge source={f.source} />
          {f.status !== "open" && <StatusPill status={f.status} />}
        </div>
      </div>

      {card.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photo.url} alt={`Drive frame of ${label(f.type)}`} className="w-full rounded-lg border" />
      ) : (
        <div className="grid h-32 place-items-center rounded-lg border border-dashed bg-grey-50 text-sm text-muted-foreground">
          <span className="flex items-center gap-2"><ImageOff className="size-4" aria-hidden />No drive frame for this survey</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {m.depth_max_m !== undefined && <Metric label="Depth"><Num value={m.depth_max_m * 100} digits={1} unit="cm" /></Metric>}
        {m.diameter_m !== undefined && <Metric label="Across"><Num value={m.diameter_m} digits={2} unit="m" /></Metric>}
        {m.volume_m3 !== undefined && <Metric label="Missing"><Num value={m.volume_m3 * 1000} digits={1} unit="L" /></Metric>}
        {m.area_m2 !== undefined && <Metric label="Area"><Num value={m.area_m2} digits={2} unit="m²" /></Metric>}
      </div>

      <p className="text-sm leading-relaxed">
        <span className="font-semibold">Why flagged: </span>
        {f.evidence}
      </p>

      {(card.isLoading || cost) && (
        <div className="flex items-baseline justify-between border-t pt-3">
          <span className="text-sm text-muted-foreground">Materials only</span>
          {cost ? <Money amount={cost.materials_cost} style="symbol" symbol={cost.symbol} className="text-2xl font-semibold text-brand" /> : <Skeleton className="h-7 w-24" />}
        </div>
      )}
      {card.isError && <p className="text-sm text-muted-foreground">Job card details unavailable.</p>}

      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button nativeButton={false} className="min-h-11 flex-1 bg-brand text-white hover:bg-brand/90" render={<Link href={withSel("/job", { finding: f.id })} />}>
          Open job card
        </Button>
        <Button variant="outline" className="min-h-11 flex-1" disabled={!canAdd || addWO.isPending} onClick={() => addWO.mutate()}>
          {addWO.isPending ? "Adding…" : f.status === "planned" ? "In a work order" : "Add to work order"}
        </Button>
      </div>
      {!f.severity && <p className="text-xs text-muted-foreground">Assets are inventory and can&apos;t be added to a work order.</p>}
    </div>
  );
}

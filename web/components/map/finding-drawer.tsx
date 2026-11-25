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
import { useLang, useT } from "@/lib/i18n";
import type { Finding } from "@/lib/types";
import { AiEvidence } from "./ai-evidence";
import { checkKey, getCheck } from "./check3d";
import { History } from "./history";
import { QrBlock } from "./qr-block";
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
  const t = useT();
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
            <SheetTitle>{t("Finding not found", "ไม่พบรายการ")}</SheetTitle>
            <SheetDescription>{t(`No finding ${findingId} in this survey.`, `ไม่มีรายการ ${findingId} ในการสำรวจนี้`)}</SheetDescription>
            <Button className="mt-3 min-h-11 bg-brand text-white hover:bg-brand/90" onClick={onClose}>{t("Back to the map", "กลับไปที่แผนที่")}</Button>
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
  const t = useT();
  const { lang } = useLang();
  const qc = useQueryClient();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  const card = useQuery({ queryKey: qk.jobCard(pid, sid, f.id), queryFn: () => getJobCard(pid, sid, f.id), enabled: !!pid && !!sid });
  const check = useQuery({ queryKey: checkKey(pid, sid, f.id), queryFn: () => getCheck(pid, sid, f.id), enabled: !!pid && !!sid && !!f.review, retry: false });
  const reviewerNames: Record<string, string> = f.review?.by && check.data?.review?.by_name ? { [f.review.by]: check.data.review.by_name } : {};
  const chain = findingChainage(f, segments);
  const m = f.metrics;
  const photo = card.data?.location.photo;
  const cost = card.data?.cost.available ? card.data.cost : null;
  const addWO = useMutation({
    mutationFn: () => createWorkOrder(pid, { survey_id: sid, finding_ids: [f.id] }),
    onSuccess: (wo) => {
      toast.success(t(`Added to work order ${wo.id}`, `เพิ่มในใบสั่งงาน ${wo.id} แล้ว`));
      qc.invalidateQueries({ queryKey: qk.workOrders(pid) });
      qc.invalidateQueries({ queryKey: qk.analysis(pid, sid) });
      qc.invalidateQueries({ queryKey: qk.priority(pid, sid) });
      qc.invalidateQueries({ queryKey: qk.verification(pid) });
      qc.invalidateQueries({ queryKey: ["project", pid, "survey", sid, "plan"] });
      qc.invalidateQueries({ queryKey: qk.jobCard(pid, sid, f.id) });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("Could not create the work order", "สร้างใบสั่งงานไม่สำเร็จ")),
  });
  const canAdd = !!f.severity && f.status === "open";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 pt-5">
      <div>
        <p className="num text-sm text-muted-foreground">
          {f.id}
          {f.segment_id && ` · ${f.segment_id}`}
          {chain !== null && ` · ${t("chainage", "ระยะทาง")} ${formatChainage(chain)}`}
        </p>
        <SheetTitle className="mt-1 text-2xl font-semibold">{label(f.type)}</SheetTitle>
        <SheetDescription className="sr-only">{t("Finding details", "รายละเอียดรายการ")}</SheetDescription>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={f.severity} />
          <TrustBadge source={f.source} />
          {f.needs_review && <span className="inline-flex items-center rounded-md border border-sev-medium bg-sev-medium-bg px-2 py-0.5 text-xs font-medium text-sev-medium-fg">▲ {t("Check first", "ตรวจก่อน")}</span>}
          {f.status !== "open" && <StatusPill status={f.status} />}
        </div>
      </div>

      {card.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photo.url} alt={t(`Drive frame of ${label(f.type)}`, `ภาพจากการสำรวจของ ${label(f.type)}`)} className="w-full rounded-lg border" />
      ) : f.photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/api/projects/${encodeURIComponent(projectId ?? "")}/surveys/${encodeURIComponent(surveyId ?? "")}/findings/${encodeURIComponent(f.id)}/photo`} alt={t(`Detector crop of ${label(f.type)}`, `ภาพตัดจากตัวตรวจจับของ ${label(f.type)}`)} className="max-h-64 w-full rounded-lg border object-contain bg-grey-50" />
      ) : (
        <div className="grid h-32 place-items-center rounded-lg border border-dashed bg-grey-50 text-sm text-muted-foreground">
          <span className="flex items-center gap-2"><ImageOff className="size-4" aria-hidden />{t("No drive frame for this survey", "ไม่มีภาพจากการสำรวจ")}</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {m.depth_max_m !== undefined && <Metric label={m.depth_assumed ? t("Depth (assumed)", "ความลึก (สมมติ)") : t("Depth", "ความลึก")}><Num value={m.depth_max_m * 100} digits={1} unit="cm" /></Metric>}
        {m.diameter_m !== undefined && <Metric label={t("Across", "ความกว้าง")}><Num value={m.diameter_m} digits={2} unit="m" /></Metric>}
        {m.volume_m3 !== undefined && <Metric label={t("Missing", "ปริมาตรที่หาย")}><Num value={m.volume_m3 * 1000} digits={1} unit="L" /></Metric>}
        {m.area_m2 !== undefined && <Metric label={t("Area", "พื้นที่")}><Num value={m.area_m2} digits={2} unit="m²" /></Metric>}
        {m.step_m !== undefined && <Metric label={t("Step", "ระดับต่าง")}><Num value={m.step_m * 100} digits={1} unit="cm" /></Metric>}
        {m.height_max_m !== undefined && <Metric label={t("Height", "ความสูง")}><Num value={m.height_max_m * 100} digits={1} unit="cm" /></Metric>}
      </div>

      <p className="text-sm leading-relaxed">
        <span className="font-semibold">{t("Why flagged: ", "เหตุที่พบ: ")}</span>
        {lang === "th" && f.evidence_th ? f.evidence_th : f.evidence}
      </p>

      {(card.isLoading || cost) && (
        <div className="flex items-baseline justify-between border-t pt-3">
          <span className="text-sm text-muted-foreground">{t("Materials only", "เฉพาะค่าวัสดุ")}</span>
          {cost ? <Money amount={cost.materials_cost} style="symbol" symbol={cost.symbol} className="text-2xl font-semibold text-brand" /> : <Skeleton className="h-7 w-24" />}
        </div>
      )}
      {card.isError && (
        <p className="text-sm text-muted-foreground">
          {t("Job card details unavailable.", "ไม่มีข้อมูลใบงาน")}{" "}
          <button type="button" className="font-medium text-link underline underline-offset-4" onClick={() => card.refetch()}>{t("Retry", "ลองใหม่")}</button>
        </p>
      )}

      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button nativeButton={false} className="min-h-11 flex-1 bg-brand text-white hover:bg-brand/90" render={<Link href={withSel("/job", { finding: f.id })} />}>
          {t("Open job card", "เปิดใบงาน")}
        </Button>
        <Button variant="outline" className="min-h-11 flex-1" disabled={!canAdd || addWO.isPending} onClick={() => addWO.mutate()}>
          {addWO.isPending ? t("Adding…", "กำลังเพิ่ม…") : f.status === "planned" ? t("In a work order", "อยู่ในใบสั่งงานแล้ว") : t("Add to work order", "เพิ่มในใบสั่งงาน")}
        </Button>
      </div>
      <AiEvidence findingId={f.id} status={f.status} detector={f.detector} confidence={f.confidence} detectionPhoto={f.detection_photo} />
      <History entries={f.history} names={reviewerNames} />
      <QrBlock findingId={f.id} />
      {!f.severity && <p className="text-xs text-muted-foreground">{t("Assets are inventory and can't be added to a work order.", "สินทรัพย์เป็นรายการสำรวจ เพิ่มในใบสั่งงานไม่ได้")}</p>}
    </div>
  );
}

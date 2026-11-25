"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { runVerify } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { invalidateRepairState } from "./invalidate";
import type { WorkOrder } from "@/lib/types";

const NONE = "__none__";

export function VerifyPanel({ orders, workorderId }: { orders: WorkOrder[]; workorderId: string | null }) {
  const t = useT();
  const { projectId, project, withSel } = useSelection();
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
      invalidateRepairState(qc, projectId!, project?.baseline);
      toast.success(t(`Verified ${v.counts.verified}, still present ${v.counts.not_fixed}, not covered ${v.counts.not_covered}`, `ยืนยันแล้ว ${v.counts.verified} ยังพบอยู่ ${v.counts.not_fixed} สำรวจไม่ถึง ${v.counts.not_covered}`));
    },
    onError: (e: Error) => toast.error(`${t("Verification failed", "ตรวจยืนยันไม่สำเร็จ")}: ${e.message}`),
  });

  const sItems = surveys.map((s) => ({ value: s.id, label: s.name }));
  const woItems = [
    { value: NONE, label: t("All repaired findings", "ทุกรายการที่ซ่อม") },
    ...orders.map((o) => ({ value: o.id, label: `${o.id} · ${o.title}` })),
  ];
  const ok = !!before && !!after && before !== after;

  const field = (label: string, id: string, items: { value: string; label: string }[], value: string, set: (v: string) => void) => (
    <div className="flex min-w-48 flex-1 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-grey-700">{label}</label>
      <Select items={items} value={value} onValueChange={(v) => v && set(v as string)}>
        <SelectTrigger id={id} className="h-11 w-full"><SelectValue placeholder={t("Choose…", "เลือก…")} /></SelectTrigger>
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
        {field(t("Before survey (baseline)", "การสำรวจก่อนซ่อม (ฐาน)"), "verify-before", sItems, before, setBefore)}
        {field(t("After survey (repairs done)", "การสำรวจหลังซ่อม"), "verify-after", sItems, after, setAfter)}
        {field(t("Work order", "ใบสั่งงาน"), "verify-wo", woItems, wo, setWo)}
        <Button type="button" variant="default" className="min-h-11" disabled={!ok || run.isPending} onClick={() => run.mutate()}>
          <ShieldCheck aria-hidden />
          {run.isPending ? t("Checking…", "กำลังตรวจ…") : t("Run verification", "เริ่มตรวจยืนยัน")}
        </Button>
      </div>
      {surveys.length < 2 && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t(
            "Verification compares a before drive with an after drive. This project has only one processed survey, so drive the road again after the repairs and add that survey.",
            "การตรวจยืนยันเทียบการสำรวจก่อนซ่อมกับหลังซ่อม โครงการนี้มีการสำรวจที่ประมวลผลแล้วเพียงรอบเดียว ให้สำรวจถนนอีกครั้งหลังซ่อมแล้วเพิ่มการสำรวจนั้น",
          )}{" "}
          <Link href={withSel("/surveys")} className="inline-flex min-h-11 items-center font-medium text-link underline underline-offset-4">
            {t("Go to Surveys", "ไปที่หน้าการสำรวจ")}
          </Link>
        </p>
      )}
      {before && before === after && <p role="alert" className="mt-3 text-sm text-sev-high-fg">{t("Pick two different surveys.", "เลือกการสำรวจสองรอบที่ต่างกัน")}</p>}
    </div>
  );
}

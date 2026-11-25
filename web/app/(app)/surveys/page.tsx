"use client";
import { AlertTriangle, CheckCircle2, Loader2, RotateCw, Clock, Star } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import Link from "next/link";
import { toast } from "sonner";
import { AddSurveyDialog } from "@/components/surveys/add-survey-dialog";
import { DemoButton } from "@/components/shared/demo-button";
import { EmptyState } from "@/components/shared/empty-state";
import { Num } from "@/components/shared/num";
import { ProcessingState } from "@/components/shared/processing-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { retrySurvey, setBaseline } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useMeta } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { Survey } from "@/lib/types";

function StatusCell({ s }: { s: Survey }) {
  const t = useT();
  if (s.status === "done")
    return <span className="inline-flex items-center gap-1.5 font-medium"><CheckCircle2 aria-hidden className="size-4 text-sev-low-fg" />{t("Ready", "พร้อมใช้")}</span>;
  if (s.status === "error")
    return (
      <span className="inline-flex items-start gap-1.5 text-sev-high-fg">
        <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span><span className="font-medium">{t("Failed", "ล้มเหลว")}</span>{s.error && <span className="block text-sm md:text-[13px]">{s.error}</span>}</span>
      </span>
    );
  const Icon = s.status === "queued" ? Clock : Loader2;
  return (
    <span role="status" className="inline-flex items-start gap-1.5">
      <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${s.status === "running" ? "animate-spin" : ""}`} />
      <span>
        <span className="font-medium">{s.status === "queued" ? t("Queued", "รอคิว") : t("Processing", "กำลังประมวลผล")}</span>
        {s.stage && <span className="block text-sm md:text-[13px] text-muted-foreground">{s.stage}</span>}
      </span>
    </span>
  );
}

export default function SurveysPage() {
  const t = useT();
  const { projectId, project, projects, projectsLoading, surveyId, setSurvey, withSel } = useSelection();
  const { data: meta } = useMeta();
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["project", projectId!] });
  const baseline = useMutation({
    mutationFn: (sid: string) => setBaseline(projectId!, sid),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["projects"] }); setConfirm(null); toast.success(t("Baseline updated", "ตั้งค่าฐานแล้ว")); },
    onError: (e: Error) => toast.error(e.message),
  });
  const retry = useMutation({
    mutationFn: (sid: string) => retrySurvey(projectId!, sid),
    onSuccess: () => { refresh(); toast.success(t("Processing again", "กำลังประมวลผลอีกครั้ง")); },
    onError: (e: Error) => toast.error(e.message),
  });
  const [confirm, setConfirm] = useState<Survey | null>(null);
  const decoderLabel = (n: string) => meta?.decoders.find((d) => d.name === n)?.label ?? n;

  return (
    <>
      <PageHeader title={t("Surveys", "การสำรวจ")} crumb={project?.name} actions={projectId ? <AddSurveyDialog /> : null} />
      {projectsLoading || (projectId && !project) ? (
        <Skeleton className="h-64 w-full" />
      ) : !projects?.length || !projectId ? (
        <EmptyState title={t("No projects yet", "ยังไม่มีโครงการ")} description={t("Load the demo street, or create a project in the old UI first.", "โหลดถนนตัวอย่าง หรือสร้างโครงการใน UI เดิมก่อน")} action={<DemoButton />} />
      ) : !project!.survey_list.length ? (
        <EmptyState title={t("No surveys yet", "ยังไม่มีการสำรวจ")} description={t("Add a drive video, a LiDAR point cloud, or the demo street.", "เพิ่มวิดีโอขับรถ จุดสแกน LiDAR หรือถนนตัวอย่าง")} action={<AddSurveyDialog />} />
      ) : (
        <div className="flex flex-col gap-4">
        {project!.survey_list
          .filter((s) => s.status === "queued" || s.status === "running")
          .map((s) => (
            <ProcessingState key={s.id} survey={s} />
          ))}
        <section className="rounded-lg border bg-card p-5 md:p-4" aria-label={t("Surveys", "การสำรวจ")}>
          <div className="relative overflow-x-auto">
            <table className="md:text-[13px] w-full min-w-[820px] text-left">
              <thead>
                <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
                  <th scope="col" className="py-3 md:py-1.5 pr-4 font-semibold">{t("Survey", "การสำรวจ")}</th>
                  <th scope="col" className="py-3 md:py-1.5 pr-4 font-semibold">{t("Source", "แหล่งข้อมูล")}</th>
                  <th scope="col" className="py-3 md:py-1.5 pr-4 font-semibold">{t("Status", "สถานะ")}</th>
                  <th scope="col" className="py-3 md:py-1.5 pr-4 text-right font-semibold">{t("Road", "ถนน")}</th>
                  <th scope="col" className="py-3 md:py-1.5 pr-4 text-right font-semibold">{t("Findings", "ข้อบกพร่อง")}</th>
                  <th scope="col" className="py-3 md:py-1.5 pr-4 font-semibold">{t("Added", "เพิ่มเมื่อ")}</th>
                  <th scope="col" className="py-3 md:py-1.5"><span className="sr-only">{t("Actions", "การดำเนินการ")}</span></th>
                </tr>
              </thead>
              <tbody>
                {project!.survey_list.map((s) => (
                  <tr key={s.id} className="border-b align-top last:border-0">
                    <td className="py-3 md:py-1.5 pr-4">
                      <p className="font-medium text-grey-900">{s.name}</p>
                      {s.id === project!.baseline && (
                        <span className="inline-flex items-center gap-1 text-sm md:text-[13px] text-muted-foreground"><Star aria-hidden className="size-3.5" />{t("Baseline", "ฐาน")}</span>
                      )}
                      {s.id === surveyId && <span className="block text-sm md:text-[13px] text-muted-foreground">{t("Selected", "เลือกอยู่")}</span>}
                    </td>
                    <td className="py-3 md:py-1.5 pr-4 text-sm md:text-[13px]">{decoderLabel(s.decoder)}</td>
                    <td className="py-3 md:py-1.5 pr-4"><StatusCell s={s} /></td>
                    <td className="py-3 md:py-1.5 pr-4 text-right">{s.stats ? <Num value={s.stats.length_m} unit="m" /> : "–"}</td>
                    <td className="py-3 md:py-1.5 pr-4 text-right">{s.stats ? <Num value={s.stats.findings} /> : "–"}</td>
                    <td className="py-3 md:py-1.5 pr-4 text-sm md:text-[13px]">{formatDate(s.created)}</td>
                    <td className="py-3 md:py-1.5">
                      <div className="flex flex-wrap justify-end gap-2">
                        {s.status === "done" && s.id !== surveyId && (
                          <Button variant="outline" className="min-h-11" onClick={() => setSurvey(s.id)}>{t("Select", "เลือก")}</Button>
                        )}
                        {s.status === "done" && (
                          <Link href={withSel("/", { survey: s.id })} className="inline-flex min-h-11 items-center px-2 font-medium text-link underline underline-offset-4">
                            {t("Overview", "ภาพรวม")}
                          </Link>
                        )}
                        {s.status === "done" && s.id !== project!.baseline && (
                          <Button variant="outline" className="min-h-11" onClick={() => setConfirm(s)}>{t("Set as baseline", "ตั้งเป็นฐาน")}</Button>
                        )}
                        {s.status === "error" && (
                          <Button variant="outline" className="min-h-11" disabled={retry.isPending} onClick={() => retry.mutate(s.id)}>
                            <RotateCw aria-hidden />{t("Retry", "ลองอีกครั้ง")}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        </div>
      )}
      <Dialog open={!!confirm} onOpenChange={(o) => !o && !baseline.isPending && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(`Set “${confirm?.name}” as the baseline?`, `ตั้ง “${confirm?.name}” เป็นฐานหรือไม่`)}</DialogTitle>
            <DialogDescription>
              {t(
                "The baseline is the “before” drive that repairs are checked against. Verification will compare later surveys with this one.",
                "ฐานคือการสำรวจรอบ “ก่อนซ่อม” ที่ใช้เทียบกับงานซ่อม การตรวจยืนยันจะเทียบรอบหลังกับรอบนี้",
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="min-h-11" onClick={() => setConfirm(null)}>{t("Cancel", "ยกเลิก")}</Button>
            <Button className="min-h-11" disabled={baseline.isPending} onClick={() => confirm && baseline.mutate(confirm.id)}>
              {baseline.isPending ? t("Saving…", "กำลังบันทึก…") : t("Set as baseline", "ตั้งเป็นฐาน")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleHelp, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, patchFinding, qk } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { cn } from "@/lib/utils";
import type { FindingStatus } from "@/lib/types";
import { checkKey, getCheck, postReview, type ReviewVerdict } from "./check3d";

const VERDICTS: { v: ReviewVerdict; en: string; th: string; Icon: typeof Check }[] = [
  { v: "correct", en: "Correct", th: "ถูกต้อง", Icon: Check },
  { v: "wrong", en: "Wrong", th: "ผิด", Icon: X },
  { v: "unsure", en: "Unsure", th: "ไม่แน่ใจ", Icon: CircleHelp },
];

/** "Check in 3D": what the AI saw, the evidence images, and the engineer's call. AI proposes, people decide. */
export function AiEvidence({ findingId, status, detector, confidence, detectionPhoto }: { findingId: string; status: FindingStatus; detectionPhoto?: boolean; detector?: import("@/lib/types").Finding["detector"]; confidence?: number }) {
  const t = useT();
  const qc = useQueryClient();
  const { projectId, surveyId } = useSelection();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  const q = useQuery({ queryKey: checkKey(pid, sid, findingId), queryFn: () => getCheck(pid, sid, findingId), enabled: !!pid && !!sid, retry: false });
  const refresh = () => {
    for (const key of [qk.analysis(pid, sid), ["project", pid, "survey", sid, "plan"], qk.priority(pid, sid), qk.verification(pid)])
      qc.invalidateQueries({ queryKey: key });
  };
  const review = useMutation({
    // A Wrong review alone does not take the finding out of the plan, so dismiss it too.
    mutationFn: async (v: ReviewVerdict) => {
      const data = await postReview(pid, sid, findingId, v);
      if (v === "wrong") await patchFinding(pid, sid, findingId, { status: "dismissed" });
      return data;
    },
    onSuccess: (data, v) => {
      qc.setQueryData(checkKey(pid, sid, findingId), data);
      refresh();
      toast.success(v === "wrong" ? t("Rejected and removed from the plan", "ปฏิเสธและนำออกจากแผนแล้ว") : t("Review saved", "บันทึกผลตรวจแล้ว"));
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("Could not save the review", "บันทึกผลตรวจไม่สำเร็จ")),
  });

  const undo = useMutation({
    mutationFn: () => patchFinding(pid, sid, findingId, { status: "open" }),
    onSuccess: () => {
      refresh();
      toast.success(t("Back in the plan", "กลับเข้าแผนแล้ว"));
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("Could not undo", "ย้อนกลับไม่สำเร็จ")),
  });
  const removed = status === "dismissed";

  const title = t("AI evidence", "หลักฐานจาก AI");
  const stats =
    confidence !== undefined || detector ? (
      <p className="num text-sm text-muted-foreground">
        {confidence !== undefined && <>{t("Confidence", "ความมั่นใจ")} {Math.round(confidence * 100)}%</>}
        {detector && <>{confidence !== undefined && " · "}{detector.hits} {t("hits", "ครั้งที่พบ")} · {detector.frames} {t("frames", "เฟรม")}</>}
      </p>
    ) : null;
  if (q.isLoading)
    return (
      <section className="flex flex-col gap-2 border-t pt-3" aria-label={title} aria-busy="true">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Skeleton className="h-40 w-full" />
      </section>
    );
  if (q.isError || !q.data)
    return (
      <section className="flex flex-col gap-1 border-t pt-3" aria-label={title}>
        <h3 className="text-sm font-semibold">{title}</h3>
        {stats}
        <p className="text-sm text-muted-foreground">
          {t("The check is not available for this finding.", "ไม่มีการตรวจสำหรับรายการนี้")}{" "}
          <button type="button" className="font-medium text-link underline underline-offset-4" onClick={() => q.refetch()}>
            {t("Retry", "ลองใหม่")}
          </button>
        </p>
      </section>
    );

  const c = q.data;
  const r = c.review;
  const who = r?.by_name || r?.by || t("someone", "ผู้ใช้");
  const stamp = r
    ? r.verdict === "correct"
      ? t(`Confirmed by ${who}`, `ยืนยันโดย ${who}`)
      : r.verdict === "wrong"
        ? t(`Rejected by ${who}`, `ปฏิเสธโดย ${who}`)
        : t(`Marked unsure by ${who}`, `ไม่แน่ใจโดย ${who}`)
    : null;

  return (
    <section className="flex flex-col gap-3 border-t pt-3" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="flex flex-col gap-2">
        {c.photo_only && (
          <>
            <p className="text-xs text-muted-foreground">{t("Review the photo above: no 3D model for camera-only runs", "ตรวจจากภาพด้านบน: รันจากกล้องอย่างเดียวไม่มีโมเดล 3D")}</p>
            {detectionPhoto && (
              <figure className="flex flex-col gap-1">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/projects/${encodeURIComponent(pid)}/surveys/${encodeURIComponent(sid)}/findings/${encodeURIComponent(findingId)}/detection`}
                  alt={t("What the detector saw: its box and confidence on the camera frame", "สิ่งที่ตัวตรวจจับเห็น: กรอบและความมั่นใจบนภาพจากกล้อง")}
                  className="w-full rounded-md border bg-grey-50 object-contain"
                  loading="lazy"
                />
                <figcaption className="text-xs text-muted-foreground">{t("Detector's view: box, confidence and distance ahead of the camera", "มุมมองของตัวตรวจจับ: กรอบ ความมั่นใจ และระยะห่างจากกล้อง")}</figcaption>
              </figure>
            )}
          </>
        )}
        {c.images.section && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={c.images.section}
            alt={t(
              "Cross-section of the road surface through the finding: the line dips below the surrounding road",
              "ภาพตัดขวางผิวถนนผ่านรายการที่พบ เส้นผิวต่ำลงกว่าถนนโดยรอบ",
            )}
            className="w-full rounded-md border bg-grey-50"
            loading="lazy"
          />
        )}
        {c.images.height && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={c.images.height}
            alt={t("Height map from above: red is below the road, blue is above it", "แผนที่ความสูงมองจากด้านบน สีแดงต่ำกว่าถนน สีน้ำเงินสูงกว่าถนน")}
            className="w-40 rounded-md border bg-grey-50"
            loading="lazy"
          />
        )}
      </div>
      {stats}
      <div className="text-sm">
        <p className="font-medium">{t("What the AI saw", "สิ่งที่ AI เห็น")}</p>
        <p className="mt-0.5 text-muted-foreground">{c.verdict.text}</p>
        {c.verdict.warnings.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 rounded-md border border-sev-medium bg-sev-medium-bg p-2 text-xs text-sev-medium-fg">
            {c.verdict.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <p className="mb-1.5 text-sm font-medium">{t("Your call: is the AI right?", "การตัดสินของคุณ: AI ถูกหรือไม่")}</p>
        <div role="group" aria-label={t("Review the AI evidence", "ตรวจหลักฐานจาก AI")} className="flex gap-2">
          {VERDICTS.map(({ v, en, th, Icon }) => (
            <Button
              key={v}
              type="button"
              variant={r?.verdict === v ? "default" : "outline"}
              aria-pressed={r?.verdict === v}
              disabled={review.isPending}
              className={cn("min-h-11 flex-1", r?.verdict === v && "bg-brand text-white hover:bg-brand/90")}
              onClick={() => review.mutate(v)}
            >
              <Icon className="size-4" aria-hidden />
              {t(en, th)}
            </Button>
          ))}
        </div>
        {r && stamp && (
          <p className="mt-2 text-sm text-muted-foreground" role="status">
            {stamp} · <span className="num">{formatDate(r.at)}</span>
            {r.verdict === "wrong" && removed && <> · {t("removed from the plan", "นำออกจากแผนแล้ว")}</>}
          </p>
        )}
        {removed && (
          <Button type="button" variant="outline" className="mt-2 min-h-11" disabled={undo.isPending} onClick={() => undo.mutate()}>
            {undo.isPending ? t("Restoring…", "กำลังคืนค่า…") : t("Undo: put it back in the plan", "ย้อนกลับ: นำกลับเข้าแผน")}
          </Button>
        )}
      </div>
    </section>
  );
}

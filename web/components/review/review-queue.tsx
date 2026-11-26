"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, CircleHelp, Undo2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { EvidenceImages, verdictText, warningText } from "@/components/map/ai-evidence";
import { checkKey, getCheck, postReview, type ReviewVerdict } from "@/components/map/check3d";
import { RetryError } from "@/components/map/retry-error";
import { Num, SeverityBadge } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, patchFinding, qk } from "@/lib/api";
import { findingChainage } from "@/lib/chainage";
import { formatChainage } from "@/lib/format";
import { isUnreviewed } from "@/lib/findings-filter";
import { useT } from "@/lib/i18n";
import { useAnalysis, useCatalogLabel } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { Analysis, Finding } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEV = { high: 0, medium: 1, low: 2 } as const;
const KEYS: { v: ReviewVerdict; key: string; en: string; th: string; Icon: typeof Check }[] = [
  { v: "correct", key: "C", en: "Correct", th: "ถูกต้อง", Icon: Check },
  { v: "wrong", key: "W", en: "Wrong", th: "ผิด", Icon: X },
  { v: "unsure", key: "U", en: "Unsure", th: "ไม่แน่ใจ", Icon: CircleHelp },
];

/** The findings an engineer still has to judge: weak tracks first, then by severity and position along the road. */
function queueOf(a: Analysis): string[] {
  return a.findings
    .filter(isUnreviewed)
    .sort(
      (x, y) =>
        Number(!!y.needs_review) - Number(!!x.needs_review) ||
        SEV[x.severity ?? "low"] - SEV[y.severity ?? "low"] ||
        (findingChainage(x, a.segments) ?? 0) - (findingChainage(y, a.segments) ?? 0),
    )
    .map((f) => f.id);
}

/** Full-screen triage: one AI finding at a time, evidence beside the numbers, C / W / U to decide. */
export function ReviewQueue() {
  const t = useT();
  const analysis = useAnalysis();
  const [round, setRound] = useState(0);
  if (analysis.isError)
    return <div className="p-6"><RetryError title={t("Could not load the findings", "โหลดรายการไม่สำเร็จ")} message={analysis.error.message} onRetry={() => analysis.refetch()} busy={analysis.isFetching} /></div>;
  if (!analysis.data) return <div className="p-6"><Skeleton className="h-96 w-full" /></div>;
  // the queue is fixed when a round starts, so "4 / 10" does not shift as answers refresh the analysis
  return <Queue key={round} initialIds={queueOf(analysis.data)} analysis={analysis.data} onAgain={() => setRound((r) => r + 1)} />;
}

function Queue({ initialIds, analysis, onAgain }: { initialIds: string[]; analysis: Analysis; onAgain: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const label = useCatalogLabel();
  const { projectId, surveyId, withSel } = useSelection();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  const [ids] = useState(initialIds);
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, ReviewVerdict>>({});
  const [trail, setTrail] = useState<string[]>([]); // answered ids, newest last, for Undo
  const total = ids.length;
  const done = idx >= total;
  const f: Finding | undefined = done ? undefined : analysis.findings.find((x) => x.id === ids[idx]);
  const id = f?.id ?? "";

  const check = useQuery({ queryKey: checkKey(pid, sid, id), queryFn: () => getCheck(pid, sid, id), enabled: !!id && !!pid && !!sid, retry: false });
  const nextId = ids[idx + 1];
  useEffect(() => {
    if (nextId && pid && sid) qc.prefetchQuery({ queryKey: checkKey(pid, sid, nextId), queryFn: () => getCheck(pid, sid, nextId), retry: false });
  }, [nextId, pid, sid, qc]);

  const refresh = () => {
    for (const key of [qk.analysis(pid, sid), ["project", pid, "survey", sid, "plan"], qk.priority(pid, sid), qk.verification(pid)]) qc.invalidateQueries({ queryKey: key });
  };
  const answer = useMutation({
    // same as the drawer: a Wrong review also takes the finding out of the plan
    mutationFn: async (v: ReviewVerdict) => {
      const data = await postReview(pid, sid, id, v);
      if (v === "wrong") await patchFinding(pid, sid, id, { status: "dismissed" });
      return data;
    },
    onSuccess: (data, v) => {
      qc.setQueryData(checkKey(pid, sid, id), data);
      setAnswers((a) => ({ ...a, [id]: v }));
      setTrail((tr) => [...tr, id]);
      setIdx((i) => i + 1);
      refresh();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("Could not save the review", "บันทึกผลตรวจไม่สำเร็จ")),
  });
  const undo = useMutation({
    mutationFn: async () => {
      const last = trail[trail.length - 1];
      if (answers[last] === "wrong") await patchFinding(pid, sid, last, { status: "open" });
      return last;
    },
    onSuccess: (last) => {
      setTrail((tr) => tr.slice(0, -1));
      setAnswers((a) => {
        const { [last]: _gone, ...rest } = a;
        void _gone;
        return rest;
      });
      setIdx(ids.indexOf(last));
      refresh();
      toast(t("Back on this one: answer again to change it", "กลับมาที่รายการนี้ ตอบใหม่เพื่อเปลี่ยนคำตอบ"));
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("Could not undo", "ย้อนกลับไม่สำเร็จ")),
  });

  const busy = answer.isPending || undo.isPending;
  const latest = useRef({ busy, done, trail: trail.length, idx });
  useEffect(() => {
    latest.current = { busy, done, trail: trail.length, idx };
  });
  const actions = useRef({ answer: (v: ReviewVerdict) => answer.mutate(v), undo: () => undo.mutate() });
  useEffect(() => {
    actions.current = { answer: (v) => answer.mutate(v), undo: () => undo.mutate() };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      const s = latest.current;
      const k = e.key.toLowerCase();
      if (k === "arrowright") setIdx((i) => Math.min(total, i + 1));
      else if (k === "arrowleft") setIdx((i) => Math.max(0, i - 1));
      else if (s.busy || s.done) return;
      else if (k === "c") actions.current.answer("correct");
      else if (k === "w") actions.current.answer("wrong");
      else if (k === "u") actions.current.answer("unsure");
      else if (k === "z" && s.trail > 0) actions.current.undo();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [total]);

  const counts = useMemo(() => {
    const c = { correct: 0, wrong: 0, unsure: 0 };
    for (const v of Object.values(answers)) c[v]++;
    return c;
  }, [answers]);

  const exit = (
    <Link href={withSel("/")} className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-grey-700 hover:bg-grey-50 md:min-h-9">
      <X className="size-4" aria-hidden />
      {t("Exit", "ออก")}
    </Link>
  );
  const shown = Math.min(idx + 1, total);

  return (
    <div role="region" aria-label={t("Review AI findings", "ตรวจข้อบกพร่องจาก AI")} className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-background">
      <header className="flex items-center gap-3 border-b bg-card px-3 py-2 md:px-6">
        {exit}
        <h1 className="min-w-0 flex-1 truncate text-base font-semibold text-brand md:text-lg">{t("Review AI findings", "ตรวจข้อบกพร่องจาก AI")}</h1>
        {total > 0 && (
          <div className="flex items-center gap-3">
            <div className="hidden h-1.5 w-40 overflow-hidden rounded-full bg-grey-100 sm:block" aria-hidden>
              <div className="h-full bg-brand transition-all" style={{ width: `${(Math.min(idx, total) / total) * 100}%` }} />
            </div>
            <span className="num text-sm font-medium" aria-live="polite" aria-label={t(`Finding ${shown} of ${total}`, `รายการที่ ${shown} จาก ${total}`)}>{shown} / {total}</span>
          </div>
        )}
      </header>

      {done || !f ? (
        <Done total={total} counts={counts} skipped={total - Object.keys(answers).length} remaining={analysis.findings.filter(isUnreviewed).length} onAgain={onAgain} withSel={withSel} />
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto grid max-w-6xl gap-4 p-3 md:p-6 lg:grid-cols-[minmax(0,1fr)_360px]">
              <section aria-label={t("Evidence", "หลักฐาน")} className="min-w-0">
                {check.isLoading ? (
                  <Skeleton className="h-72 w-full" />
                ) : check.data ? (
                  <EvidenceImages c={check.data} pid={pid} sid={sid} findingId={f.id} detectionPhoto={f.detection_photo} big />
                ) : f.photo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`/api/projects/${encodeURIComponent(pid)}/surveys/${encodeURIComponent(sid)}/findings/${encodeURIComponent(f.id)}/photo`} alt={t("Detector crop of the finding", "ภาพตัดจากตัวตรวจจับของรายการนี้")} className="max-h-[60dvh] w-full rounded-md border bg-grey-50 object-contain" />
                ) : (
                  <p className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">{t("No evidence image for this finding.", "ไม่มีภาพหลักฐานสำหรับรายการนี้")}</p>
                )}
              </section>

              <section aria-label={t("Finding", "รายการ")} className="flex min-w-0 flex-col gap-3">
                <div>
                  <p className="num text-sm text-muted-foreground">
                    {f.id}
                    {f.segment_id && ` · ${f.segment_id}`}
                    {findingChainage(f, analysis.segments) !== null && ` · ${formatChainage(findingChainage(f, analysis.segments)!)} m`}
                  </p>
                  <h2 className="mt-0.5 text-2xl font-semibold">{label(f.type)}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {f.severity && <SeverityBadge severity={f.severity} />}
                    {f.needs_review && <span className="inline-flex items-center rounded-md border border-sev-medium bg-sev-medium-bg px-2 py-0.5 text-xs font-medium text-sev-medium-fg">▲ {t("Check first", "ตรวจก่อน")}</span>}
                    {f.confidence !== undefined && <span className="num text-sm text-muted-foreground">{t("Confidence", "ความมั่นใจ")} {Math.round(f.confidence * 100)}%</span>}
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-2">
                  {f.metrics.depth_max_m !== undefined && <Tile label={f.metrics.depth_assumed ? t("Depth (assumed)", "ความลึก (สมมติ)") : t("Depth", "ความลึก")}><Num value={f.metrics.depth_max_m * 100} digits={1} unit="cm" /></Tile>}
                  {f.metrics.diameter_m !== undefined && <Tile label={t("Across", "ความกว้าง")}><Num value={f.metrics.diameter_m} digits={2} unit="m" /></Tile>}
                  {f.metrics.volume_m3 !== undefined && <Tile label={t("Missing", "ปริมาตรที่หาย")}><Num value={f.metrics.volume_m3 * 1000} digits={1} unit="L" /></Tile>}
                  {f.metrics.area_m2 !== undefined && <Tile label={t("Area", "พื้นที่")}><Num value={f.metrics.area_m2} digits={2} unit="m²" /></Tile>}
                </dl>
                {check.data && (
                  <div className="text-sm">
                    <p className="font-medium">{t("What the AI saw", "สิ่งที่ AI เห็น")}</p>
                    <p className="mt-0.5 text-muted-foreground">{verdictText(check.data, t)}</p>
                    {check.data.verdict.warnings.length > 0 && (
                      <ul className="mt-2 flex flex-col gap-1 rounded-md border border-sev-medium bg-sev-medium-bg p-2 text-xs text-sev-medium-fg">
                        {check.data.verdict.warnings.map((w, i) => <li key={i}>{warningText(w, t)}</li>)}
                      </ul>
                    )}
                  </div>
                )}
                <p className="hidden text-xs text-muted-foreground lg:block">
                  {t("Keys: C correct · W wrong · U unsure · ← → move · Z undo", "แป้นลัด: C ถูกต้อง · W ผิด · U ไม่แน่ใจ · ← → เลื่อน · Z ย้อนกลับ")}
                </p>
              </section>
            </div>
          </div>

          <footer className="border-t bg-card px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-6">
            <div className="mx-auto flex max-w-6xl flex-col gap-2 lg:flex-row lg:items-center">
              <div role="group" aria-label={t("Your call: is the AI right?", "การตัดสินของคุณ: AI ถูกหรือไม่")} className="grid flex-1 grid-cols-3 gap-2">
                {KEYS.map(({ v, key, en, th, Icon }) => (
                  <Button
                    key={v}
                    type="button"
                    disabled={busy}
                    aria-keyshortcuts={key}
                    variant={f.review?.verdict === v || answers[id] === v ? "default" : "outline"}
                    className={cn("min-h-14 text-base md:min-h-11", (f.review?.verdict === v || answers[id] === v) && "bg-brand text-white hover:bg-brand/90")}
                    onClick={() => answer.mutate(v)}
                  >
                    <Icon className="size-5" aria-hidden />
                    {t(en, th)}
                    <kbd className="ml-1 hidden rounded border px-1 text-xs font-normal opacity-70 lg:inline">{key}</kbd>
                  </Button>
                ))}
              </div>
              <div className="flex items-center justify-between gap-2 lg:justify-end">
                <Button type="button" variant="ghost" className="min-h-11 md:min-h-9" disabled={idx === 0} onClick={() => setIdx((i) => Math.max(0, i - 1))} aria-label={t("Previous", "ก่อนหน้า")}>
                  <ArrowLeft className="size-4" aria-hidden />
                </Button>
                <Button type="button" variant="ghost" className="min-h-11 md:min-h-9" disabled={busy || trail.length === 0} onClick={() => undo.mutate()} aria-keyshortcuts="Z">
                  <Undo2 className="size-4" aria-hidden />
                  {t("Undo", "ย้อนกลับ")}
                </Button>
                <Button type="button" variant="ghost" className="min-h-11 md:min-h-9" onClick={() => setIdx((i) => i + 1)}>
                  {t("Skip", "ข้าม")}
                  <ArrowRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </footer>
        </>
      )}
    </div>
  );
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold">{children}</dd>
    </div>
  );
}

function Done({ total, counts, skipped, remaining, onAgain, withSel }: { total: number; counts: { correct: number; wrong: number; unsure: number }; skipped: number; remaining: number; onAgain: () => void; withSel: ReturnType<typeof useSelection>["withSel"] }) {
  const t = useT();
  const link = "inline-flex min-h-11 items-center justify-center rounded-lg border px-4 text-sm font-semibold hover:bg-grey-50 md:min-h-9";
  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
      <CheckCircle2 className="size-10 text-sev-low-fg" aria-hidden />
      <h2 className="text-2xl font-semibold">{total === 0 ? t("Nothing to review", "ไม่มีรายการให้ตรวจ") : t("Review done", "ตรวจครบแล้ว")}</h2>
      <p className="text-sm text-muted-foreground">
        {total === 0
          ? t("Every AI finding in this survey has been reviewed by an engineer.", "วิศวกรตรวจข้อบกพร่องจาก AI ในการสำรวจนี้ครบแล้ว")
          : t("You decided these findings. The plan now reflects your calls.", "คุณตัดสินรายการเหล่านี้แล้ว แผนซ่อมสะท้อนผลที่คุณเลือก")}
      </p>
      {total > 0 && (
        <dl className="grid w-full grid-cols-2 gap-2 sm:grid-cols-4">
          <Tile label={t("Confirmed", "ยืนยันแล้ว")}><span className="num">{counts.correct}</span></Tile>
          <Tile label={t("Rejected", "ปฏิเสธ")}><span className="num">{counts.wrong}</span></Tile>
          <Tile label={t("Unsure", "ไม่แน่ใจ")}><span className="num">{counts.unsure}</span></Tile>
          <Tile label={t("Skipped", "ข้าม")}><span className="num">{skipped}</span></Tile>
        </dl>
      )}
      {counts.wrong > 0 && <p className="text-xs text-muted-foreground">{t("Rejected findings were removed from the plan.", "รายการที่ปฏิเสธถูกนำออกจากแผนแล้ว")}</p>}
      <div className="flex flex-wrap justify-center gap-2">
        {remaining > 0 && (
          <Button type="button" className="min-h-11 bg-brand text-white hover:bg-brand/90 md:min-h-9" onClick={onAgain}>
            {t(`Review the ${remaining} left`, `ตรวจอีก ${remaining} รายการ`)}
          </Button>
        )}
        <Link href={withSel("/plan")} className={link}>{t("Open the repair plan", "เปิดแผนซ่อม")}</Link>
        <Link href={withSel("/findings")} className={link}>{t("Open Findings", "เปิดรายการที่พบ")}</Link>
        <Link href={withSel("/")} className={link}>{t("Overview", "ภาพรวม")}</Link>
      </div>
    </div>
  );
}

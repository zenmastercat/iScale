"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ImageOff, Navigation } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { NotFound, RetryError } from "@/components/map/retry-error";
import { Money, Num, SeverityBadge, StatusPill } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, getJobCard, patchFinding, qk } from "@/lib/api";
import { findingChainage } from "@/lib/chainage";
import { formatChainage, formatNumber } from "@/lib/format";
import { useAnalysis } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import type { JobCard } from "@/lib/types";
import { useLang } from "@/lib/i18n";
import { T, type Lang } from "./i18n";

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="num text-xl font-medium text-grey-900">{children}</div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <section className="rounded-lg border bg-card p-4">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="flex flex-col gap-2 text-sm">
        {items.map((s, i) => (
          <li key={i} className="flex gap-2"><span className="num text-muted-foreground">{i + 1}.</span>{s}</li>
        ))}
      </ul>
    </section>
  );
}

export function JobCardView({ findingId }: { findingId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { projectId, surveyId, withSel } = useSelection();
  const pid = projectId ?? "";
  const sid = surveyId ?? "";
  const { lang, setLang } = useLang();
  const [confirm, setConfirm] = useState(false);
  const t = T[lang];
  const analysis = useAnalysis();
  const q = useQuery({ queryKey: qk.jobCard(pid, sid, findingId), queryFn: () => getJobCard(pid, sid, findingId), enabled: !!pid && !!sid });
  const fixed = useMutation({
    mutationFn: () => patchFinding(pid, sid, findingId, { status: "fixed" }),
    onSuccess: () => {
      toast.success(t.fixedToast);
      setConfirm(false);
      for (const key of [qk.analysis(pid, sid), qk.priority(pid, sid), qk.workOrders(pid), qk.verification(pid), ["project", pid, "survey", sid, "plan"], qk.jobCard(pid, sid, findingId)])
        qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t.failToast),
  });

  const finding = analysis.data?.findings.find((f) => f.id === findingId);
  const chain = finding && analysis.data ? findingChainage(finding, analysis.data.segments) : null;
  const status = finding?.status ?? q.data?.status;
  const isFixed = status === "fixed" || status === "verified";

  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 404)
      return <NotFound title={t.notFound} description={`${findingId}: ${t.notFoundHint}`} href={withSel("/map")} linkLabel={t.backToMap} />;
    return <RetryError title={t.loadError} message={(q.error as Error).message} onRetry={() => q.refetch()} busy={q.isFetching} />;
  }
  const c = q.data;

  return (
    <div className="-mx-4 -mt-6 flex min-h-[calc(100dvh-4rem)] flex-col md:mx-auto md:mt-0 md:max-w-lg md:overflow-hidden md:rounded-lg md:border">
      <header className="bg-brand px-4 pt-3 pb-4 text-white">
        <div className="flex items-center justify-between">
          <button type="button" onClick={() => router.back()} aria-label={t.back} className="grid size-11 place-items-center rounded-md hover:bg-white/10">
            <ArrowLeft className="size-5" />
          </button>
          <span className="font-semibold">{t.title}</span>
          <button
            type="button"
            lang={lang === "en" ? "th" : "en"}
            onClick={() => {
              const n = lang === "en" ? "th" : "en";
              setLang(n);
            }}
            className="min-h-11 min-w-11 rounded-md border border-white/40 px-3 font-medium hover:bg-white/10"
          >
            {t.lang}
          </button>
        </div>
        <p className="num mt-2 text-sm text-white/70">
          {findingId}
          {finding?.segment_id && ` · ${finding.segment_id}`}
          {chain !== null && ` · ${formatChainage(chain)}`}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold">{c?.label ?? <Skeleton className="h-9 w-40 bg-white/20" />}</h1>
          {c && <SeverityBadge severity={c.severity} />}
          {status && status !== "open" && <StatusPill status={status} />}
        </div>
      </header>

      {!c ? (
        <div className="flex flex-col gap-3 p-4"><Skeleton className="h-10 w-full" /><Skeleton className="h-48 w-full" /><Skeleton className="h-24 w-full" /></div>
      ) : (
        <Tabs defaultValue="location" className="flex-1 gap-0">
          <TabsList variant="line" className="h-12 w-full rounded-none border-b bg-card p-0">
            {(["location", "materials", "timing", "steps"] as const).map((k) => (
              <TabsTrigger key={k} value={k} className="min-h-11">{t[k]}</TabsTrigger>
            ))}
          </TabsList>
          <div className="bg-grey-50 p-4 pb-40 md:pb-24">
            <TabsContent value="location" className="flex flex-col gap-3">
              <Location c={c} t={t} evidenceTh={finding?.evidence_th} />
            </TabsContent>
            <TabsContent value="materials" className="flex flex-col gap-3">
              <Materials c={c} t={t} />
            </TabsContent>
            <TabsContent value="timing" className="flex flex-col gap-3">
              <Timing c={c} t={t} />
            </TabsContent>
            <TabsContent value="steps" className="flex flex-col gap-3">
              <List title={t.stepsList} items={c.plan.steps} />
              <List title={t.materialsList} items={c.plan.materials} />
            </TabsContent>
          </div>
        </Tabs>
      )}

      <div className="fixed inset-x-0 bottom-14 z-30 flex gap-3 border-t bg-card p-3 md:sticky md:bottom-0">
        <Button
          variant="outline"
          className="min-h-12 flex-1 text-base"
          disabled={!c}
          nativeButton={false}
          render={<a href={c?.location.nav_url ?? "#"} target="_blank" rel="noreferrer" />}
        >
          <Navigation className="size-4" aria-hidden />{t.navigate}
        </Button>
        <Button
          className="min-h-12 flex-1 bg-brand text-base text-white hover:bg-brand/90"
          disabled={!c || isFixed || fixed.isPending || !c.severity}
          onClick={() => setConfirm(true)}
        >
          {isFixed ? <><Check className="size-4" aria-hidden />{t.fixed}</> : fixed.isPending ? t.saving : t.markFixed}
        </Button>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.confirmTitle}</DialogTitle>
            <DialogDescription>{t.confirmBody}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="min-h-11" onClick={() => setConfirm(false)}>{t.cancel}</Button>
            <Button className="min-h-11 bg-brand text-white hover:bg-brand/90" disabled={fixed.isPending} onClick={() => fixed.mutate()}>
              {fixed.isPending ? t.saving : t.markFixed}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Location({ c, t, evidenceTh }: { c: JobCard; t: (typeof T)[Lang]; evidenceTh?: string }) {
  const { lang } = useLang();
  const evidence = lang === "th" && evidenceTh ? evidenceTh : c.location.evidence;
  const L = c.location;
  const tiles = L.tiles.filter((x) => x.value !== null);
  const label: Record<string, string> = { depth_max_m: t.depth, diameter_m: t.across, volume_m3: t.missing, area_m2: t.area, depth_assumed_cm: t.depthAssumed, volume_est_l: t.volumeEst };
  return (
    <>
      {L.photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={L.photo.url} alt={`${c.label}`} className="w-full rounded-lg border" />
      ) : (
        <div className="grid h-40 place-items-center rounded-lg border border-dashed bg-grey-100 text-sm text-muted-foreground">
          <span className="flex items-center gap-2"><ImageOff className="size-4" aria-hidden />{t.photo}</span>
        </div>
      )}
      <div className="rounded-lg border bg-card p-4">
        <div className="font-semibold">{L.address?.line1 || L.address?.full || L.road_name || t.noAddress}</div>
        {L.address?.line2 && <div className="text-sm text-muted-foreground">{L.address.line2}</div>}
        <div className="num mt-1 text-muted-foreground">{formatNumber(L.lat, 5)}, {formatNumber(L.lon, 5)}</div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {tiles.map((x) => (
          <Tile key={x.key} label={label[x.key] ?? x.label}>
            {x.key === "depth_max_m" ? <Num value={x.value * 100} digits={1} unit="cm" /> : x.key === "volume_m3" ? <Num value={x.value * 1000} digits={1} unit="L" /> : <Num value={x.value} digits={x.unit === "cm" || x.unit === "L" ? 1 : 2} unit={x.unit} />}
          </Tile>
        ))}
      </div>
      <p className="text-sm">{evidence}</p>
    </>
  );
}

function Materials({ c, t }: { c: JobCard; t: (typeof T)[Lang] }) {
  const k = c.cost;
  if (!k.available) return <p className="text-sm text-muted-foreground">{t.noCost}</p>;
  return (
    <>
      <div className="rounded-lg border bg-card p-4">
        <div className="text-sm text-muted-foreground">{t.method}</div>
        <div className="font-semibold">{k.method_label}</div>
        <div className="num mt-1 text-sm text-muted-foreground">
          {formatNumber(k.cut_w_m, 2)} × {formatNumber(k.cut_l_m, 2)} m · {formatNumber(k.layers)} {k.layers === 1 ? t.layer : t.layers}
        </div>
      </div>
      <section className="rounded-lg border bg-card">
        <h3 className="border-b px-4 py-3 font-semibold">{t.bill}</h3>
        <ul>
          {k.lines.map((l) => (
            <li key={l.key} className="flex items-start justify-between gap-3 border-b px-4 py-3 last:border-b-0">
              <div className="min-w-0">
                <div className="text-sm font-medium">{t === T.th ? l.label_th || l.label : l.label}</div>
                <div className="num text-xs text-muted-foreground">{formatNumber(l.qty, 2)} {l.unit} × {formatNumber(l.unit_price, 2)}</div>
              </div>
              <Money amount={l.amount} style="symbol" symbol={k.symbol} className="shrink-0 text-sm" />
            </li>
          ))}
        </ul>
        <div className="flex items-baseline justify-between border-t bg-grey-50 px-4 py-3">
          <span className="font-semibold">{t.total}</span>
          <Money amount={k.materials_cost} style="symbol" symbol={k.symbol} className="text-xl font-semibold text-brand" />
        </div>
      </section>
      <p className="text-sm text-muted-foreground">{t.materialsOnly}</p>
      {k.tools.length > 0 && <List title={t.tools} items={k.tools} />}
    </>
  );
}

function Timing({ c, t }: { c: JobCard; t: (typeof T)[Lang] }) {
  const m = c.timing;
  return (
    <>
      <Tile label={t.window}><span className="num">{m.window}</span></Tile>
      <div className="rounded-lg border bg-card p-4 text-sm">
        <div className="font-semibold">{t.traffic}: <span className="capitalize">{t.levels[m.level.toLowerCase()] ?? m.level}</span>{m.days && ` · ${m.days}`}</div>
        <p className="mt-1 text-muted-foreground">{m.reason}</p>
        {m.road_name && <p className="mt-2">{m.road_name}{m.road_class && ` (${m.road_class})`}</p>}
      </div>
      {c.plan.warning && (
        <div className="rounded-lg border border-sev-medium bg-sev-medium-bg p-4 text-sm text-sev-medium-fg">
          <span className="font-semibold">{t.warning}: </span>{c.plan.warning}
        </div>
      )}
      <div className="rounded-lg border bg-card p-4 text-sm"><span className="font-semibold">{t.urgency}: </span>{c.plan.urgency}</div>
    </>
  );
}

"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Layers, Table2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { RetryError } from "@/components/map/retry-error";
import { FilterBar, type Option } from "@/components/findings/filter-bar";
import { FindingsTable, isSelectable } from "@/components/findings/findings-table";
import { buildRows, filterAndSort, groupRows, toCsv } from "@/components/findings/rows";
import { EmptyState, Money, PageHeader, SurveyGate } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, createWorkOrder, qk } from "@/lib/api";
import { findingsQuery, parseFindingsFilter, type FindingsFilter } from "@/lib/findings-filter";
import { useWords } from "@/components/map/words";
import { useT } from "@/lib/i18n";
import { useAnalysis, useCatalogLabel, usePriority } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

const STATUSES = ["open", "planned", "fixed", "verified", "not_fixed", "dismissed"] as const;

function FindingsBody() {
  const t = useT();
  const words = useWords();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const { withSel, survey, projectId, surveyId } = useSelection();
  const analysis = useAnalysis();
  const priority = usePriority();
  const labelFor = useCatalogLabel();
  const filter = useMemo(() => parseFindingsFilter(new URLSearchParams(params.toString())), [params]);
  const setFilter = (f: FindingsFilter) => router.replace(withSel("/findings", findingsQuery(f)), { scroll: false });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focusId, setFocusId] = useState<string | null>(null);
  const [group, setGroup] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);

  const all = useMemo(() => {
    if (!analysis.data) return [];
    const rank = new Map((priority.data?.items ?? []).map((i) => [i.id, { rank: i.rank, cost: i.cost }]));
    return buildRows(analysis.data.findings, analysis.data.segments, labelFor, rank);
  }, [analysis.data, priority.data, labelFor]);
  const rows = useMemo(() => filterAndSort(all, filter), [all, filter]);
  const segments = analysis.data?.segments;

  // rows in the order they are drawn (grouped order, collapsed groups skipped)
  const visible = useMemo(
    () => (group && segments ? groupRows(rows, segments).flatMap((g) => (collapsed.has(g.id) ? [] : g.list)) : rows),
    [group, rows, segments, collapsed],
  );

  // selection counts only rows that are still open defects
  const chosen = useMemo(() => all.filter((r) => isSelectable(r) && selected.has(r.f.id)), [all, selected]);
  const planTotal = chosen.reduce((a, r) => a + (r.planCost ?? 0), 0);

  const latest = useRef({ visible, focusId, router, withSel });
  useEffect(() => {
    latest.current = { visible, focusId, router, withSel };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (typing) return;
      const { visible: v, focusId: fid, router: r, withSel: w } = latest.current;
      const i = v.findIndex((x) => x.f.id === fid);
      if (e.key === "/") {
        e.preventDefault();
        document.getElementById("findings-search")?.focus();
      } else if (e.key === "j" || e.key === "k") {
        if (!v.length) return;
        const n = e.key === "j" ? Math.min(v.length - 1, i + 1) : Math.max(0, i < 0 ? 0 : i - 1);
        setFocusId(v[n].f.id);
      } else if (e.key === "Enter" && fid && !["A", "BUTTON", "SUMMARY"].includes(el?.tagName ?? "")) {
        r.push(w("/map", { finding: fid }));
      } else if (e.key === "x" && fid) {
        const row = v[i];
        if (row && isSelectable(row)) setSelected((s) => {
          const n = new Set(s);
          if (n.has(fid)) n.delete(fid);
          else n.add(fid);
          return n;
        });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const create = async () => {
    if (!projectId || !surveyId || !chosen.length) return;
    setCreating(true);
    try {
      const wo = await createWorkOrder(projectId, {
        survey_id: surveyId,
        finding_ids: chosen.map((r) => r.f.id),
        title: `${survey?.name ?? "Survey"} · ${chosen.length}`,
      });
      for (const key of [qk.workOrders(projectId), qk.analysis(projectId, surveyId), qk.priority(projectId, surveyId), qk.verification(projectId), ["project", projectId, "survey", surveyId, "plan"]]) qc.invalidateQueries({ queryKey: key });
      setSelected(new Set());
      toast.success(t(`Work order ${wo.id} created with ${chosen.length} findings`, `สร้างใบสั่งงาน ${wo.id} จำนวน ${chosen.length} รายการแล้ว`), {
        action: { label: t("Open Verification", "เปิดการตรวจสอบ"), onClick: () => router.push(withSel("/verification")) },
      });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : t("Could not create the work order", "สร้างใบสั่งงานไม่สำเร็จ"));
    } finally {
      setCreating(false);
    }
  };

  if (analysis.isError) return <RetryError title={t("Could not load the findings", "โหลดรายการไม่สำเร็จ")} message={analysis.error.message} onRetry={() => analysis.refetch()} busy={analysis.isFetching} />;
  if (analysis.data && analysis.data.findings.length === 0)
    return <EmptyState icon={Table2} title={t("No findings in this survey", "ไม่มีรายการที่พบในการสำรวจนี้")} description={t("The survey found no defects or assets. Nothing to list.", "การสำรวจไม่พบข้อบกพร่องหรือสินทรัพย์ จึงไม่มีรายการ")} />;
  if (!analysis.data) return <Skeleton className="h-96 w-full" />;

  const types: Option[] = [...new Set(all.map((r) => r.f.type))].map((ty) => ({ value: ty, label: labelFor(ty) })).sort((a, b) => a.label.localeCompare(b.label));
  const segmentOpts: Option[] = analysis.data.segments.map((s) => ({ value: s.id, label: s.id }));
  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `findings-${survey?.id ?? "survey"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleAll = (checked: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      for (const r of rows.filter(isSelectable)) {
        if (checked) n.add(r.f.id);
        else n.delete(r.f.id);
      }
      return n;
    });

  return (
    <div className="flex flex-col gap-4">
      <FilterBar
        filter={filter}
        setFilter={setFilter}
        kinds={[{ value: "defect", label: t("Defects", "ข้อบกพร่อง") }, { value: "asset", label: t("Assets", "สินทรัพย์") }]}
        severities={(["high", "medium", "low"] as const).map((s) => ({ value: s, label: t(s[0].toUpperCase() + s.slice(1), { high: "สูง", medium: "กลาง", low: "ต่ำ" }[s]) }))}
        statuses={STATUSES.map((s) => ({ value: s, label: words.status(s) }))}
        types={types}
        segments={segmentOpts}
        shown={rows.length}
        total={all.length}
        onExport={download}
        canExport={rows.length > 0}
      />
      <div className="hidden md:block">
        <Button type="button" variant={group ? "default" : "outline"} aria-pressed={group} className={group ? "min-h-8 bg-brand text-white hover:bg-brand/90" : "min-h-8"} onClick={() => setGroup((g) => !g)}>
          <Layers className="size-4" aria-hidden />
          {t("Group by segment", "จัดกลุ่มตามช่วง")}
        </Button>
      </div>
      {rows.length === 0 ? (
        <EmptyState icon={Table2} title={t("No findings match", "ไม่พบรายการที่ตรงกัน")} description={t("Change or clear the filters to see more.", "ปรับหรือล้างตัวกรองเพื่อดูเพิ่ม")} />
      ) : (
        <FindingsTable
          rows={rows}
          filter={filter}
          setFilter={setFilter}
          segments={analysis.data.segments}
          selected={selected}
          onToggle={toggle}
          onToggleAll={toggleAll}
          focusId={focusId}
          groupBySegment={group}
          collapsed={collapsed}
          onCollapse={(id) => setCollapsed((c) => {
            const n = new Set(c);
            if (n.has(id)) n.delete(id);
            else n.add(id);
            return n;
          })}
        />
      )}
      <p className="hidden text-xs text-muted-foreground md:block">
        {t("Keys: / search · j k move · Enter open · x select", "แป้นลัด: / ค้นหา · j k เลื่อน · Enter เปิด · x เลือก")}
      </p>
      {chosen.length > 0 && (
        <div role="region" aria-label={t("Selected findings", "รายการที่เลือก")} className="sticky bottom-0 z-20 hidden items-center gap-4 rounded-lg border bg-card p-3 md:flex">
          <span className="text-sm">
            <span className="num font-semibold">{chosen.length}</span> {t("selected", "รายการที่เลือก")}
          </span>
          <span className="text-sm text-muted-foreground">
            {t("Plan cost", "ค่าซ่อม")} <Money amount={planTotal} className="font-semibold text-grey-900" /> <span className="text-xs">({t("excl. mobilisation", "ไม่รวมค่าเคลื่อนย้าย")})</span>
          </span>
          <Button type="button" variant="ghost" className="min-h-8" onClick={() => setSelected(new Set())}>{t("Clear", "ล้าง")}</Button>
          <Button type="button" className="ml-auto min-h-8 bg-brand text-white hover:bg-brand/90" disabled={creating} onClick={create}>
            {creating ? t("Creating…", "กำลังสร้าง…") : t("Create work order", "สร้างใบสั่งงาน")}
          </Button>
        </div>
      )}
    </div>
  );
}

export default function FindingsPage() {
  const t = useT();
  const { project, survey } = useSelection();
  return (
    <>
      <PageHeader title={t("Findings", "รายการที่พบ")} crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} />
      <SurveyGate>
        <FindingsBody />
      </SurveyGate>
    </>
  );
}

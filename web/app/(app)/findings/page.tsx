"use client";
import { Table2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { FilterBar, type Option } from "@/components/findings/filter-bar";
import { FindingsTable } from "@/components/findings/findings-table";
import { buildRows, filterAndSort, toCsv } from "@/components/findings/rows";
import { EmptyState, PageHeader, statusLabel, SurveyGate } from "@/components/shared";
import { Skeleton } from "@/components/ui/skeleton";
import { findingsQuery, parseFindingsFilter, type FindingsFilter } from "@/lib/findings-filter";
import { useAnalysis, useCatalogLabel, usePriority } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

const STATUSES = ["open", "planned", "fixed", "verified", "not_fixed", "dismissed"] as const;

function FindingsBody() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const { withSel, survey } = useSelection();
  const analysis = useAnalysis();
  const priority = usePriority();
  const labelFor = useCatalogLabel();
  const filter = useMemo(() => parseFindingsFilter(new URLSearchParams(params.toString())), [params]);
  const setFilter = (f: FindingsFilter) => router.replace(withSel("/findings", findingsQuery(f)), { scroll: false });

  const all = useMemo(() => {
    if (!analysis.data) return [];
    const rank = new Map((priority.data?.items ?? []).map((i) => [i.id, i.rank]));
    return buildRows(analysis.data.findings, analysis.data.segments, labelFor, rank);
  }, [analysis.data, priority.data, labelFor]);
  const rows = useMemo(() => filterAndSort(all, filter), [all, filter]);

  if (analysis.isError) return <p role="alert" className="text-sev-high-fg">{t("Could not load the findings", "โหลดรายการไม่สำเร็จ")}: {analysis.error.message}</p>;
  if (!analysis.data) return <Skeleton className="h-96 w-full" />;

  const types: Option[] = [...new Set(all.map((r) => r.f.type))].map((t) => ({ value: t, label: labelFor(t) })).sort((a, b) => a.label.localeCompare(b.label));
  const segments: Option[] = analysis.data.segments.map((s) => ({ value: s.id, label: s.id }));
  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `findings-${survey?.id ?? "survey"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-4">
      <FilterBar
        filter={filter}
        setFilter={setFilter}
        kinds={[{ value: "defect", label: t("Defects", "ข้อบกพร่อง") }, { value: "asset", label: t("Assets", "สินทรัพย์") }]}
        severities={(["high", "medium", "low"] as const).map((s) => ({ value: s, label: t(s[0].toUpperCase() + s.slice(1), { high: "สูง", medium: "กลาง", low: "ต่ำ" }[s]) }))}
        statuses={STATUSES.map((s) => ({ value: s, label: statusLabel(s) }))}
        types={types}
        segments={segments}
        shown={rows.length}
        total={all.length}
        onExport={download}
        canExport={rows.length > 0}
      />
      {rows.length === 0 ? (
        <EmptyState icon={Table2} title={t("No findings match", "ไม่พบรายการที่ตรงกัน")} description={t("Change or clear the filters to see more.", "ปรับหรือล้างตัวกรองเพื่อดูเพิ่ม")} />
      ) : (
        <FindingsTable rows={rows} filter={filter} setFilter={setFilter} />
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

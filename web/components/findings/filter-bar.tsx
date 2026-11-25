"use client";
import { ChevronDown, Download, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";
import { findingsQuery, type FindingsFilter } from "@/lib/findings-filter";
import { cn } from "@/lib/utils";

export interface Option { value: string; label: string }

/** A button that opens a checklist; each checkbox toggles one value. Native <details> keeps it keyboard-friendly. */
function Multi({ label, options, selected, onChange }: { label: string; options: Option[]; selected: string[]; onChange: (v: string[]) => void }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false;
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <details ref={ref} className="relative">
      <summary className={cn("flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-lg border bg-card px-3 text-sm font-medium md:min-h-8 md:px-2.5", selected.length && "border-brand")}>
        {label}
        {selected.length > 0 && <span className="num rounded bg-brand px-1.5 text-xs text-white">{selected.length}</span>}
        <ChevronDown className="size-3.5" aria-hidden />
      </summary>
      <fieldset className="absolute z-20 mt-1 max-h-72 min-w-44 overflow-y-auto rounded-lg border bg-popover p-1">
        <legend className="sr-only">{label}</legend>
        {options.map((o) => (
          <label key={o.value} className="flex min-h-11 cursor-pointer items-center gap-2 rounded px-2 text-sm hover:bg-grey-50 md:min-h-8">
            <input
              type="checkbox"
              className="size-4"
              checked={selected.includes(o.value)}
              onChange={(e) => onChange(e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value))}
            />
            {o.label}
          </label>
        ))}
      </fieldset>
    </details>
  );
}

export function FilterBar({
  filter, setFilter, kinds, severities, statuses, types, segments, shown, total, onExport, canExport,
}: {
  filter: FindingsFilter;
  setFilter: (f: FindingsFilter) => void;
  kinds: Option[]; severities: Option[]; statuses: Option[]; types: Option[]; segments: Option[];
  shown: number; total: number; onExport: () => void; canExport: boolean;
}) {
  const t = useT();
  const [q, setQ] = useState(filter.q ?? "");
  const [typing, setTyping] = useState(false);
  const [urlQ, setUrlQ] = useState(filter.q);
  // follow the URL when it changes underneath us (back/forward, Clear filters, deep link),
  // but never while the user is mid-typing
  if (filter.q !== urlQ) {
    setUrlQ(filter.q);
    if (!typing) setQ(filter.q ?? "");
  }
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latest = useRef(filter);
  useEffect(() => {
    latest.current = filter;
  }, [filter]);
  // a pending search must not fire after the page is left
  useEffect(() => () => clearTimeout(timer.current), []);
  const onQ = (v: string) => {
    setQ(v);
    setTyping(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setTyping(false);
      setFilter({ ...latest.current, q: v.trim() || undefined });
    }, 250);
  };
  const active = Object.keys(findingsQuery({ ...filter, sort: undefined })).length > 0;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label={t("Kind", "ชนิด")} className="flex gap-1">
          {kinds.map((k) => (
            <Button
              key={k.value}
              type="button"
              variant={filter.kind === k.value ? "default" : "outline"}
              aria-pressed={filter.kind === k.value}
              className={cn("min-h-11 md:min-h-8", filter.kind === k.value && "bg-brand text-white hover:bg-brand/90")}
              onClick={() => setFilter({ ...filter, kind: filter.kind === k.value ? undefined : (k.value as "defect" | "asset") })}
            >
              {k.label}
            </Button>
          ))}
        </div>
        <Multi label={t("Severity", "ความรุนแรง")} options={severities} selected={filter.severity ?? []} onChange={(v) => setFilter({ ...filter, severity: v.length ? (v as never) : undefined })} />
        <Multi label={t("Status", "สถานะ")} options={statuses} selected={filter.status ?? []} onChange={(v) => setFilter({ ...filter, status: v.length ? (v as never) : undefined })} />
        <Multi label={t("Type", "ประเภท")} options={types} selected={filter.type ?? []} onChange={(v) => setFilter({ ...filter, type: v.length ? v : undefined })} />
        <Multi label={t("Segment", "ช่วง")} options={segments} selected={filter.segment ?? []} onChange={(v) => setFilter({ ...filter, segment: v.length ? v : undefined })} />
        <label className="relative min-w-48 flex-1 md:max-w-xs">
          <span className="sr-only">{t("Search findings", "ค้นหารายการ")}</span>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            id="findings-search"
            type="search"
            value={q}
            onChange={(e) => onQ(e.target.value)}
            placeholder={t("Search id, type, evidence", "ค้นหารหัส ประเภท หลักฐาน")}
            className="min-h-11 w-full rounded-lg border bg-card pr-3 pl-8 text-sm md:min-h-8"
          />
        </label>
        {active && (
          <Button type="button" variant="ghost" className="min-h-11 md:min-h-8" onClick={() => { setQ(""); setFilter({ sort: filter.sort }); }}>
            {t("Clear filters", "ล้างตัวกรอง")}
          </Button>
        )}
        <Button type="button" variant="outline" className="min-h-11 md:ml-auto md:min-h-8" disabled={!canExport} onClick={onExport}>
          <Download className="size-4" aria-hidden />{t("Export CSV", "ส่งออก CSV")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground" role="status">
        <span className="num">{shown}</span> {t("of", "จาก")} <span className="num">{total}</span> {t("findings", "รายการ")}
      </p>
    </div>
  );
}

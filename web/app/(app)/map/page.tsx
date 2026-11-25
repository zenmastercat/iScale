"use client";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { PanelRight } from "lucide-react";
import { FindingDrawer } from "@/components/map/finding-drawer";
import { DefectList, type Bounds } from "@/components/map/defect-list";
import { MapLegend } from "@/components/map/legend";
import { MapView, type Layers } from "@/components/map/map-view";
import { COLOUR_KEYS, METRICS, parseColour } from "@/components/map/metrics";
import { PageHeader, SurveyGate } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalysis, useCatalogLabel, useMeta, usePriority } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

const TOGGLES: { key: keyof Layers; en: string; th: string }[] = [
  { key: "condition", en: "Condition", th: "สภาพถนน" },
  { key: "defects", en: "Defects", th: "ข้อบกพร่อง" },
  { key: "assets", en: "Assets", th: "สินทรัพย์" },
];

function MapBody({ layers }: { layers: Layers }) {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const { withSel } = useSelection();
  const analysis = useAnalysis();
  const meta = useMeta();
  const priority = usePriority();
  const [listOpen, setListOpen] = useState(true);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [onlyInView, setOnlyInView] = useState(false);
  const rank = useMemo(() => new Map((priority.data?.items ?? []).map((i) => [i.id, i.rank])), [priority.data]);
  const labelFor = useCatalogLabel();
  const findingId = params.get("finding");
  const segmentId = params.get("segment");
  const colourBy = parseColour(params.get("colour"));
  const keep: Record<string, string> = colourBy === "condition" ? {} : { colour: colourBy };
  const setColour = (c: string) => {
    const q = new URLSearchParams(params.toString());
    if (c === "condition") q.delete("colour");
    else q.set("colour", c);
    router.replace(`/map?${q.toString()}`, { scroll: false });
  };
  const assetCodes = useMemo(() => new Set((meta.data?.catalog ?? []).filter((c) => c.kind === "asset").map((c) => c.code)), [meta.data]);

  if (analysis.isError) return <p role="alert" className="text-sev-high-fg">{t("Could not load the analysis", "โหลดผลวิเคราะห์ไม่สำเร็จ")}: {analysis.error.message}</p>;
  if (!analysis.data) return <Skeleton className="h-[60dvh] w-full" />;
  const an = analysis.data;
  const empty = !an.segments.length && !an.findings.length;

  return (
    <div className="lg:flex lg:items-start lg:gap-3">
      <div className="min-w-0 rounded-lg border bg-card p-3 lg:flex-1">
        <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label={t("Colour by", "ระบายสีตาม")}>
          <span className="text-sm font-medium">{t("Colour by", "ระบายสีตาม")}</span>
          {COLOUR_KEYS.map((k) => (
            <Button
              key={k}
              type="button"
              aria-pressed={colourBy === k}
              variant={colourBy === k ? "default" : "outline"}
              className={colourBy === k ? "min-h-11 bg-brand text-white hover:bg-brand/90 md:min-h-8" : "min-h-11 md:min-h-8"}
              onClick={() => setColour(k)}
            >
              {k === "condition" ? t("Condition", "สภาพถนน") : t(METRICS[k].en, METRICS[k].th)}
            </Button>
          ))}
          <Button type="button" variant="outline" aria-expanded={listOpen} className="ml-auto hidden min-h-8 lg:inline-flex" onClick={() => setListOpen((o) => !o)}>
            <PanelRight className="size-4" aria-hidden />
            {listOpen ? t("Hide list", "ซ่อนรายการ") : t("Show list", "แสดงรายการ")}
          </Button>
        </div>
        <div className="h-[calc(100dvh-20rem)] min-h-[360px] overflow-hidden rounded-md bg-grey-50">
          {empty ? (
            <p className="grid h-full place-items-center text-muted-foreground">{t("This survey has no segments or findings to show.", "การสำรวจนี้ไม่มีช่วงถนนหรือรายการให้แสดง")}</p>
          ) : (
            <MapView
              analysis={an}
              layers={layers}
              selectedId={findingId}
              segmentId={segmentId}
              colourBy={colourBy}
              hoverId={hoverId}
              onViewChange={setBounds}
              assetCodes={assetCodes}
              labelFor={labelFor}
              onSelect={(id) => router.push(withSel("/map", { finding: id, ...keep }), { scroll: false })}
            />
          )}
        </div>
        <MapLegend showCondition={layers.condition} showDefects={layers.defects} colourBy={colourBy} segments={an.segments} />
      </div>
      {listOpen && !empty && (
        <aside aria-label={t("Defect list", "รายการข้อบกพร่อง")} className="mt-3 hidden h-[calc(100dvh-14rem)] min-h-[420px] w-80 shrink-0 overflow-hidden rounded-lg border bg-card lg:mt-0 lg:block">
          <DefectList
            findings={an.findings}
            rank={rank}
            labelFor={labelFor}
            selectedId={findingId}
            bounds={bounds}
            onlyInView={onlyInView}
            onOnlyInView={setOnlyInView}
            onHover={setHoverId}
            onSelect={(id) => router.push(withSel("/map", { finding: id, ...keep }), { scroll: false })}
          />
        </aside>
      )}
      <FindingDrawer findingId={findingId} onClose={() => router.replace(withSel("/map", keep), { scroll: false })} />
    </div>
  );
}

export default function MapPage() {
  const t = useT();
  const { project, survey } = useSelection();
  const [layers, setLayers] = useState<Layers>({ condition: true, defects: true, assets: false });
  const actions = (
    <div className="flex gap-2" role="group" aria-label={t("Map layers", "ชั้นแผนที่")}>
      {TOGGLES.map((x) => (
        <Button
          key={x.key}
          type="button"
          aria-pressed={layers[x.key]}
          variant={layers[x.key] ? "default" : "outline"}
          className={layers[x.key] ? "min-h-11 bg-brand text-white hover:bg-brand/90" : "min-h-11"}
          onClick={() => setLayers((l) => ({ ...l, [x.key]: !l[x.key] }))}
        >
          {t(x.en, x.th)}
        </Button>
      ))}
    </div>
  );
  return (
    <>
      <PageHeader title={t("Map", "แผนที่")} crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} actions={actions} />
      <SurveyGate>
        <MapBody layers={layers} />
      </SurveyGate>
    </>
  );
}

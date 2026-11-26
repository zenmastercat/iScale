"use client";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { PanelRight, SlidersHorizontal } from "lucide-react";
import { FindingDrawer } from "@/components/map/finding-drawer";
import { DefectList, type Bounds } from "@/components/map/defect-list";
import { RetryError } from "@/components/map/retry-error";
import { MapLegend } from "@/components/map/legend";
import { MapView, type Layers } from "@/components/map/map-view";
import { COLOUR_KEYS, METRICS, parseColour } from "@/components/map/metrics";
import { SurveyGate } from "@/components/shared";
import { useMediaQuery } from "@/components/map/use-media";
import { MapSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { useAnalysis, useCatalogLabel, useMeta, usePriority } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

const TOGGLES: { key: keyof Layers; en: string; th: string }[] = [
  { key: "condition", en: "Condition", th: "สภาพถนน" },
  { key: "defects", en: "Defects", th: "ข้อบกพร่อง" },
  { key: "assets", en: "Assets", th: "สินทรัพย์" },
];

function MapBody({ layers, setLayers }: { layers: Layers; setLayers: React.Dispatch<React.SetStateAction<Layers>> }) {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const { withSel } = useSelection();
  const analysis = useAnalysis();
  const meta = useMeta();
  const priority = usePriority();
  const { project, survey } = useSelection();
  const wide = useMediaQuery("(min-width: 768px)");
  const [ctl, setCtl] = useState<boolean | null>(null);
  const ctlOpen = ctl ?? wide; // open by default on a tablet or desktop, folded on a phone
  const setCtlOpen = (v: boolean) => setCtl(v);
  useEffect(() => {
    document.title = `${t("Map", "แผนที่")} · iScale`;
  }, [t]);
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

  if (analysis.isError) return <RetryError title={t("Could not load the analysis", "โหลดผลวิเคราะห์ไม่สำเร็จ")} message={analysis.error.message} onRetry={() => analysis.refetch()} busy={analysis.isFetching} />;
  if (!analysis.data) return <MapSkeleton />;
  const an = analysis.data;
  const empty = !an.segments.length && !an.findings.length;
  const noDefects = !empty && !an.findings.some((f) => f.severity);

  const toggles = (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("Map layers", "ชั้นแผนที่")}>
      {TOGGLES.map((x) => (
        <Button
          key={x.key}
          type="button"
          aria-pressed={layers[x.key]}
          variant={layers[x.key] ? "default" : "outline"}
          className={layers[x.key] ? "min-h-11 bg-brand text-white hover:bg-brand/90 md:min-h-8" : "min-h-11 md:min-h-8"}
          onClick={() => setLayers((l) => ({ ...l, [x.key]: !l[x.key] }))}
        >
          {t(x.en, x.th)}
        </Button>
      ))}
    </div>
  );

  return (
    // full bleed: cancel the page padding, then fill the space between the top bar and the phone tab bar
    <div className="-mx-4 -mt-6 -mb-24 flex h-[max(26rem,calc(100dvh-7rem-3.5rem-env(safe-area-inset-bottom)))] md:-mx-8 md:-mb-10 md:h-[calc(100dvh-3.6rem)]">
      <div className="relative min-w-0 flex-1 bg-grey-50">
        {empty ? (
          <p className="grid h-full place-items-center px-6 text-center text-muted-foreground">{t("This survey has no segments or findings to show.", "การสำรวจนี้ไม่มีช่วงถนนหรือรายการให้แสดง")}</p>
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

        <div className="pointer-events-none absolute top-3 left-3 z-10 flex max-h-[calc(100%-1.5rem)] max-w-[calc(100%-5rem)] flex-col items-start gap-2 md:max-w-sm">
          <div className="pointer-events-auto flex flex-col gap-2 rounded-lg border bg-card/95 p-2 backdrop-blur-sm">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold text-brand">{t("Map", "แผนที่")}</h1>
              {project && survey && <span className="min-w-0 truncate text-xs text-muted-foreground">{project.name} / {survey.name}</span>}
              <Button type="button" variant="ghost" size="icon" className="ml-auto min-h-11 md:min-h-8" aria-expanded={ctlOpen} aria-controls="map-controls" aria-label={t("Map options", "ตัวเลือกแผนที่")} onClick={() => setCtlOpen(!ctlOpen)}>
                <SlidersHorizontal className="size-4" aria-hidden />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="hidden min-h-8 lg:inline-flex" aria-expanded={listOpen} aria-label={listOpen ? t("Hide list", "ซ่อนรายการ") : t("Show list", "แสดงรายการ")} onClick={() => setListOpen((o) => !o)}>
                <PanelRight className="size-4" aria-hidden />
              </Button>
            </div>
            {ctlOpen && (
              <div id="map-controls" className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("Colour by", "ระบายสีตาม")}>
                  <span className="text-xs font-medium">{t("Colour by", "ระบายสีตาม")}</span>
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
                </div>
                {toggles}
              </div>
            )}
          </div>
          {noDefects && (
            <p role="status" className="pointer-events-auto rounded-md border bg-card/95 px-3 py-2 text-xs text-muted-foreground md:text-sm">
              {t("No defects were found in this survey. The road is shown by condition only.", "ไม่พบข้อบกพร่องในการสำรวจนี้ แสดงเฉพาะสภาพถนน")}
            </p>
          )}
        </div>

        {!empty && (
          <div className="pointer-events-auto absolute bottom-7 left-3 z-10 max-w-[calc(100%-1.5rem)] rounded-lg border bg-card/95 px-3 py-2 backdrop-blur-sm md:max-w-[min(32rem,calc(100%-6rem))]">
            <MapLegend showCondition={layers.condition} showDefects={layers.defects} colourBy={colourBy} segments={an.segments} />
          </div>
        )}
      </div>
      {listOpen && !empty && (
        <aside aria-label={t("Defect list", "รายการข้อบกพร่อง")} className="hidden w-[300px] shrink-0 overflow-hidden border-l bg-card lg:block">
          <DefectList
            findings={an.findings}
            segments={an.segments}
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
  const [layers, setLayers] = useState<Layers>({ condition: true, defects: true, assets: false });
  return (
    <SurveyGate>
      <MapBody layers={layers} setLayers={setLayers} />
    </SurveyGate>
  );
}

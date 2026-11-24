"use client";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { FindingDrawer } from "@/components/map/finding-drawer";
import { MapLegend } from "@/components/map/legend";
import { MapView, type Layers } from "@/components/map/map-view";
import { PageHeader, SurveyGate } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalysis, useCatalogLabel, useMeta } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

const TOGGLES: { key: keyof Layers; label: string }[] = [
  { key: "condition", label: "Condition" },
  { key: "defects", label: "Defects" },
  { key: "assets", label: "Assets" },
];

function MapBody({ layers }: { layers: Layers }) {
  const router = useRouter();
  const params = useSearchParams();
  const { withSel } = useSelection();
  const analysis = useAnalysis();
  const meta = useMeta();
  const labelFor = useCatalogLabel();
  const findingId = params.get("finding");
  const segmentId = params.get("segment");
  const assetCodes = useMemo(() => new Set((meta.data?.catalog ?? []).filter((c) => c.kind === "asset").map((c) => c.code)), [meta.data]);

  if (analysis.isError) return <p role="alert" className="text-sev-high-fg">Could not load the analysis: {analysis.error.message}</p>;
  if (!analysis.data) return <Skeleton className="h-[60dvh] w-full" />;
  const an = analysis.data;
  const empty = !an.segments.length && !an.findings.length;

  return (
    <div>
      <div className="rounded-lg border bg-card p-3">
        <div className="h-[calc(100dvh-20rem)] min-h-[360px] overflow-hidden rounded-md bg-grey-50">
          {empty ? (
            <p className="grid h-full place-items-center text-muted-foreground">This survey has no segments or findings to show.</p>
          ) : (
            <MapView
              analysis={an}
              layers={layers}
              selectedId={findingId}
              segmentId={segmentId}
              assetCodes={assetCodes}
              labelFor={labelFor}
              onSelect={(id) => router.replace(withSel("/map", { finding: id }), { scroll: false })}
            />
          )}
        </div>
        <MapLegend showCondition={layers.condition} showDefects={layers.defects} />
      </div>
      <FindingDrawer findingId={findingId} onClose={() => router.replace(withSel("/map"), { scroll: false })} />
    </div>
  );
}

export default function MapPage() {
  const { project, survey } = useSelection();
  const [layers, setLayers] = useState<Layers>({ condition: true, defects: true, assets: false });
  const actions = (
    <div className="flex gap-2" role="group" aria-label="Map layers">
      {TOGGLES.map((t) => (
        <Button
          key={t.key}
          type="button"
          aria-pressed={layers[t.key]}
          variant={layers[t.key] ? "default" : "outline"}
          className={layers[t.key] ? "min-h-11 bg-brand text-white hover:bg-brand/90" : "min-h-11"}
          onClick={() => setLayers((l) => ({ ...l, [t.key]: !l[t.key] }))}
        >
          {t.label}
        </Button>
      ))}
    </div>
  );
  return (
    <>
      <PageHeader title="Map" crumb={project && survey ? `${project.name} / ${survey.name}` : undefined} actions={actions} />
      <SurveyGate>
        <MapBody layers={layers} />
      </SurveyGate>
    </>
  );
}

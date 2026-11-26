"use client";
import { Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import MapGL, { Layer, Marker, NavigationControl, Popup, Source, type MapLayerMouseEvent, type MapRef } from "@/lib/maplibre";
import { ConditionChip, Num, SeverityIcon } from "@/components/shared";
import { bandFor } from "@/lib/condition";
import { useWords } from "./words";
import { METRICS, metricScale, type ColourBy } from "./metrics";
import { BASE_SOURCE, BASE_STYLE, PLAIN_STYLE, viaOwnServer } from "@/components/map/base-style";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Analysis, Finding } from "@/lib/types";
import { cn } from "@/lib/utils";


export interface Layers {
  condition: boolean;
  defects: boolean;
  assets: boolean;
}

function boundsOf(analysis: Analysis, segmentId: string | null): [[number, number], [number, number]] | null {
  const focus = segmentId ? analysis.segments.find((s) => s.id === segmentId) : null;
  const pts: [number, number][] = focus?.coords?.length
    ? focus.coords
    : [...analysis.segments.flatMap((s) => s.coords ?? []), ...analysis.findings.map((f) => [f.lon, f.lat] as [number, number])];
  if (!pts.length) return null;
  const lons = pts.map((p) => p[0]);
  const lats = pts.map((p) => p[1]);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}

export function MapView({
  analysis,
  layers,
  selectedId,
  segmentId,
  colourBy,
  assetCodes,
  labelFor,
  onSelect,
  hoverId = null,
  onViewChange,
}: {
  analysis: Analysis;
  layers: Layers;
  selectedId: string | null;
  segmentId: string | null;
  colourBy: ColourBy;
  assetCodes: Set<string>;
  labelFor: (code: string) => string;
  onSelect: (id: string) => void;
  /** marker to emphasise (hovered in the side list) */
  hoverId?: string | null;
  onViewChange?: (b: { west: number; south: number; east: number; north: number }) => void;
}) {
  const t = useT();
  const ref = useRef<MapRef>(null);
  const [seg, setSeg] = useState<{ id: string; lng: number; lat: number; pinned: boolean } | null>(null);
  const [cursor, setCursor] = useState("");
  const [tilesFailed, setTilesFailed] = useState(false);
  // Fall back to the plain style only if the base map never loaded. One bad tile later (or a request
  // cancelled by panning) must not wipe the street map mid-demo.
  const baseOk = useRef(false);
  const segAt = (e: MapLayerMouseEvent) => {
    const id = e.features?.[0]?.properties?.id as string | undefined;
    return id ? { id, lng: e.lngLat.lng, lat: e.lngLat.lat } : null;
  };
  const shown = seg ? analysis.segments.find((x) => x.id === seg.id) : undefined;

  const lines = useMemo(() => {
    const m = colourBy === "condition" ? null : METRICS[colourBy];
    const scale = m ? metricScale(analysis.segments, m) : null;
    return {
      type: "FeatureCollection" as const,
      features: analysis.segments
        .filter((s) => s.coords?.length >= 2)
        .map((s) => ({
          type: "Feature" as const,
          properties: { id: s.id, color: m && scale ? scale.colorFor(m.pick(s)) : bandFor(s.condition).color, focus: s.id === segmentId ? 1 : 0 },
          geometry: { type: "LineString" as const, coordinates: s.coords },
        })),
    };
  }, [analysis.segments, segmentId, colourBy]);

  // Fit once per survey (and when ?segment= changes). Refetches after a mutation hand us a new
  // `analysis` object, which must not snap the map back and drop the user's pan/zoom.
  const latest = useRef(analysis);
  useEffect(() => {
    latest.current = analysis;
  });
  const reportView = () => {
    const b = ref.current?.getBounds();
    if (b && onViewChange) onViewChange({ west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() });
  };
  const fit = (duration: number) => {
    const b = boundsOf(latest.current, segmentId);
    if (b) ref.current?.fitBounds(b, { padding: 60, maxZoom: 19, duration });
  };
  useEffect(() => {
    if (ref.current) {
      const b = boundsOf(latest.current, segmentId);
      if (b) ref.current.fitBounds(b, { padding: 60, maxZoom: 19, duration: 400 });
    }
  }, [analysis.survey_id, segmentId]);

  const visible = analysis.findings.filter((f) => (assetCodes.has(f.type) ? layers.assets : layers.defects));

  const focused = segmentId ? analysis.segments.find((x) => x.id === segmentId) : undefined;
  return (
    <div className="relative size-full max-md:[&_.maplibregl-ctrl-group_button]:size-11!">
    {focused && (
      <div className="absolute right-3 bottom-8 z-10 flex flex-col gap-1 rounded-md border bg-card p-3 text-sm" role="status">
        <span className="num font-semibold">{focused.id}</span>
        <ConditionChip score={focused.condition} showLabel />
        <span className="text-muted-foreground">
          {focused.defect_count} {t(focused.defect_count === 1 ? "defect" : "defects", "ข้อบกพร่อง")}
        </span>
      </div>
    )}
    {tilesFailed && (
      <div role="status" className="pointer-events-none absolute top-3 right-16 z-10 flex max-w-[14rem] md:max-w-xs items-start gap-3 rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground">
        <p>{t("Map tiles could not load (offline?). Showing the route on a plain background.", "โหลดแผนที่ไม่ได้ (ออฟไลน์?) แสดงเส้นทางบนพื้นเรียบแทน")}</p>
        <button type="button" className="pointer-events-auto shrink-0 font-medium text-foreground underline underline-offset-2" onClick={() => setTilesFailed(false)}>
          {t("Retry", "ลองใหม่")}
        </button>
      </div>
    )}
    <MapGL
      ref={ref}
      onError={(e) => {
        const err = e as { sourceId?: string; error?: { name?: string; message?: string } };
        if (err.sourceId !== BASE_SOURCE || err.error?.name === "AbortError") return;
        console.warn("base map:", err.error?.message ?? err.error);
        if (!baseOk.current) setTilesFailed(true);
      }}
      onSourceData={(e) => {
        if (e.sourceId === BASE_SOURCE && e.isSourceLoaded) baseOk.current = true;
      }}
      mapStyle={tilesFailed ? PLAIN_STYLE : BASE_STYLE}
      transformRequest={viaOwnServer}
      initialViewState={{ longitude: analysis.findings[0]?.lon ?? 100.5, latitude: analysis.findings[0]?.lat ?? 13.8, zoom: 17 }}
      onLoad={() => {
        fit(0);
        reportView();
      }}
      onMoveEnd={reportView}
      interactiveLayerIds={layers.condition ? ["seg-line"] : []}
      cursor={cursor}
      onMouseMove={(e) => {
        const hit = segAt(e);
        setCursor(hit ? "pointer" : "");
        setSeg((cur) => (cur?.pinned ? cur : hit && { ...hit, pinned: false }));
      }}
      onMouseLeave={() => setSeg((cur) => (cur?.pinned ? cur : null))}
      onClick={(e) => {
        const hit = segAt(e);
        setSeg(hit && { ...hit, pinned: true });
      }}
      style={{ width: "100%", height: "100%" }}
      attributionControl={{ compact: true }}
    >
      <NavigationControl showCompass={false} position="top-right" />
      {layers.condition && (
        <Source id="segments" type="geojson" data={lines}>
          <Layer id="seg-casing" type="line" paint={{ "line-color": "#ffffff", "line-width": 11, "line-opacity": 0.9 }} layout={{ "line-cap": "round" }} />
          <Layer
            id="seg-focus"
            type="line"
            filter={["==", ["get", "focus"], 1]}
            paint={{ "line-color": "#102D50", "line-width": 15 }}
            layout={{ "line-cap": "round" }}
          />
          <Layer
            id="seg-line"
            type="line"
            paint={{ "line-color": ["get", "color"], "line-width": ["case", ["==", ["get", "focus"], 1], 9, 6] }}
            layout={{ "line-cap": "butt" }}
          />
        </Source>
      )}
      {seg && shown && (
        <Popup longitude={seg.lng} latitude={seg.lat} closeButton={seg.pinned} closeOnClick={false} onClose={() => setSeg(null)} offset={12} maxWidth="240px">
          <div className="flex flex-col gap-1 p-1 text-sm">
            <div className="num font-semibold">{shown.id}</div>
            <ConditionChip score={shown.condition} showLabel />
            {colourBy !== "condition" && (
              <div className="num">
                {t(METRICS[colourBy].en, METRICS[colourBy].th)}: {formatNumber(METRICS[colourBy].pick(shown), METRICS[colourBy].digits)} {METRICS[colourBy].unit}
              </div>
            )}
            <div className="text-muted-foreground">
              <Num value={shown.length_m} digits={0} unit="m" /> · {shown.defect_count} {t(shown.defect_count === 1 ? "defect" : "defects", "ข้อบกพร่อง")}
            </div>
          </div>
        </Popup>
      )}
      {visible.map((f) => (
        <FindingMarker key={f.id} f={f} asset={assetCodes.has(f.type)} selected={f.id === selectedId} hovered={f.id === hoverId} label={labelFor(f.type)} onSelect={onSelect} />
      ))}
    </MapGL>
    </div>
  );
}

function FindingMarker({
  f,
  asset,
  selected,
  hovered,
  label,
  onSelect,
}: {
  f: Finding;
  asset: boolean;
  selected: boolean;
  hovered: boolean;
  label: string;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const words = useWords();
  const sev = f.severity;
  const resolved = f.status === "fixed" || f.status === "verified" || f.status === "dismissed";
  const name = `${f.id}, ${label}${sev ? `, ${t(`${sev} severity`, `ความรุนแรง${{ high: "สูง", medium: "กลาง", low: "ต่ำ" }[sev]}`)}` : ""}${resolved ? `, ${words.status(f.status)}` : ""}`;
  return (
    <Marker longitude={f.lon} latitude={f.lat} anchor="center" style={{ zIndex: selected || hovered ? 5 : undefined }}>
      <button
        type="button"
        aria-label={name}
        title={name}
        data-finding-id={f.id}
        onClick={() => onSelect(f.id)}
        className={cn(
          "grid size-11 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-brand",
        )}
      >
        <span
          className={cn(
            "grid size-7 place-items-center rounded-full border bg-white",
            selected ? "border-2 border-brand ring-2 ring-white" : hovered ? "scale-125 border-2 border-brand" : "border-grey-300",
            asset && "rounded-[4px] border-brand/60",
            resolved && "border-grey-200 bg-grey-100 opacity-60",
          )}
        >
          {resolved ? <Check className="size-3.5 text-grey-500" aria-hidden /> : sev ? <SeverityIcon severity={sev} size={13} /> : <span className="size-2.5 rotate-45 bg-brand" aria-hidden />}
        </span>
      </button>
    </Marker>
  );
}

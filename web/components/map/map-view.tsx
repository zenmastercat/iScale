"use client";
import type { StyleSpecification } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import MapGL, { Layer, Marker, NavigationControl, Source, type MapRef } from "@/lib/maplibre";
import { SEVERITY, SeverityIcon } from "@/components/shared";
import { bandFor } from "@/lib/condition";
import type { Analysis, Finding } from "@/lib/types";
import { cn } from "@/lib/utils";

/* OSM raster tiles over a plain background layer: if tiles fail the plain background stays. */
const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#eef0ec" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.85 } },
  ],
};

export interface Layers {
  condition: boolean;
  defects: boolean;
  assets: boolean;
}

export function MapView({
  analysis,
  layers,
  selectedId,
  segmentId,
  assetCodes,
  labelFor,
  onSelect,
}: {
  analysis: Analysis;
  layers: Layers;
  selectedId: string | null;
  segmentId: string | null;
  assetCodes: Set<string>;
  labelFor: (code: string) => string;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<MapRef>(null);

  const lines = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: analysis.segments
        .filter((s) => s.coords?.length >= 2)
        .map((s) => ({
          type: "Feature" as const,
          properties: { id: s.id, color: bandFor(s.condition).color, focus: s.id === segmentId ? 1 : 0 },
          geometry: { type: "LineString" as const, coordinates: s.coords },
        })),
    }),
    [analysis.segments, segmentId],
  );

  const bounds = useMemo(() => {
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
    ] as [[number, number], [number, number]];
  }, [analysis, segmentId]);

  const fit = () => {
    if (bounds) ref.current?.fitBounds(bounds, { padding: 60, maxZoom: 19, duration: 0 });
  };
  useEffect(() => {
    if (ref.current && bounds) ref.current.fitBounds(bounds, { padding: 60, maxZoom: 19, duration: 400 });
  }, [bounds]);

  const visible = analysis.findings.filter((f) => (assetCodes.has(f.type) ? layers.assets : layers.defects));

  return (
    <MapGL
      ref={ref}
      mapStyle={STYLE}
      initialViewState={{ longitude: analysis.findings[0]?.lon ?? 100.5, latitude: analysis.findings[0]?.lat ?? 13.8, zoom: 17 }}
      onLoad={fit}
      style={{ width: "100%", height: "100%" }}
      attributionControl={{ compact: true }}
    >
      <NavigationControl showCompass={false} position="top-right" />
      {layers.condition && (
        <Source id="segments" type="geojson" data={lines}>
          <Layer id="seg-casing" type="line" paint={{ "line-color": "#ffffff", "line-width": 11, "line-opacity": 0.9 }} layout={{ "line-cap": "round" }} />
          <Layer
            id="seg-line"
            type="line"
            paint={{ "line-color": ["get", "color"], "line-width": ["case", ["==", ["get", "focus"], 1], 9, 6] }}
            layout={{ "line-cap": "butt" }}
          />
        </Source>
      )}
      {visible.map((f) => (
        <FindingMarker key={f.id} f={f} asset={assetCodes.has(f.type)} selected={f.id === selectedId} label={labelFor(f.type)} onSelect={onSelect} />
      ))}
    </MapGL>
  );
}

function FindingMarker({
  f,
  asset,
  selected,
  label,
  onSelect,
}: {
  f: Finding;
  asset: boolean;
  selected: boolean;
  label: string;
  onSelect: (id: string) => void;
}) {
  const sev = f.severity;
  const name = `${label}${sev ? `, ${SEVERITY[sev].label} severity` : ""}`;
  return (
    <Marker longitude={f.lon} latitude={f.lat} anchor="center" style={{ zIndex: selected ? 5 : undefined }}>
      <button
        type="button"
        aria-label={name}
        title={name}
        onClick={() => onSelect(f.id)}
        className={cn(
          "grid size-11 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-brand",
        )}
      >
        <span
          className={cn(
            "grid size-7 place-items-center rounded-full border bg-white",
            selected ? "border-2 border-brand ring-2 ring-white" : "border-grey-300",
            asset && "rounded-[4px] border-brand/60",
          )}
        >
          {sev ? <SeverityIcon severity={sev} size={13} /> : <span className="size-2.5 rotate-45 bg-brand" aria-hidden />}
        </span>
      </button>
    </Marker>
  );
}

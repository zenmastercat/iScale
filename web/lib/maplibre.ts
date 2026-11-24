"use client";
/*
 * Import react-map-gl from HERE, not from "react-map-gl/maplibre":
 *   import MapGL, { Layer, Marker, Source } from "@/lib/maplibre";
 * It points MapLibre at its web worker first (copied to public/ by scripts/copy-maplibre-worker.mjs).
 * Without this, GeoJSON sources (route lines) never render and the console says "Worker failed to load".
 */
import { setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

if (typeof window !== "undefined") setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

export * from "react-map-gl/maplibre";
export { default } from "react-map-gl/maplibre";

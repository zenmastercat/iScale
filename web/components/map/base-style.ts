import type { StyleSpecification } from "maplibre-gl";

/**
 * Road-first base map: OpenStreetMap data as vector tiles from OpenFreeMap (free, no API key, no usage limit;
 * https://openfreemap.org). Roads are the strongest shape (white with a dark casing, width by road class),
 * buildings are faint context, shop and bus-stop icons are left out, so the condition line is the only colour.
 * If the tiles can't be loaded, map-view.tsx switches to PLAIN_STYLE and shows a notice. Credits are required by the licences.
 *
 * The browser never calls tiles.openfreemap.org itself: viaOwnServer() rewrites every request to /basemap/… on our own
 * origin (proxied by next.config.ts in dev and scripts/serve.mjs in the build). Same-origin, so a privacy add-on,
 * strict tracking protection or CORS can't block the map, the CSP needs no third-party host, and serve.mjs keeps a
 * disk copy of every tile it has served, so a route viewed once still has its street map offline at the venue.
 */
const TILES = "https://tiles.openfreemap.org";
export const TILE_PATH = "/basemap";
export const BASE_SOURCE = "base";

/** MapLibre transformRequest: send tile, TileJSON and font requests through our own server. */
export function viaOwnServer(url: string) {
  return url.startsWith(`${TILES}/`) ? { url: `${window.location.origin}${TILE_PATH}${url.slice(TILES.length)}` } : { url };
}

const ROADS = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor", "service"];
const byClass = (major: number, mid: number, service: number, minor: number) => [
  "match",
  ["get", "class"],
  ["motorway", "trunk", "primary"],
  major,
  ["secondary", "tertiary"],
  mid,
  "service",
  service,
  minor,
];

export const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    [BASE_SOURCE]: {
      type: "vector",
      url: `${TILES}/planet`,
      attribution:
        '<a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener noreferrer">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>',
    },
  },
  glyphs: `${TILES}/fonts/{fontstack}/{range}.pbf`,
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#f4f5f7" } },
    { id: "water", type: "fill", source: BASE_SOURCE, "source-layer": "water", paint: { "fill-color": "#d9e4ef" } },
    {
      id: "building",
      type: "fill",
      source: BASE_SOURCE,
      "source-layer": "building",
      minzoom: 14,
      paint: { "fill-color": "#e8eaed", "fill-outline-color": "#dde0e4" },
    },
    {
      id: "rail",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "transportation",
      filter: ["==", ["get", "class"], "rail"],
      paint: { "line-color": "#c4c9d0", "line-width": 1, "line-dasharray": [3, 3] },
    },
    {
      id: "path",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["path", "track"]]],
      paint: { "line-color": "#c9ced5", "line-width": 1, "line-dasharray": [2, 2] },
    },
    {
      id: "road-casing",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ROADS]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#6b7480",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- style-spec expression arrays aren't typed precisely
        "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, byClass(3, 2.2, 1.2, 1.2), 18, byClass(34, 26, 10, 16)] as any,
      },
    },
    {
      id: "road",
      type: "line",
      source: BASE_SOURCE,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ROADS]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#ffffff",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- as above
        "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, byClass(2, 1.4, 0.6, 0.6), 18, byClass(31, 23, 8, 13.5)] as any,
      },
    },
    {
      id: "road-name",
      type: "symbol",
      source: BASE_SOURCE,
      "source-layer": "transportation_name",
      minzoom: 14,
      layout: {
        "symbol-placement": "line",
        "text-font": ["Noto Sans Regular"],
        "text-size": 13,
        // English and Thai street names, as on the street signs
        "text-field": [
          "case",
          ["has", "name:nonlatin"],
          ["concat", ["get", "name:latin"], "  ", ["get", "name:nonlatin"]],
          ["coalesce", ["get", "name_en"], ["get", "name"]],
        ],
      },
      paint: { "text-color": "#1f2937", "text-halo-color": "#ffffff", "text-halo-width": 2 },
    },
  ],
};

/** Used when the tile host can't be reached: loads with no network, so the route and markers still draw. */
export const PLAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#f4f5f7" } }],
};

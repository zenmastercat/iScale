// MapLibre 6 loads its worker from a separate file next to the bundle; Next doesn't emit it.
// Copy it to public/ (served at /maplibre/maplibre-gl-worker.mjs) on install, dev and build.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const src = path.join(path.dirname(require.resolve("maplibre-gl/package.json")), "dist", "maplibre-gl-worker.mjs");
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "maplibre");
mkdirSync(outDir, { recursive: true });
copyFileSync(src, path.join(outDir, "maplibre-gl-worker.mjs"));
console.log("maplibre worker → public/maplibre/maplibre-gl-worker.mjs");

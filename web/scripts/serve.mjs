#!/usr/bin/env node
/*
 * Serve the static export (out/) and proxy /api/* to the FastAPI backend, same-origin.
 * For the pitch: `pnpm build && pnpm serve` → http://127.0.0.1:3000
 * Env: PORT (3000), HOST (127.0.0.1), CIVIL_API (http://127.0.0.1:8765)
 * The proxied request keeps Host = the backend's host, so CIVIL_ALLOWED_HOSTS needs no change.
 */
import { createReadStream, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "out");
const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "127.0.0.1";
const API = new URL(process.env.CIVIL_API ?? "http://127.0.0.1:8765");

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2",
  ".txt": "text/plain", ".map": "application/json", ".webmanifest": "application/manifest+json",
};

function fileFor(urlPath) {
  const clean = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
  const candidates = [clean, `${clean}.html`, path.join(clean, "index.html")];
  for (const c of candidates) {
    const full = path.join(ROOT, c);
    if (!full.startsWith(ROOT)) return null;
    try {
      if (statSync(full).isFile()) return full;
    } catch {}
  }
  return null;
}

function proxy(req, res) {
  const headers = { ...req.headers, host: API.host };
  delete headers.origin; // same-origin from the browser's point of view
  const up = http.request(
    { hostname: API.hostname, port: API.port, path: req.url, method: req.method, headers },
    (r) => {
      res.writeHead(r.statusCode ?? 502, r.headers);
      r.pipe(res);
    },
  );
  up.on("error", (e) => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: `backend unreachable at ${API.origin}: ${e.message}` }));
  });
  req.pipe(up);
}

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://x");
    if (url.pathname.startsWith("/api/")) return proxy(req, res);
    const file = fileFor(url.pathname) ?? path.join(ROOT, "404.html");
    const found = fileFor(url.pathname) !== null;
    res.writeHead(found ? 200 : 404, {
      "content-type": TYPES[path.extname(file)] ?? "application/octet-stream",
      "cache-control": url.pathname.startsWith("/_next/static/") ? "public, max-age=31536000, immutable" : "no-cache",
    });
    createReadStream(file).on("error", () => res.end()).pipe(res);
  })
  .listen(PORT, HOST, () => console.log(`iScale web: http://${HOST}:${PORT}  (api → ${API.origin})`));

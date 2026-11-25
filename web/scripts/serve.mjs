#!/usr/bin/env node
/*
 * Serve the static export (out/) and proxy /api/* to the FastAPI backend, same-origin.
 * For the pitch: `pnpm build && pnpm serve` → http://127.0.0.1:3000
 * Env: PORT (3000), HOST (127.0.0.1), CIVIL_API (http://127.0.0.1:8765)
 * Like the backend, only requests addressed to an allowed Host are served (DNS-rebinding defence):
 * 127.0.0.1 / localhost / [::1] on PORT, plus any host in CIVIL_ALLOWED_HOSTS (e.g. a LAN IP for a phone).
 */
import { createReadStream, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "out");
const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "127.0.0.1";
const API = new URL(process.env.CIVIL_API ?? "http://127.0.0.1:8765");

const ALLOWED = new Set(
  ["127.0.0.1", "localhost", "[::1]", ...(process.env.CIVIL_ALLOWED_HOSTS ?? "").split(",")]
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean)
    .flatMap((h) => [h, `${h}:${PORT}`]),
);

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2",
  ".txt": "text/plain", ".map": "application/json", ".webmanifest": "application/manifest+json",
};

function fileFor(urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null; // malformed % escape
  }
  const clean = path.normalize(decoded).replace(/^(\.\.[/\\])+/, "");
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
  // Host was checked against ALLOWED above; the backend gets its own host so its allowlist matches
  const headers = { ...req.headers, host: API.host };
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
    try {
      handle(req, res);
    } catch (e) {
      if (!res.headersSent) res.writeHead(400, { "content-type": "text/plain" });
      res.end(`bad request: ${e instanceof Error ? e.message : e}`);
    }
  })
  .listen(PORT, HOST, () => console.log(`iScale web: http://${HOST}:${PORT}  (api → ${API.origin})`));

function handle(req, res) {
    if (!ALLOWED.has(String(req.headers.host ?? "").toLowerCase())) {
      res.writeHead(400, { "content-type": "text/plain" });
      return res.end("Invalid host header (add it to CIVIL_ALLOWED_HOSTS)");
    }
    const url = new URL(req.url ?? "/", "http://x");
    if (url.pathname.startsWith("/api/")) return proxy(req, res);
    const hit = fileFor(url.pathname);
    const file = hit ?? path.join(ROOT, "404.html");
    res.writeHead(hit ? 200 : 404, {
      "content-type": TYPES[path.extname(file)] ?? "application/octet-stream",
      "cache-control": url.pathname.startsWith("/_next/static/") ? "public, max-age=31536000, immutable" : "no-cache",
    });
    createReadStream(file).on("error", () => res.end()).pipe(res);
}

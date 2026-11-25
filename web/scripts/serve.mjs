#!/usr/bin/env node
/*
 * Serve the static export (out/) and proxy /api/* to the FastAPI backend, same-origin.
 * For the pitch: `pnpm build && pnpm serve` → http://127.0.0.1:3000
 * Env: PORT (3000), HOST (127.0.0.1), CIVIL_API (http://127.0.0.1:8765)
 * Like the backend, only requests addressed to an allowed Host are served (DNS-rebinding defence):
 * 127.0.0.1 / localhost / [::1] on PORT, plus any host in CIVIL_ALLOWED_HOSTS (e.g. a LAN IP for a phone).
 *
 * Security headers on every page: a Content-Security-Policy whose script-src lists the SHA-256 of each inline
 * <script> in that HTML file (Next's static export inlines its bootstrap), so no 'unsafe-inline' for scripts;
 * nosniff, no framing, same-origin referrer, COOP/CORP. The only third-party origin is the OSM tile server.
 * The proxy overwrites X-Forwarded-For with the real peer address: uvicorn trusts it from loopback (us), so a
 * client could otherwise pick its own address and dodge the backend's per-address sign-in limit.
 */
import { createHash } from "node:crypto";
import { createReadStream, readFileSync, statSync } from "node:fs";
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

const TILES = "https://tile.openstreetmap.org";
const BASE_HEADERS = {
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "same-origin",
  "permissions-policy": "camera=(self), geolocation=(self), microphone=(), payment=(), usb=()",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
};

/** CSP for one HTML file, with a hash per inline script; cached per file until it changes on disk. */
const cspCache = new Map();
function cspFor(file) {
  const mtime = statSync(file).mtimeMs;
  const hit = cspCache.get(file);
  if (hit && hit.mtime === mtime) return hit.csp;
  const html = readFileSync(file, "utf8");
  const hashes = new Set();
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)) {
    if (m[1]) hashes.add(`'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`);
  }
  const csp = [
    "default-src 'self'",
    `script-src 'self' ${[...hashes].join(" ")}`.trim(),
    "style-src 'self' 'unsafe-inline'", // React style={} attributes and the map's inline styles
    `img-src 'self' data: blob: ${TILES}`,
    `connect-src 'self' ${TILES}`,
    "worker-src 'self' blob:",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  cspCache.set(file, { mtime, csp });
  return csp;
}

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
    if (full !== ROOT && !full.startsWith(ROOT + path.sep)) return null;
    try {
      if (statSync(full).isFile()) return full;
    } catch {}
  }
  return null;
}

function proxy(req, res) {
  // Host was checked against ALLOWED above; the backend gets its own host so its allowlist matches
  const headers = { ...req.headers, host: API.host, "x-forwarded-for": req.socket.remoteAddress ?? "", "x-forwarded-proto": "http" };
  delete headers.forwarded;
  const up = http.request(
    { hostname: API.hostname, port: API.port, path: req.url, method: req.method, headers },
    (r) => {
      res.writeHead(r.statusCode ?? 502, { ...BASE_HEADERS, ...r.headers });
      r.pipe(res);
    },
  );
  up.on("error", (e) => {
    res.writeHead(502, { ...BASE_HEADERS, "content-type": "application/json" });
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
    const type = TYPES[path.extname(file)] ?? "application/octet-stream";
    res.writeHead(hit ? 200 : 404, {
      ...BASE_HEADERS,
      ...(type.startsWith("text/html") ? { "content-security-policy": cspFor(file) } : {}),
      "content-type": type,
      "cache-control": url.pathname.startsWith("/_next/static/") ? "public, max-age=31536000, immutable" : "no-cache",
    });
    createReadStream(file).on("error", () => res.end()).pipe(res);
}

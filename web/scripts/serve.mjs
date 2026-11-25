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
 * nosniff, no framing, same-origin referrer, COOP/CORP. No third-party origins: base map tiles come through
 * /basemap/* (below), proxied to OpenFreeMap with a disk copy in .cache/basemap so viewed areas still work offline.
 * The proxy overwrites X-Forwarded-For with the real peer address: uvicorn trusts it from loopback (us), so a
 * client could otherwise pick its own address and dodge the backend's per-address sign-in limit.
 */
import { createHash } from "node:crypto";
import { createReadStream, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
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

const TILES = "https://tiles.openfreemap.org"; // vector tiles, TileJSON and fonts for the map (components/map/base-style.ts)
const TILE_CACHE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", ".cache", "basemap");
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
    "img-src 'self' data: blob:",
    "connect-src 'self'",
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

/**
 * GET /basemap/<path> → TILES/<path>. Fixed upstream host (no open proxy). Every 200 is kept on disk: tiles and fonts
 * are served from disk once cached (their URLs are versioned); the TileJSON ("planet", which names the current tile
 * set) is fetched fresh and the disk copy is the fallback when the upstream is unreachable.
 */
async function basemap(req, res, url) {
  const rel = url.pathname.slice("/basemap/".length);
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, BASE_HEADERS);
    return res.end();
  }
  if (!/^[A-Za-z0-9_.%-]+(\/[A-Za-z0-9_.%-]+)*$/.test(rel) || rel.split("/").some((s) => s === "." || s === "..")) {
    res.writeHead(400, BASE_HEADERS);
    return res.end();
  }
  const versioned = rel.includes("/");
  // the TileJSON "planet" and the tile folder "planet/<version>/…" share a name: keep unversioned files apart
  const file = path.join(TILE_CACHE, versioned ? "files" : "index", rel);
  const type = rel.endsWith(".pbf") ? "application/x-protobuf" : "application/json";
  const send = (status, body, cc) => {
    res.writeHead(status, { ...BASE_HEADERS, "content-type": type, "cache-control": cc });
    res.end(req.method === "HEAD" ? undefined : body);
  };
  const cached = () => {
    try {
      return readFileSync(file);
    } catch {
      return null;
    }
  };
  if (versioned) {
    const hit = cached();
    if (hit) return send(200, hit, "public, max-age=86400");
  }
  try {
    const up = await fetch(`${TILES}/${rel}`, { signal: AbortSignal.timeout(8000) });
    if (!up.ok) {
      res.writeHead(up.status, BASE_HEADERS);
      return res.end();
    }
    const body = Buffer.from(await up.arrayBuffer());
    try {
      mkdirSync(path.dirname(file), { recursive: true });
      writeFileSync(`${file}.tmp`, body);
      renameSync(`${file}.tmp`, file);
    } catch (e) {
      console.warn(`basemap cache: ${e instanceof Error ? e.message : e}`); // serve it anyway
    }
    send(200, body, versioned ? "public, max-age=86400" : "no-cache");
  } catch {
    const hit = cached();
    if (hit) return send(200, hit, "no-cache");
    res.writeHead(502, BASE_HEADERS);
    res.end();
  }
}

const server = http.createServer((req, res) => {
  try {
    handle(req, res);
  } catch (e) {
    if (!res.headersSent) res.writeHead(400, { "content-type": "text/plain" });
    res.end(`bad request: ${e instanceof Error ? e.message : e}`);
  }
});
server.listen(PORT, HOST, () => console.log(`iScale web: http://${HOST}:${PORT}  (api → ${API.origin})`));

/**
 * Crew chat: GET /xmpp is the XMPP-over-WebSocket the backend passes on to its chat server. Only that path is passed
 * through, after the same Host check as everything else. The backend wants Host and Origin to agree and to be its own
 * (it checks the session cookie too), so both are rewritten to the backend's, but only after our own Origin check above.
 */
server.on("upgrade", (req, socket, head) => {
  const host = String(req.headers.host ?? "").toLowerCase();
  // A browser always sends Origin on a WebSocket: it must be one of our own hosts (stops a page on another site opening
  // this socket with the user's cookie). Only after that is it rewritten below, to what the backend expects.
  let originHost = "";
  if (req.headers.origin) {
    try {
      originHost = new URL(String(req.headers.origin)).host.toLowerCase();
    } catch {
      originHost = "?";
    }
  }
  if (!ALLOWED.has(host) || (req.headers.origin && !ALLOWED.has(originHost)) || !/^\/xmpp(\?|$)/.test(req.url ?? "")) {
    socket.write("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
    return socket.destroy();
  }
  const up = net.connect(Number(API.port) || 80, API.hostname);
  up.on("error", () => {
    socket.write("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n");
    socket.destroy();
  });
  socket.on("error", () => up.destroy());
  up.on("connect", () => {
    const headers = { ...req.headers, host: API.host, "x-forwarded-for": req.socket.remoteAddress ?? "", "x-forwarded-proto": "http" };
    if (headers.origin) headers.origin = `http://${API.host}`;
    delete headers.forwarded;
    const lines = Object.entries(headers).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`);
    up.write(`${req.method} ${req.url} HTTP/1.1\r\n${lines.join("\r\n")}\r\n\r\n`);
    if (head?.length) up.write(head);
    socket.pipe(up);
    up.pipe(socket);
  });
});

function handle(req, res) {
    if (!ALLOWED.has(String(req.headers.host ?? "").toLowerCase())) {
      res.writeHead(400, { "content-type": "text/plain" });
      return res.end("Invalid host header (add it to CIVIL_ALLOWED_HOSTS)");
    }
    const url = new URL(req.url ?? "/", "http://x");
    if (url.pathname.startsWith("/api/")) return proxy(req, res);
    if (url.pathname.startsWith("/basemap/")) {
      basemap(req, res, url).catch(() => {
        if (!res.headersSent) res.writeHead(502, BASE_HEADERS);
        res.end();
      });
      return;
    }
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

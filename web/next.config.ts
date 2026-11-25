import type { NextConfig } from "next";

/*
 * Dev (`pnpm dev`): /api/* is proxied to the FastAPI backend so requests are same-origin
 * (SameSite=Strict session cookie, no CORS).
 * Build (`pnpm build`): static export to out/. Rewrites don't apply to an export, so the
 * exported site is served by scripts/serve.mjs, which also proxies /api. See README.md.
 */
const isDev = process.env.NODE_ENV !== "production";
const API = process.env.CIVIL_API ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  ...(isDev
    ? {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${API}/api/:path*` },
            // base map tiles via our own origin (components/map/base-style.ts); scripts/serve.mjs does this in the build
            { source: "/basemap/:path*", destination: "https://tiles.openfreemap.org/:path*" },
          ];
        },
      }
    : { output: "export" as const }),
  // the backend's host allowlist is 127.0.0.1/localhost; let the dev server be opened on either
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  devIndicators: false,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

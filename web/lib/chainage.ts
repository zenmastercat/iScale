/* Chainage (distance along the route, metres) for a finding, from its segment's polyline. */
import type { Finding, Segment } from "@/lib/types";

const R = 6_371_000;

/** Project lat/lon onto the segment's coords ([lon, lat] pairs); returns metres from route start. */
export function findingChainage(f: Pick<Finding, "lat" | "lon" | "segment_id">, segments: Segment[]): number | null {
  const seg = segments.find((s) => s.id === f.segment_id);
  if (!seg) return null;
  const pts = seg.coords;
  if (!pts || pts.length < 2) return (seg.s0 + seg.s1) / 2;
  const lat0 = (pts[0][1] * Math.PI) / 180;
  const xy = (lon: number, lat: number): [number, number] => [
    ((lon * Math.PI) / 180) * R * Math.cos(lat0),
    ((lat * Math.PI) / 180) * R,
  ];
  const p = xy(f.lon, f.lat);
  let best = Infinity;
  let bestAlong = 0;
  let along = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = xy(pts[i][0], pts[i][1]);
    const b = xy(pts[i + 1][0], pts[i + 1][1]);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    const t = len ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (len * len))) : 0;
    const d = Math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]);
    if (d < best) {
      best = d;
      bestAlong = along + t * len;
    }
    along += len;
  }
  // scale the polyline length to the segment's nominal length
  const frac = along ? bestAlong / along : 0.5;
  return seg.s0 + frac * (seg.s1 - seg.s0);
}

/** Findings that still need work (not fixed / verified / dismissed) and are defects. */
export const isOpenDefect = (f: Finding) =>
  !!f.severity && f.status !== "fixed" && f.status !== "verified" && f.status !== "dismissed";

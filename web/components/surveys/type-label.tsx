"use client";
import { useCatalogLabel } from "@/lib/queries";

/** A catalog defect name in the current language (Thai when we have it, else the server's English label). */
export function TypeLabel({ type, fallback }: { type: string; fallback: string }) {
  const label = useCatalogLabel();
  const l = label(type);
  // useCatalogLabel humanizes an unknown code; keep the server's own wording in that case
  return <>{l === type || l === "" ? fallback : l}</>;
}

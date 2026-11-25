"use client";
import { useSyncExternalStore } from "react";

/** Media query as external state: correct on the first client render (no wrong-side flash), false on the server. */
export function useMediaQuery(q: string) {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(q);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(q).matches,
    () => false,
  );
}

"use client";
/*
 * English / Thai. No key files: write both strings where the text is,
 *   const t = useT();  <h2>{t("Open defects", "ข้อบกพร่องที่ยังไม่ซ่อม")}</h2>
 * The choice is stored in localStorage and sets <html lang>. Numbers, ids and units stay as they are.
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Lang = "en" | "th";
const KEY = "iscale-lang";

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => {
    const saved = window.localStorage.getItem(KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once after hydration (static export has no server value)
    if (saved === "th" || saved === "en") setLangState(saved);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    window.localStorage.setItem(KEY, l);
  }, []);
  return <Ctx.Provider value={{ lang, setLang }}>{children}</Ctx.Provider>;
}

export const useLang = () => useContext(Ctx);

/** t(english, thai) → the string for the current language. */
export function useT() {
  const { lang } = useContext(Ctx);
  return useCallback((en: string, th: string) => (lang === "th" ? th : en), [lang]);
}

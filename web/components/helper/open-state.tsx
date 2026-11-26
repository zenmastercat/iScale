"use client";
import { createContext, useContext, useState } from "react";

const Ctx = createContext<{ open: boolean; setOpen: (v: boolean) => void }>({ open: false, setOpen: () => {} });

/** Whether the floating Civil Helper panel is open; shared so the phone "More" sheet can open it. */
export function HelperOpenProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <Ctx.Provider value={{ open, setOpen }}>{children}</Ctx.Provider>;
}
export const useHelperOpen = () => useContext(Ctx);

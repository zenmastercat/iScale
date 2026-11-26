"use client";
import { Bot, Menu, Settings2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { useSelection } from "@/lib/selection";
import { Logo } from "./logo";
import { useLang, useT } from "@/lib/i18n";
import { useHelperOpen } from "@/components/helper/open-state";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useReviewCounts } from "@/lib/review-counts";
import { useRailStatus } from "@/lib/rail-status";
import { NAV, NAV_GROUPS, ROUTES } from "./nav";

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

/** Left rail on md+ screens: Work (in workflow order, with a status line), Explore, Team. */
export function SideRail() {
  const pathname = usePathname();
  const { withSel } = useSelection();
  const { lang } = useLang();
  const status = useRailStatus();
  return (
    <nav aria-label="Main" className="sticky top-0 hidden print:hidden h-dvh w-60 shrink-0 flex-col overflow-y-auto bg-sidebar px-3 py-6 text-sidebar-foreground md:flex">
      <Link href={withSel("/")} className="mb-6 px-3">
        <Logo />
      </Link>
      {NAV_GROUPS.map((g, gi) => (
        <div key={g.id} className={gi === 0 ? "" : "mt-5"}>
          <p className="mb-2 px-3 text-xs font-medium tracking-wider text-white/70 uppercase">{lang === "th" ? g.th : g.label}</p>
          <ul className="flex flex-col gap-1">
            {NAV.filter((n) => n.group === g.id)
              .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
              .map(({ href, label, th, icon: Icon }) => {
                const active = isActive(pathname, href);
                const line = status[href];
                return (
                  <li key={href}>
                    <Link
                      href={withSel(href)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-11 items-center gap-3 rounded-md px-3 py-1.5 text-[15px] font-medium transition-colors",
                        active ? "bg-sidebar-accent text-white" : "text-white/85 hover:bg-white/8 hover:text-white",
                      )}
                    >
                      <Icon aria-hidden className="size-5 shrink-0" strokeWidth={1.75} />
                      <span className="flex min-w-0 flex-col leading-tight">
                        {lang === "th" ? th : label}
                        {line && <span className="num truncate text-xs font-normal text-white/70">{line}</span>}
                      </span>
                    </Link>
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** Bottom tab bar on phones: the "bar" pages plus More (a bottom sheet with every other page and Civil Helper). */
export function BottomBar() {
  const pathname = usePathname();
  const { withSel } = useSelection();
  const { lang } = useLang();
  const t = useT();
  const { setOpen: openHelper } = useHelperOpen();
  const [more, setMore] = useState(false);
  const { unreviewed, stillPresent } = useReviewCounts();
  const badge: Record<string, number | null> = { "/findings": unreviewed, "/verification": stillPresent };
  const label = (n: (typeof NAV)[number]) => (lang === "th" ? n.th : n.label);
  const moreItems = NAV.filter((n) => n.phone === "more");
  const moreActive = moreItems.some((n) => isActive(pathname, n.href)) || pathname.startsWith(ROUTES.helper);
  const tab = "flex min-h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium";
  const row = "flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-left text-[15px] font-medium hover:bg-grey-50";
  return (
    <>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-sidebar pb-[env(safe-area-inset-bottom)] md:hidden print:hidden"
      >
        <ul className="grid grid-cols-6">
          {NAV.filter((n) => n.phone === "bar").map(({ href, short, shortTh, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={withSel(href)}
                  aria-current={active ? "page" : undefined}
                  className={cn(tab, active ? "text-white" : "text-white/70")}
                >
                  <Icon aria-hidden className={cn("size-5", active && "text-[#8ec0f0]")} strokeWidth={1.75} />
                  {lang === "th" ? shortTh : short}
                </Link>
              </li>
            );
          })}
          <li>
            <button
              type="button"
              onClick={() => setMore(true)}
              aria-haspopup="dialog"
              aria-current={moreActive ? "page" : undefined}
              className={cn(tab, moreActive ? "text-white" : "text-white/70")}
            >
              <Menu aria-hidden className={cn("size-5", moreActive && "text-[#8ec0f0]")} strokeWidth={1.75} />
              {t("More", "เพิ่มเติม")}
            </button>
          </li>
        </ul>
      </nav>
      <Sheet open={more} onOpenChange={setMore}>
        <SheetContent side="bottom" className="max-h-[85dvh] gap-0 overflow-y-auto pb-[env(safe-area-inset-bottom)] md:hidden">
          <SheetHeader>
            <SheetTitle>{t("More", "เพิ่มเติม")}</SheetTitle>
          </SheetHeader>
          <ul className="flex flex-col gap-0.5 px-2 pb-3">
            {moreItems.map((n) => {
              const active = isActive(pathname, n.href);
              const Icon = n.icon;
              const count = badge[n.href] ?? 0;
              return (
                <li key={n.href}>
                  <Link href={withSel(n.href)} onClick={() => setMore(false)} aria-current={active ? "page" : undefined} className={cn(row, active && "bg-grey-50 text-brand")}>
                    <Icon aria-hidden className="size-5" strokeWidth={1.75} />
                    {label(n)}
                    {count > 0 && <span className="num ml-auto rounded-full bg-grey-100 px-2 py-0.5 text-xs font-semibold">{count}</span>}
                  </Link>
                </li>
              );
            })}
            <li>
              <button type="button" className={row} onClick={() => { setMore(false); openHelper(true); }}>
                <Bot aria-hidden className="size-5" strokeWidth={1.75} />
                {t("Ask Civil Helper", "ถามผู้ช่วยวิศวกร")}
              </button>
            </li>
            <li>
              <Link href={withSel(ROUTES.helper)} onClick={() => setMore(false)} aria-current={pathname.startsWith(ROUTES.helper) ? "page" : undefined} className={cn(row, pathname.startsWith(ROUTES.helper) && "bg-grey-50 text-brand")}>
                <Settings2 aria-hidden className="size-5" strokeWidth={1.75} />
                {t("Helper library & settings", "คลังเอกสารและการตั้งค่าผู้ช่วย")}
              </Link>
            </li>
          </ul>
        </SheetContent>
      </Sheet>
    </>
  );
}

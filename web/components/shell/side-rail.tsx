"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useSelection } from "@/lib/selection";
import { Logo } from "./logo";
import { NAV } from "./nav";

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

/** Left rail on md+ screens. */
export function SideRail() {
  const pathname = usePathname();
  const { withSel } = useSelection();
  return (
    <nav aria-label="Main" className="sticky top-0 hidden print:hidden h-dvh w-60 shrink-0 flex-col bg-sidebar px-3 py-6 text-sidebar-foreground md:flex">
      <Link href={withSel("/")} className="mb-8 px-3">
        <Logo />
      </Link>
      <p className="mb-2 px-3 text-xs font-medium tracking-wider text-white/70 uppercase">Workspace</p>
      <ul className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={withSel(href)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-11 items-center gap-3 rounded-md px-3 text-[15px] font-medium transition-colors",
                  active ? "bg-sidebar-accent text-white" : "text-white/85 hover:bg-white/8 hover:text-white",
                )}
              >
                <Icon aria-hidden className="size-5" strokeWidth={1.75} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Bottom tab bar on phones. */
export function BottomBar() {
  const pathname = usePathname();
  const { withSel } = useSelection();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-sidebar pb-[env(safe-area-inset-bottom)] md:hidden print:hidden"
    >
      <ul className="grid grid-cols-6">
        {NAV.filter((n) => !n.desktopOnly).map(({ href, short, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={withSel(href)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                  active ? "text-white" : "text-white/70",
                )}
              >
                <Icon aria-hidden className={cn("size-5", active && "text-[#8ec0f0]")} strokeWidth={1.75} />
                {short}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

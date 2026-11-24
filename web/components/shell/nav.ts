import { ClipboardCheck, LayoutDashboard, ListOrdered, Map, Route, Wrench, type LucideIcon } from "lucide-react";

/** Route paths for every page. Pages live in app/(app)/<path>/page.tsx. */
export const ROUTES = {
  overview: "/",
  map: "/map",
  fixFirst: "/fix-first",
  plan: "/plan",
  verification: "/verification",
  surveys: "/surveys",
  /** phone job card: /job?project=&survey=&finding=<fid> */
  job: "/job",
  login: "/login",
} as const;

export const NAV: { href: string; label: string; short: string; icon: LucideIcon }[] = [
  { href: ROUTES.overview, label: "Overview", short: "Overview", icon: LayoutDashboard },
  { href: ROUTES.map, label: "Map", short: "Map", icon: Map },
  { href: ROUTES.fixFirst, label: "Fix first", short: "Fix first", icon: ListOrdered },
  { href: ROUTES.plan, label: "Repair plan", short: "Plan", icon: Wrench },
  { href: ROUTES.verification, label: "Verification", short: "Verify", icon: ClipboardCheck },
  { href: ROUTES.surveys, label: "Surveys", short: "Surveys", icon: Route },
];

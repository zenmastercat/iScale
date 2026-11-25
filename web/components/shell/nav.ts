import { ClipboardCheck, FileText, LayoutDashboard, ListOrdered, Map, Route, Table2, Users, Wrench, type LucideIcon } from "lucide-react";

/** Route paths for every page. Pages live in app/(app)/<path>/page.tsx. */
export const ROUTES = {
  overview: "/",
  map: "/map",
  /** every finding; filters in the URL: ?severity=high,medium&status=open&type=pothole&segment=S003&q=&sort=-depth */
  findings: "/findings",
  fixFirst: "/fix-first",
  plan: "/plan",
  verification: "/verification",
  surveys: "/surveys",
  /** one-page council report (print / save as PDF) */
  report: "/report",
  /** team members; admins add people (e.g. a crew phone) */
  team: "/team",
  /** phone job card: /job?project=&survey=&finding=<fid> */
  job: "/job",
  login: "/login",
} as const;

/** desktopOnly: in the side rail but not the phone bottom bar (6 columns is the most that fits). */
export const NAV: { href: string; label: string; short: string; th: string; shortTh: string; icon: LucideIcon; desktopOnly?: boolean }[] = [
  { href: ROUTES.overview, label: "Overview", short: "Overview", th: "ภาพรวม", shortTh: "ภาพรวม", icon: LayoutDashboard },
  { href: ROUTES.map, label: "Map", short: "Map", th: "แผนที่", shortTh: "แผนที่", icon: Map },
  { href: ROUTES.findings, label: "Findings", short: "Findings", th: "รายการที่พบ", shortTh: "รายการ", icon: Table2, desktopOnly: true },
  { href: ROUTES.fixFirst, label: "Fix first", short: "Fix first", th: "ซ่อมก่อน", shortTh: "ซ่อมก่อน", icon: ListOrdered },
  { href: ROUTES.plan, label: "Repair plan", short: "Plan", th: "แผนซ่อม", shortTh: "แผน", icon: Wrench },
  { href: ROUTES.verification, label: "Verification", short: "Verify", th: "ตรวจผลการซ่อม", shortTh: "ตรวจผล", icon: ClipboardCheck },
  { href: ROUTES.surveys, label: "Surveys", short: "Surveys", th: "การสำรวจ", shortTh: "สำรวจ", icon: Route },
  { href: ROUTES.report, label: "Report", short: "Report", th: "รายงาน", shortTh: "รายงาน", icon: FileText, desktopOnly: true },
  { href: ROUTES.team, label: "Team", short: "Team", th: "ทีม", shortTh: "ทีม", icon: Users, desktopOnly: true },
];

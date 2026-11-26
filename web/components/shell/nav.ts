import { ClipboardCheck, FileText, LayoutDashboard, ListOrdered, Map, Route, Table2, Users, Wrench, MessageCircle, type LucideIcon } from "lucide-react";

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
  /** Civil Helper library and provider settings (the chat is the floating button) */
  helper: "/helper",
  /** team members; admins add people (e.g. a crew phone) */
  team: "/team",
  /** crew chat (XMPP + OMEMO) */
  chat: "/chat",
  /** phone job card: /job?project=&survey=&finding=<fid> */
  job: "/job",
  login: "/login",
} as const;

/** phone: "bar" = a tab in the phone bottom bar, "more" = in its More sheet (the bar fits 6 columns: 5 tabs + More). The side rail lists all. */
export const NAV: { href: string; label: string; short: string; th: string; shortTh: string; icon: LucideIcon; phone: "bar" | "more" }[] = [
  { href: ROUTES.overview, label: "Overview", short: "Overview", th: "ภาพรวม", shortTh: "ภาพรวม", icon: LayoutDashboard, phone: "bar" },
  { href: ROUTES.map, label: "Map", short: "Map", th: "แผนที่", shortTh: "แผนที่", icon: Map, phone: "bar" },
  { href: ROUTES.findings, label: "Findings", short: "Findings", th: "รายการที่พบ", shortTh: "รายการ", icon: Table2, phone: "more" },
  { href: ROUTES.fixFirst, label: "Fix first", short: "Fix first", th: "ซ่อมก่อน", shortTh: "ซ่อมก่อน", icon: ListOrdered, phone: "bar" },
  { href: ROUTES.plan, label: "Repair plan", short: "Plan", th: "แผนซ่อม", shortTh: "แผน", icon: Wrench, phone: "bar" },
  { href: ROUTES.verification, label: "Verification", short: "Verify", th: "ตรวจผลการซ่อม", shortTh: "ตรวจผล", icon: ClipboardCheck, phone: "more" },
  { href: ROUTES.surveys, label: "Surveys", short: "Surveys", th: "การสำรวจ", shortTh: "สำรวจ", icon: Route, phone: "more" },
  { href: ROUTES.report, label: "Report", short: "Report", th: "รายงาน", shortTh: "รายงาน", icon: FileText, phone: "more" },
  { href: ROUTES.team, label: "Team", short: "Team", th: "ทีม", shortTh: "ทีม", icon: Users, phone: "more" },
  { href: ROUTES.chat, label: "Chat", short: "Chat", th: "แชท", shortTh: "แชท", icon: MessageCircle, phone: "bar" },
];

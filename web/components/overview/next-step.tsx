"use client";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useT } from "@/lib/i18n";
import { useReviewCounts } from "@/lib/review-counts";
import { useWorkOrders } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

/** One next action, picked from the state: review AI findings → plan repairs → re-drive check → report. */
export function NextStep() {
  const t = useT();
  const { withSel } = useSelection();
  const { unreviewed } = useReviewCounts();
  const orders = useWorkOrders();
  if (unreviewed === null || orders.data === undefined) return null;

  let text: string;
  let action: string;
  let href: string;
  if (unreviewed > 0) {
    text = t(`${unreviewed} AI findings need an engineer's decision`, `ข้อบกพร่องจาก AI ${unreviewed} จุด รอวิศวกรตัดสินใจ`);
    action = t("Review now", "ตรวจเลย");
    href = withSel("/review");
  } else if (orders.data.length === 0) {
    text = t("Every AI finding has been reviewed. Next: plan the repairs.", "วิศวกรตรวจข้อบกพร่องจาก AI ครบแล้ว ขั้นต่อไป: วางแผนซ่อม");
    action = t("Plan the repairs", "วางแผนซ่อม");
    href = withSel("/plan");
  } else if (orders.data.some((o) => o.status !== "verified" && o.status !== "cancelled")) {
    text = t("Repairs are ordered. Drive the road again to prove they worked.", "สั่งงานซ่อมแล้ว ขับสำรวจถนนอีกครั้งเพื่อพิสูจน์ว่าซ่อมได้ผล");
    action = t("Run the re-drive check", "ตรวจด้วยการสำรวจซ้ำ");
    href = withSel("/verification");
  } else {
    text = t("All repairs verified", "ตรวจยืนยันงานซ่อมครบแล้ว");
    action = t("Open the report", "เปิดรายงาน");
    href = withSel("/report");
  }
  const done = unreviewed === 0 && orders.data.length > 0 && !orders.data.some((o) => o.status !== "verified" && o.status !== "cancelled");
  return (
    <section
      aria-label={t("Next step", "ขั้นต่อไป")}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-brand-50 px-4 py-3 md:py-2.5"
    >
      <p className="flex min-w-0 items-center gap-2 text-base font-medium text-grey-900 md:text-[15px]">
        {done && <CheckCircle2 aria-hidden className="size-5 shrink-0 text-sev-low-fg" />}
        <span><span className="text-xs font-semibold tracking-wider text-brand uppercase">{t("Next step", "ขั้นต่อไป")}</span>{" "}<span className="block sm:inline">{text}</span></span>
      </p>
      <Link
        href={href}
        className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:bg-brand/90 md:min-h-9"
      >
        {action}
        <ArrowRight aria-hidden className="size-4" />
      </Link>
    </section>
  );
}

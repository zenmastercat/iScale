"use client";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useReviewCounts } from "@/lib/review-counts";
import { useWorkOrders } from "@/lib/queries";
import { useSelection } from "@/lib/selection";

/** The short status line under each "Work" item in the side rail, from queries the pages already use.
 *  A page's entry is null (hidden) until its data has loaded. */
export function useRailStatus(): Record<string, string | null> {
  const t = useT();
  const { project } = useSelection();
  const { unreviewed, stillPresent } = useReviewCounts();
  const orders = useWorkOrders();
  const drives = project ? project.survey_list.length : null;
  const funded = orders.data ? orders.data.reduce((a, o) => a + (o.total || 0), 0) : null;
  return {
    "/surveys": drives === null ? null : t(`${drives} ${drives === 1 ? "drive" : "drives"}`, `${drives} รอบสำรวจ`),
    "/findings": unreviewed === null ? null : unreviewed > 0 ? t(`${unreviewed} to review`, `${unreviewed} รอตรวจ`) : t("all reviewed", "ตรวจครบแล้ว"),
    "/plan": funded === null ? null : orders.data!.length > 0 ? t(`${formatMoney(funded)} funded`, `งบ ${formatMoney(funded)}`) : t("no plan", "ยังไม่มีแผน"),
    "/verification": stillPresent === null ? null : stillPresent > 0 ? t(`${stillPresent} still present`, `${stillPresent} จุดยังพบอยู่`) : null,
  };
}

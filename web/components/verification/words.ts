import type { WorkOrderStatus } from "@/lib/types";

/** Label for a status; an unknown one (backend added a state) falls back to its raw code instead of throwing. */
export function woLabel(t: (en: string, th: string) => string, status: string): string {
  const w = (WO_STATUS as Record<string, [string, string] | undefined>)[status];
  return w ? t(w[0], w[1]) : status.replace(/_/g, " ");
}

/** [English, Thai] for work order statuses. */
export const WO_STATUS: Record<WorkOrderStatus, [string, string]> = {
  open: ["Open", "เปิด"],
  scheduled: ["Scheduled", "นัดหมายแล้ว"],
  completed: ["Completed", "เสร็จแล้ว"],
  verified: ["Verified", "ตรวจยืนยันแล้ว"],
  partially_verified: ["Partly verified", "ยืนยันบางส่วน"],
  cancelled: ["Cancelled", "ยกเลิก"],
};

/** Work order titles are made by the server as "N repairs"; show them in Thai when asked. */
export function woTitle(t: (en: string, th: string) => string, title: string): string {
  const m = /^(\d+) repairs?$/.exec(title);
  return m ? t(title, `${m[1]} งานซ่อม`) : title;
}

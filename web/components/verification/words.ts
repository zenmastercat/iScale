import type { WorkOrderStatus } from "@/lib/types";

/** [English, Thai] for work order statuses. */
export const WO_STATUS: Record<WorkOrderStatus, [string, string]> = {
  open: ["Open", "เปิด"],
  scheduled: ["Scheduled", "นัดหมายแล้ว"],
  completed: ["Completed", "เสร็จแล้ว"],
  verified: ["Verified", "ตรวจยืนยันแล้ว"],
  partially_verified: ["Partly verified", "ยืนยันบางส่วน"],
  cancelled: ["Cancelled", "ยกเลิก"],
};

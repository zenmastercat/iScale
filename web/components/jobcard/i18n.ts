export type Lang = "en" | "th";

export const T = {
  en: {
    title: "Job card", back: "Back", lang: "ไทย",
    location: "Location", materials: "Materials", timing: "Timing", steps: "Steps",
    photo: "No drive frame for this survey", depth: "Depth", across: "Across", missing: "Missing", cutArea: "Cut area",
    area: "Area", coords: "Coordinates", address: "Address", noAddress: "Address not available",
    method: "Method", bill: "Bill of materials", item: "Item", qty: "Qty", amount: "Amount", total: "Total",
    materialsOnly: "Materials only. Labour, equipment and traffic control are not included.",
    tools: "Tools", window: "Suggested window", traffic: "Traffic", reason: "Why then", road: "Road class",
    urgency: "Urgency", warning: "Safety", materialsList: "Materials", stepsList: "Steps",
    navigate: "Navigate", markFixed: "Mark as fixed", fixed: "Fixed", saving: "Saving…",
    fixedToast: "Marked as fixed", failToast: "Could not update the finding", noCost: "No cost estimate for this finding type.",
    missingFinding: "Choose a finding", missingHint: "Open a finding from the map and press Open job card.",
    loadError: "Could not load the job card",
    confirmTitle: "Mark this repair as fixed?", confirmBody: "The finding is recorded as fixed. You can verify it on the next survey.", cancel: "Cancel",
  },
  th: {
    title: "ใบงาน", back: "กลับ", lang: "EN",
    location: "ตำแหน่ง", materials: "วัสดุ", timing: "เวลา", steps: "ขั้นตอน",
    photo: "ไม่มีภาพจากการสำรวจ", depth: "ความลึก", across: "ความกว้าง", missing: "ปริมาตรที่หาย", cutArea: "พื้นที่ตัด",
    area: "พื้นที่", coords: "พิกัด", address: "ที่อยู่", noAddress: "ไม่มีข้อมูลที่อยู่",
    method: "วิธีซ่อม", bill: "รายการวัสดุ", item: "รายการ", qty: "จำนวน", amount: "จำนวนเงิน", total: "รวม",
    materialsOnly: "เฉพาะค่าวัสดุ ไม่รวมค่าแรง เครื่องจักร และการจัดการจราจร",
    tools: "เครื่องมือ", window: "ช่วงเวลาที่แนะนำ", traffic: "การจราจร", reason: "เหตุผล", road: "ประเภทถนน",
    urgency: "ความเร่งด่วน", warning: "ความปลอดภัย", materialsList: "วัสดุ", stepsList: "ขั้นตอน",
    navigate: "นำทาง", markFixed: "ซ่อมเสร็จแล้ว", fixed: "ซ่อมแล้ว", saving: "กำลังบันทึก…",
    fixedToast: "บันทึกว่าซ่อมแล้ว", failToast: "ไม่สามารถอัปเดตได้", noCost: "ไม่มีประมาณการสำหรับประเภทนี้",
    missingFinding: "เลือกรายการ", missingHint: "เปิดรายการจากแผนที่ แล้วกด Open job card",
    loadError: "โหลดใบงานไม่สำเร็จ",
    confirmTitle: "ยืนยันว่าซ่อมเสร็จแล้ว?", confirmBody: "ระบบจะบันทึกว่าซ่อมแล้ว และตรวจสอบได้ในการสำรวจรอบถัดไป", cancel: "ยกเลิก",
  },
} as const;

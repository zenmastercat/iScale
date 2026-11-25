"use client";
/*
 * "How we measure": the rules behind every number, taken from the backend code
 * (civil/analysis/condition.py, detect.py, civil/priority.py, planning.py, verify.py). Keep in sync.
 */
import { Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { CONDITION_BANDS } from "@/lib/condition";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-5 mb-1.5 text-sm font-semibold text-grey-900 first:mt-0">{children}</h3>;
}

function Rules({ rows, head }: { rows: [string, string, string, string][]; head: [string, string, string, string] }) {
  return (
    <table className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b text-xs text-grey-600">
          {head.map((h, i) => (
            <th key={i} scope="col" className="py-1 pr-2 font-semibold">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r[0]} className="border-b last:border-0">
            <th scope="row" className="py-1 pr-2 font-normal">{r[0]}</th>
            <td className="num py-1 pr-2 text-sev-high-fg">{r[1]}</td>
            <td className="num py-1 pr-2 text-sev-medium-fg">{r[2]}</td>
            <td className="num py-1 text-sev-low-fg">{r[3]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function HowWeMeasure({ className }: { className?: string }) {
  const t = useT();
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" className={cn("h-11 md:h-9", className)} />}>
        <Info aria-hidden />
        {t("How we measure", "วิธีการวัด")}
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("How these numbers are made", "ตัวเลขเหล่านี้มาจากไหน")}</DialogTitle>
          <DialogDescription>
            {t(
              "A phone on a car records the road surface in 3D. Everything below is measured from that surface; nothing is typed in by hand unless it says “Tagged by hand”.",
              "โทรศัพท์บนรถบันทึกผิวถนนแบบ 3 มิติ ทุกค่าด้านล่างวัดจากผิวถนนนั้น ไม่มีการกรอกเอง เว้นแต่ระบุว่า “บันทึกด้วยมือ”",
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="text-sm text-grey-800">
          <H>{t("Condition index (0–100, per 25 m segment)", "ดัชนีสภาพถนน (0–100 ต่อช่วง 25 ม.)")}</H>
          <p>
            {t(
              "Start at 100. Each open defect deducts points: 4 (low), 10 (medium) or 20 (high), times a factor for the defect type (pothole 1.0, sunken manhole 0.4 …), times how much of the segment's surface it covers. The biggest deduct counts fully, the next 70 %, then 49 % … Fixed and verified defects no longer count. The route score is the length-weighted average.",
              "เริ่มที่ 100 ข้อบกพร่องที่ยังไม่ซ่อมแต่ละจุดหักคะแนน 4 (ต่ำ) 10 (กลาง) หรือ 20 (สูง) คูณค่าตามชนิด (หลุมบ่อ 1.0 ฝาท่อทรุด 0.4 …) และคูณตามพื้นที่ที่เสียหายในช่วงนั้น จุดที่หักมากที่สุดนับเต็ม จุดถัดไป 70 % แล้ว 49 % … จุดที่ซ่อมแล้วไม่นับ คะแนนทั้งเส้นเฉลี่ยตามความยาว",
            )}
          </p>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {CONDITION_BANDS.map((b) => (
              <span key={b.rating} className="inline-flex items-center gap-1.5 text-[13px]">
                <span aria-hidden className={cn("size-2.5 rounded-[2px]", b.bg)} />
                {b.label} <span className="num text-muted-foreground">{b.range}</span>
              </span>
            ))}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {t(
              "PCI-like, a simplified deduct model, not a certified ASTM D6433 PCI. The tables can be tuned to an agency's own data.",
              "คล้าย PCI เป็นแบบจำลองหักคะแนนอย่างง่าย ไม่ใช่ PCI ตามมาตรฐาน ASTM D6433 ปรับตารางให้ตรงกับข้อมูลของหน่วยงานได้",
            )}
          </p>

          <H>{t("Severity", "ระดับความรุนแรง")}</H>
          <Rules
            head={[t("Defect", "ชนิด"), t("High", "สูง"), t("Medium", "กลาง"), t("Low", "ต่ำ")]}
            rows={[
              [t("Pothole", "หลุมบ่อ"), t("≥ 5 cm deep and ≥ 0.45 m across", "ลึก ≥ 5 ซม. และกว้าง ≥ 0.45 ม."), t("one of the two", "อย่างใดอย่างหนึ่ง"), t("smaller", "เล็กกว่านั้น")],
              [t("Depression, sunken cover", "แอ่ง ฝาท่อทรุด"), "≥ 5 cm", "≥ 3 cm", "< 3 cm"],
              [t("Heave / bump", "ผิวโป่ง"), "≥ 5 cm", "≥ 3.5 cm", "< 3.5 cm"],
              [t("Sidewalk trip step", "ขอบสะดุดทางเท้า"), "≥ 2.5 cm", "≥ 1.3 cm", "< 1.3 cm"],
              [t("Rough surface (texture)", "ผิวขรุขระ"), "> 12 mm", "> 9 mm", "≤ 9 mm"],
            ]}
          />

          <H>{t("Fix first ranking", "ลำดับการซ่อม")}</H>
          <p>
            {t(
              "Priority = severity (high 3.5, medium 2, low 1) × safety (pothole and trip step 1.6, sunken cover 1.3, heave 1.2, depression 1.1, others 1.0) × traffic on that road.",
              "ลำดับ = ความรุนแรง (สูง 3.5 กลาง 2 ต่ำ 1) × ความปลอดภัย (หลุมบ่อและขอบสะดุด 1.6 ฝาท่อทรุด 1.3 ผิวโป่ง 1.2 แอ่ง 1.1 อื่น ๆ 1.0) × ปริมาณจราจรของถนนนั้น",
            )}
          </p>

          <H>{t("Costs", "ค่าใช้จ่าย")}</H>
          <p>
            {t(
              "Repair plan: measured quantity (+30 % margin) × the agency's unit rate per repair action, plus one mobilisation fee per work order. Job card: the bill of materials for that one repair (asphalt bags, tack coat, base) at local prices. All amounts in Thai baht; the demo rates are placeholders.",
              "แผนซ่อม: ปริมาณที่วัดได้ (+30 %) × ราคาต่อหน่วยของหน่วยงาน บวกค่าเคลื่อนย้ายครั้งเดียวต่อใบสั่งงาน ใบงาน: รายการวัสดุของจุดนั้น (ถุงแอสฟัลต์ แทคโค้ท หินคลุก) ราคาท้องถิ่น ทุกจำนวนเป็นบาท อัตราในตัวอย่างเป็นค่าสมมติ",
            )}
          </p>

          <H>{t("Verification", "การตรวจสอบผลซ่อม")}</H>
          <p>
            {t(
              "After the repairs, drive the street again. At each repaired spot: not detected any more → Verified; still detected → Still present (with its new size); no data at that spot → Not covered, drive it again.",
              "หลังซ่อม ขับรถเก็บข้อมูลอีกครั้ง แต่ละจุด: ตรวจไม่พบแล้ว → ซ่อมแล้วจริง ยังตรวจพบ → ยังอยู่ (พร้อมขนาดใหม่) ไม่มีข้อมูลที่จุดนั้น → ไม่ครอบคลุม ให้ขับซ้ำ",
            )}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

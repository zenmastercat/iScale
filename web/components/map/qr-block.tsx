"use client";
import { Copy } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** "Open on a phone": QR of the absolute job card URL plus a Copy link button. Desktop only. */
export function QrBlock({ findingId }: { findingId: string }) {
  const t = useT();
  const { withSel } = useSelection();
  const [url, setUrl] = useState("");
  const [img, setImg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const path = withSel("/job", { finding: findingId });
  useEffect(() => {
    const abs = window.location.origin + path;
    let live = true;
    QRCode.toDataURL(abs, { margin: 1, width: 240 })
      .then((d) => {
        if (!live) return;
        setUrl(abs);
        setImg(d);
        setFailed(false);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [path]);

  const local = url ? LOCAL_HOSTS.has(new URL(url).hostname) : false;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t("Link copied", "คัดลอกลิงก์แล้ว"));
    } catch {
      toast.error(t("Could not copy the link", "คัดลอกลิงก์ไม่สำเร็จ"));
    }
  };

  return (
    <section className="hidden flex-col gap-2 border-t pt-3 md:flex" aria-label={t("Open on a phone", "เปิดบนโทรศัพท์")}>
      <h3 className="text-sm font-semibold">{t("Open on a phone", "เปิดบนโทรศัพท์")}</h3>
      <div className="flex items-center gap-3">
        {img ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={img} alt={t("QR code for the job card", "คิวอาร์โค้ดของใบงาน")} width={112} height={112} className="size-28 rounded-md border" />
        ) : (
          <div className="size-28 rounded-md border bg-grey-50" aria-hidden />
        )}
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground">{t("Scan to open this job card on a crew phone.", "สแกนเพื่อเปิดใบงานนี้บนโทรศัพท์ของทีมช่าง")}</p>
          <Button type="button" variant="outline" className="min-h-8" disabled={!url} onClick={copy}>
            <Copy className="size-4" aria-hidden />
            {t("Copy link", "คัดลอกลิงก์")}
          </Button>
        </div>
      </div>
      {failed && <p className="text-xs text-muted-foreground">{t("Could not draw the QR code.", "สร้างคิวอาร์โค้ดไม่ได้")}</p>}
      {local && (
        <p className="text-xs text-muted-foreground">
          {t(
            "Phones can't reach localhost. Open this page using the laptop's network address (see PITCH.md).",
            "โทรศัพท์เข้า localhost ไม่ได้ ให้เปิดหน้านี้ด้วยที่อยู่เครือข่ายของแล็ปท็อป (ดู PITCH.md)",
          )}
        </p>
      )}
    </section>
  );
}

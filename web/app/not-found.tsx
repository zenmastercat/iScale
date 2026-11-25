"use client";
import Link from "next/link";
import { Logo } from "@/components/shell/logo";
import { useT } from "@/lib/i18n";

export default function NotFound() {
  const t = useT();
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-grey-50 px-6 text-center">
      <span className="rounded-md bg-sidebar px-3 py-2">
        <Logo />
      </span>
      <div>
        <h1 className="text-2xl font-semibold text-brand">{t("Page not found", "ไม่พบหน้านี้")}</h1>
        <p className="mt-2 text-muted-foreground">{t("The link may be old or mistyped.", "ลิงก์อาจเก่าหรือพิมพ์ผิด")}</p>
      </div>
      <Link href="/" className="inline-flex min-h-11 items-center rounded-lg bg-primary px-5 font-medium text-primary-foreground hover:bg-primary/90">
        {t("Go to the overview", "ไปที่ภาพรวม")}
      </Link>
    </main>
  );
}

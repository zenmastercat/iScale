"use client";
import { LibraryPanel } from "@/components/helper/library-panel";
import { PageHeader } from "@/components/shared/page-header";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

/** Library and provider settings for Civil Helper. The chat itself is the floating button on every page. */
export default function HelperPage() {
  const t = useT();
  const { project } = useSelection();
  return (
    <>
      <PageHeader title={t("Civil Helper: library and settings", "ผู้ช่วยวิศวกร: คลังเอกสารและการตั้งค่า")} crumb={project?.name} />
      <LibraryPanel />
    </>
  );
}

"use client";
import { AskPanel } from "@/components/helper/ask-panel";
import { LibraryPanel } from "@/components/helper/library-panel";
import { PageHeader } from "@/components/shared/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

export default function HelperPage() {
  const t = useT();
  const { project } = useSelection();
  return (
    <>
      <PageHeader title={t("Civil Helper", "ผู้ช่วยวิศวกร")} crumb={project?.name} />
      <Tabs defaultValue="ask">
        <TabsList>
          <TabsTrigger value="ask" className="min-h-11 md:min-h-9">{t("Ask", "ถาม")}</TabsTrigger>
          <TabsTrigger value="library" className="min-h-11 md:min-h-9">{t("Library and settings", "คลังเอกสารและการตั้งค่า")}</TabsTrigger>
        </TabsList>
        <TabsContent value="ask" className="mt-4"><AskPanel /></TabsContent>
        <TabsContent value="library" className="mt-4"><LibraryPanel /></TabsContent>
      </Tabs>
    </>
  );
}

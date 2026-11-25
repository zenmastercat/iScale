"use client";
import { Database, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoButton } from "@/components/shared/demo-button";
import { EmptyState } from "@/components/shared/empty-state";
import { ProcessingState } from "@/components/shared/processing-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelection } from "@/lib/selection";
import { useT } from "@/lib/i18n";

/**
 * Wrap a page body that needs a processed survey. Renders loading / no project / processing /
 * failed states itself and only renders children when the selected survey is "done".
 */
export function SurveyGate({ children }: { children: React.ReactNode }) {
  const { projects, projectsLoading, projectId, project, survey, loadError, retryLoad } = useSelection();
  const t = useT();
  if (loadError)
    return (
      <div role="alert">
        <EmptyState
          icon={TriangleAlert}
          title={t("Could not load the project", "โหลดโครงการไม่สำเร็จ")}
          description={`${loadError.message}. ${t("Check that the iScale server is running.", "ตรวจสอบว่าเซิร์ฟเวอร์ iScale ทำงานอยู่")}`}
          action={
            <Button className="h-11 px-4" onClick={retryLoad}>
              {t("Retry", "ลองอีกครั้ง")}
            </Button>
          }
        />
      </div>
    );
  if (projectsLoading || (projectId && !project)) return <Skeleton className="h-64 w-full" />;
  if (!projects?.length || !projectId)
    return (
      <EmptyState
        icon={Database}
        title={t("No projects yet", "ยังไม่มีโครงการ")}
        description={t("Load the demo street to see iScale with sample data: two drives of the same road, before and after repairs.", "โหลดถนนตัวอย่างเพื่อดู iScale ด้วยข้อมูลตัวอย่าง: การขับสำรวจถนนเดียวกันสองครั้ง ก่อนและหลังซ่อม")}
        action={<DemoButton />}
      />
    );
  if (!survey)
    return <EmptyState icon={Database} title={t("This project has no surveys yet", "โครงการนี้ยังไม่มีการสำรวจ")} description={t("Add a drive to start.", "เพิ่มการขับสำรวจเพื่อเริ่มต้น")} />;
  if (survey.status !== "done") return <ProcessingState survey={survey} />;
  return <>{children}</>;
}

"use client";
import { Printer } from "lucide-react";
import { ReportSheet } from "@/components/report/report-sheet";
import { PageHeader } from "@/components/shared/page-header";
import { SurveyGate } from "@/components/shared/survey-gate";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";

export default function ReportPage() {
  const t = useT();
  const { project, survey } = useSelection();
  return (
    <>
      {/* A4, small margins; the shell chrome carries print:hidden */}
      <style>{"@media print{@page{size:A4;margin:12mm}body{background:#fff!important}}"}</style>
      <PageHeader
        className="print:hidden"
        title={t("Report", "รายงาน")}
        crumb={project && survey ? `${project.name} / ${survey.name}` : undefined}
        actions={
          survey?.status === "done" ? (
            <Button className="min-h-11" onClick={() => window.print()}>
              <Printer aria-hidden />
              {t("Print or save as PDF", "พิมพ์ หรือบันทึกเป็น PDF")}
            </Button>
          ) : null
        }
      />
      <SurveyGate>
        <div className="rounded-lg bg-grey-100 p-2 md:p-6 print:bg-white print:p-0">
          <ReportSheet />
        </div>
      </SurveyGate>
    </>
  );
}

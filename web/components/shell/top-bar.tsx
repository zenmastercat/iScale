"use client";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { FlaskConical, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { signOut } from "@/lib/auth";
import { useLang, useT } from "@/lib/i18n";
import { useAuthState } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import { Logo } from "./logo";

const STATUS_SUFFIX: Record<string, string> = { queued: " (queued)", running: " (processing)", error: " (failed)" };

/** Project + survey pickers, "Sample data" badge, user + sign out. */
export function TopBar() {
  const { projects, projectId, project, surveyId, isDemo, setProject, setSurvey } = useSelection();
  const { data: auth } = useAuthState();
  const qc = useQueryClient();
  const { lang, setLang } = useLang();
  const t = useT();
  // the crew job card is a full-screen phone page (it has its own header); keep the bar on md+
  const fullScreenOnPhone = usePathname()?.startsWith("/job");

  const projectItems = (projects ?? []).map((p) => ({ value: p.id, label: p.name }));
  const surveyItems = (project?.survey_list ?? []).map((s) => ({
    value: s.id,
    label: `${s.name}${s.id === project?.baseline ? " · baseline" : ""}${STATUS_SUFFIX[s.status] ?? ""}`,
  }));

  return (
    <header className={`sticky top-0 z-30 border-b bg-card/95 backdrop-blur ${fullScreenOnPhone ? "hidden md:block" : ""}`}>
      <div className="flex min-h-14 flex-wrap items-center gap-2 px-4 py-2 md:px-8">
        <span className="order-1 rounded bg-sidebar px-2 py-1 md:hidden">
          <Logo className="text-base" />
        </span>
        <div className="order-3 flex w-full flex-wrap items-center gap-2 md:order-2 md:w-auto">
        <label className="sr-only" htmlFor="project-picker">
          Project
        </label>
        <Select items={projectItems} value={projectId} onValueChange={(v) => v && setProject(v as string)}>
          <SelectTrigger id="project-picker" aria-label="Project" className="h-11 max-w-[16rem] min-w-0 flex-1 md:h-9 md:min-w-40 md:flex-none">
            <SelectValue placeholder="Choose a project" />
          </SelectTrigger>
          <SelectContent>
            {projectItems.map((p) => (
              <SelectItem key={p.value} value={p.value}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="sr-only" htmlFor="survey-picker">
          Survey
        </label>
        <Select items={surveyItems} value={surveyId} onValueChange={(v) => v && setSurvey(v as string)} disabled={!project}>
          <SelectTrigger id="survey-picker" aria-label="Survey" className="h-11 max-w-[16rem] min-w-0 flex-1 md:h-9 md:min-w-40 md:flex-none">
            <SelectValue placeholder="Choose a survey" />
          </SelectTrigger>
          <SelectContent>
            {surveyItems.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isDemo && (
          <Tooltip>
            <TooltipTrigger
              render={
                <span className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-sev-medium/40 bg-sev-medium-bg px-2.5 text-sm font-medium text-sev-medium-fg" />
              }
            >
              <FlaskConical aria-hidden className="size-4" />
              Sample data
            </TooltipTrigger>
            <TooltipContent>Synthetic demo street. Figures are not field results.</TooltipContent>
          </Tooltip>
        )}
        </div>
        <div className="order-2 ml-auto flex items-center gap-2 md:order-3">
          {auth?.user && (
            <span className="hidden text-sm text-muted-foreground lg:inline">
              {auth.user.display_name} · {auth.user.company}
            </span>
          )}
          <Button
            variant="outline"
            className="h-11 min-w-11 px-3 md:h-9"
            lang={lang === "th" ? "en" : "th"}
            aria-label={lang === "th" ? "Switch to English" : "เปลี่ยนเป็นภาษาไทย"}
            onClick={() => setLang(lang === "th" ? "en" : "th")}
          >
            {lang === "th" ? "EN" : "ไทย"}
          </Button>
          <Button
            variant="ghost"
            size="icon-lg"
            className="size-11"
            aria-label={t("Sign out", "ออกจากระบบ")}
            onClick={async () => {
              await signOut().catch(() => {});
              qc.clear();
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination
              window.location.assign("/login");
            }}
          >
            <LogOut aria-hidden />
          </Button>
        </div>
      </div>
    </header>
  );
}

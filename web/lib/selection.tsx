"use client";
/*
 * The current project and survey, shared by every page under (app).
 * Source of truth is the URL (?project=<pid>&survey=<sid>) so links and reloads keep it;
 * the last choice is remembered in localStorage for the next visit.
 * Defaults: last-used (or newest) project, then its baseline survey (or the first one).
 */
import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo } from "react";
import { getProject, listProjects, qk } from "@/lib/api";
import type { Project, ProjectSummary, Survey } from "@/lib/types";

const LS_KEY = "iscale.selection";

export interface Selection {
  projects: ProjectSummary[] | undefined;
  projectsLoading: boolean;
  projectId: string | null;
  surveyId: string | null;
  /** full project (with survey_list), once loaded */
  project: Project | undefined;
  /** the selected survey record, once the project is loaded */
  survey: Survey | undefined;
  /** surveys of the project other than the selected one (e.g. the after-repairs drive) */
  otherSurveys: Survey[];
  /** true for the built-in synthetic demo project */
  isDemo: boolean;
  setProject: (pid: string) => void;
  setSurvey: (sid: string) => void;
  /** href with the current ?project&survey appended; use for every in-app <Link> */
  withSel: (path: string, extra?: Record<string, string>) => string;
}

const Ctx = createContext<Selection | null>(null);

export function useSelection(): Selection {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSelection must be used inside <SelectionProvider> (the (app) layout)");
  return v;
}

/** Demo projects are created by POST /api/demo with this name. */
export const isDemoProject = (p?: { name: string } | null) => !!p && p.name.startsWith("Demo district");

function remembered(): { project?: string; survey?: string } {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
  } catch {
    return {};
  }
}

export function SelectionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const urlProject = params.get("project");
  const urlSurvey = params.get("survey");

  const projectsQ = useQuery({ queryKey: qk.projects, queryFn: listProjects });
  const projects = projectsQ.data;

  const projectId = useMemo(() => {
    if (!projects) return urlProject;
    if (urlProject && projects.some((p) => p.id === urlProject)) return urlProject;
    const last = remembered().project;
    if (last && projects.some((p) => p.id === last)) return last;
    const newest = [...projects].sort((a, b) => b.created - a.created)[0];
    return newest?.id ?? null;
  }, [projects, urlProject]);

  const projectQ = useQuery({
    queryKey: qk.project(projectId ?? ""),
    queryFn: () => getProject(projectId!),
    enabled: !!projectId,
    // keep polling while any survey is still processing
    refetchInterval: (q) =>
      q.state.data?.survey_list.some((s) => s.status === "queued" || s.status === "running") ? 2000 : false,
  });
  const project = projectQ.data?.id === projectId ? projectQ.data : undefined;

  const surveyId = useMemo(() => {
    if (!project) return urlSurvey;
    const ids = project.survey_list.map((s) => s.id);
    if (urlSurvey && ids.includes(urlSurvey)) return urlSurvey;
    const last = remembered();
    if (last.project === project.id && last.survey && ids.includes(last.survey)) return last.survey;
    return project.baseline && ids.includes(project.baseline) ? project.baseline : (ids[0] ?? null);
  }, [project, urlSurvey]);

  const survey = project?.survey_list.find((s) => s.id === surveyId);
  const otherSurveys = project?.survey_list.filter((s) => s.id !== surveyId) ?? [];

  const push = useCallback(
    (pid: string | null, sid: string | null) => {
      const q = new URLSearchParams(params.toString());
      if (pid) q.set("project", pid);
      else q.delete("project");
      if (sid) q.set("survey", sid);
      else q.delete("survey");
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  // reflect resolved defaults in the URL and remember them
  useEffect(() => {
    if (!projectId) return;
    if (project && surveyId) localStorage.setItem(LS_KEY, JSON.stringify({ project: projectId, survey: surveyId }));
    if (projectId !== urlProject || (surveyId && surveyId !== urlSurvey)) push(projectId, surveyId);
  }, [projectId, surveyId, project, urlProject, urlSurvey, push]);

  const value: Selection = {
    projects,
    projectsLoading: projectsQ.isLoading,
    projectId,
    surveyId,
    project,
    survey,
    otherSurveys,
    isDemo: isDemoProject(project ?? projects?.find((p) => p.id === projectId)),
    setProject: (pid) => push(pid, null),
    setSurvey: (sid) => push(projectId, sid),
    withSel: (path, extra) => {
      const q = new URLSearchParams();
      if (projectId) q.set("project", projectId);
      if (surveyId) q.set("survey", surveyId);
      for (const [k, v] of Object.entries(extra ?? {})) q.set(k, v);
      const s = q.toString();
      return s ? `${path}?${s}` : path;
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

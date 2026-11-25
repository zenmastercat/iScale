/*
 * The only way the app talks to the backend. Every call goes through api(), which
 *  - sends X-Civil-Scan: 1 on POST/PATCH/PUT/DELETE (the server answers 403 without it),
 *  - sends/parses JSON (FormData bodies are passed through untouched),
 *  - throws ApiError with the server's `detail` message on any non-2xx,
 *  - on 401 (signed out) sends the browser to /login, except for /api/auth/* calls.
 * Paths are same-origin (/api/...): the dev server and scripts/serve.mjs proxy them to FastAPI.
 */
import type {
  Analysis,
  AuthState,
  Challenge,
  Finding,
  FindingStatus,
  JobCard,
  Meta,
  Plan,
  Priority,
  Project,
  ProjectSummary,
  SegmentPlan,
  Severity,
  SpotPlan,
  Survey,
  User,
  Verification,
  WorkOrder,
  WorkOrderStatus,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Json = Record<string, unknown> | unknown[];

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** object → JSON body; FormData → multipart */
  body?: Json | FormData;
  /** query string params; undefined/null values are dropped */
  query?: Record<string, string | number | boolean | null | undefined>;
}

const LOGIN_PATH = "/login";

function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith(LOGIN_PATH)) return;
  const next = window.location.pathname + window.location.search;
  // full reload on purpose: drops every cached query of the signed-out user
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`${LOGIN_PATH}?next=${encodeURIComponent(next)}`);
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { body, query, headers, method = body !== undefined ? "POST" : "GET", ...rest } = opts;
  let url = path.startsWith("/api") ? path : `/api${path.startsWith("/") ? "" : "/"}${path}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null) qs.set(k, String(v));
    const s = qs.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const h = new Headers(headers);
  if (method !== "GET" && method !== "HEAD") h.set("X-Civil-Scan", "1");
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    h.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }
  h.set("Accept", "application/json");

  const res = await fetch(url, { ...rest, method, headers: h, body: payload, credentials: "same-origin" });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith("/api/auth/")) redirectToLogin();
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail: unknown }).detail
        : typeof data === "string" && data
          ? data
          : res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

/**
 * One path segment from an id. Ids can come from the URL (?finding=...), so a crafted value must not
 * reach another endpoint: "/", "?", "#" are percent-encoded and "." / ".." are refused.
 */
export function seg(v: string | number): string {
  const s = String(v);
  if (!s || s === "." || s === "..") throw new ApiError(400, `invalid id ${JSON.stringify(s)}`);
  return encodeURIComponent(s);
}

/** Tagged template for API paths: every ${value} goes through seg(). Use it for every new endpoint. */
const p = (parts: TemplateStringsArray, ...vals: (string | number)[]) =>
  parts.reduce((out, part, i) => out + part + (i < vals.length ? seg(vals[i]) : ""), "");

// --- auth (used by lib/auth.ts) -------------------------------------------------------------
export const getAuthState = () => api<AuthState>("/api/auth/state");
export const postChallenge = (username: string) => api<Challenge>("/api/auth/challenge", { body: { username } });
export const postLogin = (b: { username: string; nonce: string; signature: string; public_key: string }) =>
  api<{ user: User }>("/api/auth/login", { body: b });
export const postSetup = (b: { company: string; username: string; display_name: string }) =>
  api<{ ok: true; username: string }>("/api/auth/setup", { body: b });
export const postRegister = (b: {
  kind: "company" | "join" | "individual";
  username: string;
  display_name: string;
  public_key: string;
  company?: string;
  join_code?: string;
}) => api<unknown>("/api/auth/register", { body: b });
export const postLogout = () => api<{ ok: true }>("/api/auth/logout", { body: {} });

// --- team (civil/auth.py; admin only for writes) ---------------------------------------------
/** Members of my company (User shape). */
export const listTeam = () => api<User[]>("/api/team");
/** Admin: add a member. They claim the username on their own device at first sign-in. */
export const addMember = (b: { username: string; display_name: string; role: "engineer" | "admin" }) =>
  api<User>("/api/team", { body: b });
/** Admin: unbind a member's device so they can sign in on a new one. */
export const resetMemberDevice = (username: string) =>
  api<User>(p`/api/team/${username}/reset-device`, { method: "POST" });

// --- meta ----------------------------------------------------------------------------------
export const getMeta = () => api<Meta>("/api/meta");

// --- projects & surveys ----------------------------------------------------------------------
export const listProjects = () => api<ProjectSummary[]>("/api/projects");
export const getProject = (pid: string) => api<Project>(p`/api/projects/${pid}`);
export const createProject = (name: string, origin?: { lat: number; lon: number }) =>
  api<ProjectSummary>("/api/projects", { body: origin ? { name, origin_lat: origin.lat, origin_lon: origin.lon } : { name } });

/**
 * Where the demo street sits. The synthetic drive (civil/decoders/demo.py) is a fixed L: 140 m due east, then
 * 100 m due north, measured from the project origin, and it can't be rotated. POST /api/demo uses a default
 * origin where that L crosses buildings; this origin puts it on real roads: Pracha Rat Sai 2 Road eastbound,
 * then left onto Pracha Rat Sai 1 Road (Bang Sue), found by matching the L to OpenStreetMap centrelines.
 */
export const DEMO_ORIGIN = { lat: 13.806486, lon: 100.520277 };

/**
 * Same as POST /api/demo (project "Demo district (synthetic)", a baseline and an after-repairs survey, processing
 * starts at once), but at DEMO_ORIGIN so the route follows real streets on the map.
 */
/** Imports the recorded Sukhumvit pothole run as a finished survey (POST /api/demo/sukhumvit). */
export const createSukhumvitDemo = () => api<ProjectSummary>("/api/demo/sukhumvit", { method: "POST" });

export async function createDemo(): Promise<ProjectSummary> {
  const proj = await createProject("Demo district (synthetic)", DEMO_ORIGIN);
  const survey = (name: string, repaired: boolean) => {
    const f = new FormData();
    f.set("name", name);
    f.set("decoder", "demo");
    f.set("params", JSON.stringify({ repaired }));
    return createSurvey(proj.id, f);
  };
  const before = await survey("Baseline drive", false);
  await survey("After repairs", true);
  return setBaseline(proj.id, before.id);
}
export const getSurvey = (pid: string, sid: string) => api<Survey>(p`/api/projects/${pid}/surveys/${sid}`);
export const setBaseline = (pid: string, sid: string) =>
  api<ProjectSummary>(p`/api/projects/${pid}/baseline/${sid}`, { method: "POST" });
export const retrySurvey = (pid: string, sid: string) =>
  api<Survey>(p`/api/projects/${pid}/surveys/${sid}/retry`, { method: "POST" });
/** multipart: name, decoder, params (JSON string), files[] */
export const createSurvey = (pid: string, form: FormData) =>
  api<Survey>(p`/api/projects/${pid}/surveys`, { body: form });

/** Poll a survey until it is done or errored. Resolves with the final survey. */
export async function waitForSurvey(
  pid: string,
  sid: string,
  { intervalMs = 1500, timeoutMs = 300_000, onProgress }: { intervalMs?: number; timeoutMs?: number; onProgress?: (s: Survey) => void } = {},
): Promise<Survey> {
  const t0 = Date.now();
  for (;;) {
    const s = await getSurvey(pid, sid);
    onProgress?.(s);
    if (s.status === "done" || s.status === "error") return s;
    if (Date.now() - t0 > timeoutMs) throw new ApiError(408, "survey is taking too long");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// --- analysis & findings ---------------------------------------------------------------------
export const getAnalysis = (pid: string, sid: string) => api<Analysis>(p`/api/projects/${pid}/surveys/${sid}/analysis`);
export const patchFinding = (
  pid: string,
  sid: string,
  fid: string,
  patch: { status?: FindingStatus; severity?: Severity; type?: string; note?: string },
) => api<Finding>(p`/api/projects/${pid}/surveys/${sid}/findings/${fid}`, { method: "PATCH", body: patch });
export const addFinding = (
  pid: string,
  sid: string,
  f: { type: string; x: number; y: number; z?: number; severity?: Severity; note?: string; size_m?: number },
) => api<Finding>(p`/api/projects/${pid}/surveys/${sid}/findings`, { body: f });
export const getJobCard = (pid: string, sid: string, fid: string) =>
  api<JobCard>(p`/api/projects/${pid}/surveys/${sid}/findings/${fid}/card`);
/** Plain URL for <a href download>: csv | geojson | ply */
export const exportUrl = (pid: string, sid: string, fmt: "csv" | "geojson" | "ply") =>
  p`/api/projects/${pid}/surveys/${sid}/export.${fmt}`;
/** Plain URL for <img src> of a drive frame (JobCard.location.photo.url is already this). */
export const frameUrl = (pid: string, sid: string, n: number) => p`/api/projects/${pid}/surveys/${sid}/frames/${n}`;

// --- planning ----------------------------------------------------------------------------------
export function getPlan(pid: string, sid: string, mode: "spot", budget?: number | null): Promise<SpotPlan>;
export function getPlan(pid: string, sid: string, mode: "segment", budget?: number | null): Promise<SegmentPlan>;
export function getPlan(pid: string, sid: string, mode: "spot" | "segment", budget?: number | null): Promise<Plan>;
export function getPlan(pid: string, sid: string, mode: "spot" | "segment" = "spot", budget?: number | null) {
  return api<Plan>(p`/api/projects/${pid}/surveys/${sid}/plan`, { query: { mode, budget: budget || undefined } });
}
/** "Fix first": survey defects (and shared pins nearby), ranked by severity x safety x traffic. */
export const getPriority = (pid: string, sid: string, limit = 100) =>
  api<Priority>("/api/priority", { query: { project: pid, survey: sid, limit } });

// --- work orders ---------------------------------------------------------------------------------
export const listWorkOrders = (pid: string) => api<WorkOrder[]>(p`/api/projects/${pid}/workorders`);
export const createWorkOrder = (pid: string, b: { survey_id: string; finding_ids: string[]; title?: string }) =>
  api<WorkOrder>(p`/api/projects/${pid}/workorders`, { body: b });
export const patchWorkOrder = (pid: string, wid: string, status: WorkOrderStatus) =>
  api<WorkOrder>(p`/api/projects/${pid}/workorders/${wid}`, { method: "PATCH", body: { status } });

// --- verification ------------------------------------------------------------------------------------
export const getVerification = (pid: string) => api<Verification | null>(p`/api/projects/${pid}/verification`);
export const runVerify = (pid: string, b: { before: string; after: string; workorder_id?: string | null }) =>
  api<Verification>(p`/api/projects/${pid}/verify`, { body: b });

// --- TanStack Query keys (use these so invalidation works across pages) ----------------------------
export const qk = {
  authState: ["auth", "state"] as const,
  team: ["team"] as const,
  meta: ["meta"] as const,
  projects: ["projects"] as const,
  project: (pid: string) => ["project", pid] as const,
  survey: (pid: string, sid: string) => ["project", pid, "survey", sid] as const,
  analysis: (pid: string, sid: string) => ["project", pid, "survey", sid, "analysis"] as const,
  plan: (pid: string, sid: string, mode: string, budget?: number | null) =>
    ["project", pid, "survey", sid, "plan", mode, budget ?? null] as const,
  priority: (pid: string, sid: string) => ["project", pid, "survey", sid, "priority"] as const,
  jobCard: (pid: string, sid: string, fid: string) => ["project", pid, "survey", sid, "card", fid] as const,
  workOrders: (pid: string) => ["project", pid, "workorders"] as const,
  verification: (pid: string) => ["project", pid, "verification"] as const,
};

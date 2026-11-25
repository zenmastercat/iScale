import { api, seg } from "@/lib/api";

export interface HelperSource {
  n: number;
  title: string;
  page: number | null;
  doc_id: string | null;
  snippet: string;
}
export interface HelperReply {
  reply: string;
  by: "rules" | "helper";
  highlight: string[];
  segments: string[];
  plan: { mode: string; items: { finding_id: string }[] } | null;
  sources?: HelperSource[];
  model?: string;
  seconds?: number;
}
export interface HelperStatus {
  type: string;
  model_setting: string;
  embed_model: string | null;
  documents: number;
  reachable: boolean;
  model?: string;
  error?: string;
}
export interface LibraryDoc {
  id: string;
  title: string;
  chunks: number;
  embedded: number | boolean;
  uploader: string | null;
}
export interface HelperSettings {
  type: string;
  base_url: string;
  model: string;
  embed_model: string;
  has_key: boolean;
}

export const helperStatus = () => api<HelperStatus>("/api/helper/status");

/** Survey questions go to the fixed rules (and fall through to the helper); with no project, straight to the helper. */
export async function askHelper(text: string, projectId: string | null, surveyId: string | null): Promise<HelperReply> {
  if (projectId) {
    return api<HelperReply>(`/api/projects/${seg(projectId)}/chat`, { body: { message: text, survey_id: surveyId } });
  }
  const f = await api<{ answer: string; sources: HelperSource[]; model: string; seconds: number }>("/api/helper/ask", { body: { question: text } });
  return { reply: f.answer, by: "helper", highlight: [], segments: [], plan: null, sources: f.sources, model: f.model, seconds: f.seconds };
}

export const listLibrary = () => api<LibraryDoc[]>("/api/library");
export const uploadDoc = (f: FormData) => api<LibraryDoc>("/api/library", { body: f });
export const deleteDoc = (id: string) => api(`/api/library/${seg(id)}`, { method: "DELETE" });
export const reindexLibrary = () => api<{ chunks: number }>("/api/library/reindex", { method: "POST", body: {} });
export const getHelperSettings = () => api<{ helper: HelperSettings }>("/api/settings");
/** api_key is write-only: omit it to keep the saved key. The server never returns it. */
export const putHelperSettings = (b: { type: string; base_url: string; model: string; embed_model: string; api_key?: string }) =>
  api<HelperSettings>("/api/settings/helper", { method: "PUT", body: b });

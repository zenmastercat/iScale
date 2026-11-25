"use client";
import { api } from "@/lib/api";

export type ReviewVerdict = "correct" | "wrong" | "unsure";

export interface CheckResult {
  id: string;
  verdict: { code: string; text: string; warnings: string[] };
  review: { verdict: ReviewVerdict; note?: string; at: number; by?: string | null; by_name?: string | null } | null;
  points: number;
  measured_depth_m: number | null;
  area_m2: number | null;
  detector_points: number;
  /** same-origin PNG urls keyed by panel: section | height | top */
  images: Record<string, string>;
  /** camera-only survey: no point cloud, the detector crop is the evidence */
  photo_only?: boolean;
}

const base = (pid: string, sid: string, fid: string) =>
  `/api/projects/${encodeURIComponent(pid)}/surveys/${encodeURIComponent(sid)}/findings/${encodeURIComponent(fid)}`;

export const checkKey = (pid: string, sid: string, fid: string) => ["project", pid, "survey", sid, "check", fid] as const;

export const getCheck = (pid: string, sid: string, fid: string) => api<CheckResult>(`${base(pid, sid, fid)}/check`);

/** The server answers with the refreshed check, review included. */
export const postReview = (pid: string, sid: string, fid: string, verdict: ReviewVerdict, note = "") =>
  api<CheckResult>(`${base(pid, sid, fid)}/review`, { body: { verdict, note } });

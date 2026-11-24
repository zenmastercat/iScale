import { seg } from "@/lib/api";
import type { Survey } from "@/lib/types";

/**
 * Multipart upload with progress. lib/api.ts uses fetch, which cannot report upload progress,
 * so this one call uses XMLHttpRequest with the same headers the api() helper sends.
 */
export function uploadSurvey(
  pid: string,
  form: FormData,
  onProgress: (fraction: number) => void,
): Promise<Survey> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects/" + seg(pid) + "/surveys");
    xhr.setRequestHeader("X-Civil-Scan", "1");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* keep null */
      }
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      if (xhr.status === 401) window.location.assign("/login");
      if (xhr.status >= 300) {
        const d = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : null;
        return reject(new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : xhr.statusText));
      }
      resolve(data as Survey);
    };
    xhr.send(form);
  });
}

"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, Upload } from "lucide-react";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/surveys/query-error";
import { useT } from "@/lib/i18n";
import { useAuthState } from "@/lib/queries";
import { deleteDoc, getHelperSettings, listLibrary, putHelperSettings, reindexLibrary, uploadDoc } from "./api";

const inputCls =
  "h-11 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9";

function Field({ label, children }: { label: string; children: (id: string) => React.ReactNode }) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-grey-900">{label}</label>
      {children(id)}
    </div>
  );
}

const PROVIDERS: [string, string, string][] = [
  ["ollama", "Ollama on this server", "Ollama บนเซิร์ฟเวอร์นี้"],
  ["openai", "OpenAI or OpenAI-compatible", "OpenAI หรือที่เข้ากันได้"],
  ["anthropic", "Anthropic", "Anthropic"],
  ["google", "Google Gemini", "Google Gemini"],
];

/** Admin only. The API key is write-only: the field is always empty, the server never sends the key back. */
function ProviderForm() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["helper", "settings"], queryFn: getHelperSettings, retry: false });
  const save = useMutation({
    mutationFn: putHelperSettings,
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["helper"] });
      toast.success(t("Civil Helper settings saved", "บันทึกการตั้งค่าผู้ช่วยวิศวกรแล้ว"));
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  if (q.isError) return <QueryError what={t("Could not load the settings", "โหลดการตั้งค่าไม่ได้")} error={q.error} onRetry={() => q.refetch()} />;
  const h = q.data!.helper;
  return (
    <form
      key={`${h.type}|${h.base_url}|${h.model}|${h.embed_model}|${h.has_key}`}
      className="grid gap-3 md:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        const key = String(f.get("api_key") ?? "");
        save.mutate({
          type: String(f.get("type")),
          base_url: String(f.get("base_url") ?? ""),
          model: String(f.get("model") ?? ""),
          embed_model: String(f.get("embed_model") ?? ""),
          ...(key ? { api_key: key } : {}),
        });
        e.currentTarget.reset();
      }}
    >
      <Field label={t("Provider", "ผู้ให้บริการ")}>
        {(id) => (
          <select id={id} name="type" defaultValue={h.type} className={inputCls}>
            {PROVIDERS.map(([v, en, th]) => <option key={v} value={v}>{t(en, th)}</option>)}
          </select>
        )}
      </Field>
      <Field label={t("Endpoint (optional)", "ปลายทาง (ไม่บังคับ)")}>
        {(id) => <input id={id} name="base_url" defaultValue={h.base_url} placeholder={t("Provider's own API", "API ของผู้ให้บริการ")} className={inputCls} />}
      </Field>
      <Field label={t("Model", "โมเดล")}>
        {(id) => <input id={id} name="model" defaultValue={h.model} required className={inputCls} />}
      </Field>
      <Field label={t("Embedding model (for library search)", "โมเดลฝังข้อความ (สำหรับค้นคลังเอกสาร)")}>
        {(id) => <input id={id} name="embed_model" defaultValue={h.embed_model} placeholder={t("none: keyword search only", "ไม่ใส่: ค้นด้วยคำเท่านั้น")} className={inputCls} />}
      </Field>
      <Field label={`${t("API key", "คีย์ API")}${h.has_key ? ` (${t("saved; leave empty to keep", "บันทึกแล้ว เว้นว่างเพื่อใช้คีย์เดิม")})` : ""}`}>
        {(id) => <input id={id} name="api_key" type="password" autoComplete="off" spellCheck={false} placeholder={h.type === "ollama" ? t("not needed for Ollama", "Ollama ไม่ต้องใช้") : ""} className={inputCls} />}
      </Field>
      <div className="flex items-end">
        <Button type="submit" disabled={save.isPending} className="min-h-11 md:min-h-9">{t("Save Civil Helper settings", "บันทึกการตั้งค่าผู้ช่วยวิศวกร")}</Button>
      </div>
      <p className="text-xs text-muted-foreground md:col-span-2">
        {t(
          "\"auto:smallest-qwen\" picks the smallest Qwen model in Ollama. Questions go only to the provider you choose here; chat messages never do. The key is stored on the server and never shown again.",
          "\"auto:smallest-qwen\" เลือกโมเดล Qwen ที่เล็กที่สุดใน Ollama คำถามส่งไปยังผู้ให้บริการที่เลือกที่นี่เท่านั้น ข้อความแชตไม่ถูกส่งไปเลย คีย์เก็บไว้บนเซิร์ฟเวอร์และจะไม่แสดงอีก",
        )}
      </p>
    </form>
  );
}

export function LibraryPanel() {
  const t = useT();
  const qc = useQueryClient();
  const auth = useAuthState();
  const me = auth.data?.user;
  const admin = me?.role === "admin";
  const lib = useQuery({ queryKey: ["helper", "library"], queryFn: listLibrary, retry: false });
  const form = useRef<HTMLFormElement>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["helper"] });
  const upload = useMutation({
    mutationFn: uploadDoc,
    onMutate: () => toast.info(t("Reading the document. Large PDFs take a minute.", "กำลังอ่านเอกสาร ไฟล์ PDF ใหญ่ใช้เวลาประมาณหนึ่งนาที")),
    onSuccess: async () => { form.current?.reset(); await refresh(); toast.success(t("Document added", "เพิ่มเอกสารแล้ว")); },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: deleteDoc,
    onSuccess: async () => { setConfirmId(null); await refresh(); toast.success(t("Document removed", "ลบเอกสารแล้ว")); },
    onError: (e: Error) => toast.error(e.message),
  });
  const reindex = useMutation({
    mutationFn: reindexLibrary,
    onSuccess: async (r) => { await refresh(); toast.success(t(`Indexed ${r.chunks} passages`, `ทำดัชนี ${r.chunks} ข้อความแล้ว`)); },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="flex flex-col gap-6 md:gap-4">
      {admin && (
        <section aria-label={t("Civil Helper provider", "ผู้ให้บริการของผู้ช่วยวิศวกร")} className="rounded-lg border bg-card p-5 md:p-4">
          <h2 className="mb-3 text-lg font-semibold text-grey-900 md:text-base">{t("Provider", "ผู้ให้บริการ")}</h2>
          <ProviderForm />
        </section>
      )}

      <section aria-label={t("Library", "คลังเอกสาร")} className="rounded-lg border bg-card p-5 md:p-4">
        <h2 className="text-lg font-semibold text-grey-900 md:text-base">{t("Library", "คลังเอกสาร")}</h2>
        <p className="mt-1 mb-3 text-sm text-muted-foreground">
          {t(
            "Civil Helper answers from these documents and cites them. Add your standards, manuals and specifications (PDF, .txt or .md).",
            "ผู้ช่วยวิศวกรตอบจากเอกสารเหล่านี้และอ้างอิงให้ เพิ่มมาตรฐาน คู่มือ และข้อกำหนดของคุณ (PDF, .txt หรือ .md)",
          )}
        </p>
        <form
          ref={form}
          className="mb-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => { e.preventDefault(); upload.mutate(new FormData(e.currentTarget)); }}
        >
          <div className="min-w-48 flex-1">
            <Field label={t("Title (optional)", "ชื่อเอกสาร (ไม่บังคับ)")}>{(id) => <input id={id} name="title" maxLength={200} className={inputCls} />}</Field>
          </div>
          <div className="min-w-48 flex-1">
            <Field label={t("Document", "เอกสาร")}>{(id) => <input id={id} name="file" type="file" accept=".pdf,.txt,.md" required className={`${inputCls} py-2 md:py-1.5`} />}</Field>
          </div>
          <Button type="submit" disabled={upload.isPending} className="min-h-11 md:min-h-9"><Upload aria-hidden />{t("Add document", "เพิ่มเอกสาร")}</Button>
          {admin && (
            <Button type="button" variant="outline" disabled={reindex.isPending} onClick={() => reindex.mutate()} className="min-h-11 md:min-h-9">
              {t("Rebuild search index", "สร้างดัชนีค้นหาใหม่")}
            </Button>
          )}
        </form>

        {lib.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : lib.isError ? (
          <QueryError what={t("Could not load the library", "โหลดคลังเอกสารไม่ได้")} error={lib.error} onRetry={() => lib.refetch()} />
        ) : lib.data!.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("No documents yet.", "ยังไม่มีเอกสาร")}</p>
        ) : (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={t("Documents, scrolls sideways", "รายการเอกสาร เลื่อนไปด้านข้างได้")}>
            <table className="w-full min-w-[560px] text-left md:text-[13px]">
              <thead>
                <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
                  <th scope="col" className="py-2 pr-4">{t("Document", "เอกสาร")}</th>
                  <th scope="col" className="py-2 pr-4 text-right">{t("Passages", "ข้อความ")}</th>
                  <th scope="col" className="py-2 pr-4">{t("Search", "การค้นหา")}</th>
                  <th scope="col" className="py-2 pr-4">{t("Added by", "เพิ่มโดย")}</th>
                  <th scope="col" className="py-2"><span className="sr-only">{t("Actions", "การดำเนินการ")}</span></th>
                </tr>
              </thead>
              <tbody>
                {lib.data!.map((d) => (
                  <tr key={d.id} className="border-b align-top last:border-0">
                    <td className="py-2 pr-4 font-medium text-grey-900">{d.title}</td>
                    <td className="num py-2 pr-4 text-right">{d.chunks}</td>
                    <td className="py-2 pr-4">{d.embedded ? t("meaning + keywords", "ความหมาย + คำ") : t("keywords", "คำ")}</td>
                    <td className="py-2 pr-4">{d.uploader ? `@${d.uploader}` : "–"}</td>
                    <td className="py-2 text-right">
                      {(admin || d.uploader === me?.username) &&
                        (confirmId === d.id ? (
                          <span className="inline-flex flex-wrap justify-end gap-2">
                            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(d.id)} className="min-h-11 md:min-h-9">{t("Remove it", "ลบเลย")}</Button>
                            <Button variant="outline" onClick={() => setConfirmId(null)} className="min-h-11 md:min-h-9">{t("Cancel", "ยกเลิก")}</Button>
                          </span>
                        ) : (
                          <Button variant="outline" onClick={() => setConfirmId(d.id)} aria-label={`${t("Remove", "ลบ")}: ${d.title}`} className="min-h-11 md:min-h-9">
                            <Trash2 aria-hidden />{t("Remove", "ลบ")}
                          </Button>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { createWorkOrder } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { askHelper, helperStatus, type HelperReply } from "./api";

interface Msg {
  id: number;
  role: "user" | "bot";
  text: string;
  reply?: HelperReply;
  pending?: boolean;
}

/** **bold** and `code` only; everything else stays text, so nothing from the server is ever injected as HTML. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`|(?<![\w/])_[^_\s][^_]*_(?!\w))/g).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : part.startsWith("_") && part.endsWith("_") && part.length > 2 ? (
          <em key={i}>{part.slice(1, -1)}</em>
        ) : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? (
          <code key={i} className="num">{part.slice(1, -1)}</code>
        ) : (
          part
        ),
      )}
    </>
  );
}

const BULLET = /^\s*([-*•]|\d+[.)])\s+/;

/** Plain-text answer: lines starting "-", "*" or "1." become list items, other lines paragraphs. */
function Answer({ text }: { text: string }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const list = BULLET.test(line);
    const last = blocks[blocks.length - 1];
    if (last && last.list === list && list) last.lines.push(line);
    else blocks.push({ list, lines: [line] });
  }
  return (
    <div className="flex flex-col gap-2">
      {blocks.map((b, i) =>
        b.list ? (
          <ul key={i} className="list-disc pl-5">
            {b.lines.map((l, k) => <li key={k}><Inline text={l.replace(BULLET, "")} /></li>)}
          </ul>
        ) : (
          <p key={i} className="whitespace-pre-wrap"><Inline text={b.lines.join("\n")} /></p>
        ),
      )}
    </div>
  );
}

export function AskPanel({ variant = "page" }: { variant?: "page" | "panel" }) {
  const panel = variant === "panel";
  const t = useT();
  const qc = useQueryClient();
  const { projectId, surveyId, withSel } = useSelection();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const next = useRef(1);
  const end = useRef<HTMLDivElement>(null);
  const status = useQuery({ queryKey: ["helper", "status"], queryFn: helperStatus, staleTime: 30_000, retry: false });

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [msgs]);

  const suggestions = [
    t("Where are the stop signs?", "ป้ายหยุดอยู่ที่ไหนบ้าง"),
    t("How many high severity potholes are there?", "มีหลุมบ่อความรุนแรงสูงกี่จุด"),
    t("Which 3 segments are worst?", "ช่วงถนนที่แย่ที่สุด 3 ช่วงคือช่วงไหน"),
    t("What will it cost to fix the potholes?", "ค่าซ่อมหลุมบ่อทั้งหมดเท่าไร"),
    t("What has been verified?", "ตรวจยืนยันอะไรไปแล้วบ้าง"),
  ];

  const ask = useMutation({
    mutationFn: (q: string) => askHelper(q, projectId, surveyId),
    onSuccess: (r, q) => {
      void q;
      setMsgs((m) => [...m.filter((x) => !x.pending), { id: next.current++, role: "bot", text: r.reply, reply: r }]);
    },
    onError: (e: Error) => {
      setMsgs((m) => [...m.filter((x) => !x.pending), { id: next.current++, role: "bot", text: t(`That didn't work: ${e.message}`, `ไม่สำเร็จ: ${e.message}`) }]);
    },
  });
  const send = (q: string) => {
    const v = q.trim();
    if (!v || ask.isPending) return;
    setMsgs((m) => [...m, { id: next.current++, role: "user", text: v }, { id: next.current++, role: "bot", text: t("Working on it…", "กำลังหาคำตอบ…"), pending: true }]);
    setText("");
    ask.mutate(v);
  };
  const order = useMutation({
    mutationFn: (ids: string[]) => createWorkOrder(projectId!, { survey_id: surveyId!, finding_ids: ids, title: `${ids.length} repairs` }),
    onSuccess: async (wo) => {
      await qc.invalidateQueries({ queryKey: ["project", projectId!] });
      toast.success(t(`Work order ${wo.id} created`, `สร้างใบสั่งงาน ${wo.id} แล้ว`));
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const s = status.data;
  return (
    <div className={panel ? "flex h-full min-h-0 flex-col gap-2" : "flex flex-col gap-4"}>
      <p className="text-xs text-muted-foreground md:text-sm" role="status">
        {status.isLoading
          ? t("Checking Civil Helper…", "กำลังตรวจสอบผู้ช่วยวิศวกร…")
          : s?.reachable
            ? t(
                `Answers with ${s.model}, from ${s.documents} ${s.documents === 1 ? "document" : "documents"} in your library`,
                `ตอบด้วย ${s.model} จากเอกสาร ${s.documents} ฉบับในคลังของคุณ`,
              )
            : s
              ? t(`Civil Helper's model isn't reachable: ${s.error ?? ""}. Survey questions below still work.`, `เข้าถึงโมเดลของผู้ช่วยวิศวกรไม่ได้: ${s.error ?? ""} คำถามเกี่ยวกับการสำรวจด้านล่างยังใช้ได้`)
              : t("Civil Helper's status could not be loaded. Survey questions below still work.", "โหลดสถานะผู้ช่วยวิศวกรไม่ได้ คำถามเกี่ยวกับการสำรวจด้านล่างยังใช้ได้")}
      </p>

      <div role="log" className={panel ? "flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-lg border bg-card p-3" : "flex min-h-64 flex-col gap-3 rounded-lg border bg-card p-4 md:p-3"} aria-live="polite" aria-label={t("Conversation", "บทสนทนา")}>
        {msgs.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t("Ask about this survey, or about standards and repair methods.", "ถามเกี่ยวกับการสำรวจนี้ มาตรฐาน หรือวิธีซ่อม")}
          </p>
        )}
        {msgs.map((m) => (
          <div
            key={m.id}
            className={m.role === "user" ? "max-w-[85%] self-end rounded-lg bg-brand px-3 py-2 text-white" : "max-w-[95%] self-start rounded-lg border bg-grey-50 px-3 py-2"}
          >
            {m.pending ? <span className="inline-flex items-center gap-2 text-muted-foreground"><Loader2 aria-hidden className="size-4 animate-spin" />{m.text}</span> : m.role === "user" ? <p className="whitespace-pre-wrap">{m.text}</p> : <Answer text={m.text} />}
            {m.reply?.by === "helper" && (
              <div className="mt-2 border-t pt-2 text-sm text-muted-foreground">
                {m.reply.sources?.length ? (
                  <>
                    <p className="font-medium">{t("Sources", "แหล่งอ้างอิง")}</p>
                    <ul className="mt-1 flex flex-col gap-0.5">
                      {m.reply.sources.map((src) => (
                        <li key={src.n}><b>[{src.n}]</b> {src.title}{src.page ? `, ${t("page", "หน้า")} ${src.page}` : ""}</li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p>{t("No matching documents in your library.", "ไม่พบเอกสารที่ตรงกันในคลังของคุณ")}</p>
                )}
                <p className="mt-1">Civil Helper, <span className="num">{m.reply.model ?? ""}</span>, <span className="num">{m.reply.seconds ?? "?"}</span> s</p>
              </div>
            )}
            {m.reply && m.reply.by === "rules" && m.reply.highlight.length > 0 && (
              <Link href={withSel("/map", { finding: m.reply.highlight[0] })} className="mt-2 inline-flex min-h-11 items-center font-medium text-link underline underline-offset-4 md:min-h-0">
                {t(`Show ${m.reply.highlight.length} on the map`, `ดู ${m.reply.highlight.length} จุดบนแผนที่`)}
              </Link>
            )}
            {m.reply?.plan?.mode === "spot" && m.reply.plan.items.length > 0 && (
              <Button
                variant="outline"
                className="mt-2 min-h-11 md:min-h-9"
                disabled={order.isPending || !surveyId}
                onClick={() => order.mutate(m.reply!.plan!.items.map((i) => i.finding_id))}
              >
                {t(`Create a work order for these ${m.reply.plan.items.length}`, `สร้างใบสั่งงานสำหรับ ${m.reply.plan.items.length} รายการนี้`)}
              </Button>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>

      <div role="group" className={panel ? "flex max-h-28 flex-wrap gap-2 overflow-y-auto" : "flex flex-wrap gap-2"} aria-label={t("Suggested questions", "คำถามแนะนำ")}>
        {suggestions.map((q) => (
          <button key={q} type="button" onClick={() => send(q)} className="min-h-11 rounded-full border bg-card px-3 text-sm hover:bg-grey-50 md:min-h-9">
            {q}
          </button>
        ))}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          autoComplete="off"
          enterKeyHint="send"
          aria-label={t("Question", "คำถาม")}
          placeholder={t("Ask Civil Helper", "ถามผู้ช่วยวิศวกร")}
          className="h-11 min-w-0 flex-1 rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9"
        />
        <Button type="submit" disabled={!text.trim() || ask.isPending} className="min-h-11 md:min-h-9">
          <Send aria-hidden />
          {t("Send", "ส่ง")}
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">
        {t(
          "Questions about this survey are answered from its data by fixed rules. Other questions go to Civil Helper, which answers from your company's document library and names its sources.",
          "คำถามเกี่ยวกับการสำรวจนี้ตอบจากข้อมูลด้วยกฎที่กำหนดไว้ คำถามอื่นส่งให้ผู้ช่วยวิศวกร ซึ่งตอบจากคลังเอกสารของบริษัทและระบุแหล่งอ้างอิง",
        )}
      </p>
    </div>
  );
}

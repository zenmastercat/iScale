"use client";
import { ArrowLeft, Lock, MapPin, Search, Send, ShieldCheck, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { searchDirectory, getXmppToken, type DirectoryRow } from "@/lib/chat/api";
import type { Conv, Group, Messenger, Msg, Peer } from "@/lib/chat/messenger";
import { useAuthState } from "@/lib/queries";
import { cn } from "@/lib/utils";

type Status = "checking" | "unavailable" | "connecting" | "online" | "offline";
const inputCls = "h-11 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9";

function Avatar({ name, group }: { name: string; group?: boolean }) {
  const initial = Array.from(name.replace(/^g:/, "").trim())[0]?.toLocaleUpperCase() ?? "?";
  return (
    <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-grey-100 text-sm font-semibold text-grey-700">
      {group ? <Users className="size-4" /> : initial}
    </span>
  );
}

/** Crew chat: conversation list, thread, composer. The OMEMO/XMPP code is lib/chat/messenger.js, copied from the old UI. */
export function ChatView() {
  const t = useT();
  const { data: auth } = useAuthState();
  const me = auth?.user;
  const [status, setStatus] = useState<Status>("checking");
  const [reason, setReason] = useState("");
  const [m, setM] = useState<Messenger | null>(null);
  const [tick, setTick] = useState(0);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [groups, setGroups] = useState<Map<string, Group>>(new Map());
  const [current, setCurrent] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<DirectoryRow[]>([]);
  const [peers, setPeers] = useState<Record<string, Peer>>({});
  const [text, setText] = useState("");
  const [codes, setCodes] = useState<{ mine: string; theirs: string[] } | null | undefined>(undefined);
  const [showMembers, setShowMembers] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const currentRef = useRef<string | null>(null);
  useEffect(() => {
    currentRef.current = current;
  });

  // 1. ask iScale for a chat token first: if the chat server is not running we say so instead of failing later
  const username = me?.username;
  const displayName = me?.display_name;
  const role = me?.role;
  useEffect(() => {
    if (!username) return;
    let messenger: Messenger | null = null;
    let dead = false;
    (async () => {
      try {
        const tok = await getXmppToken();
        if (tok.running === false) throw new Error("not running");
      } catch (e) {
        if (!dead) {
          setReason(e instanceof Error ? e.message : "");
          setStatus("unavailable");
        }
        return;
      }
      try {
        setStatus("connecting");
        const mod = await import("@/lib/chat/messenger");
        if (dead) return;
        messenger = new mod.Messenger(
          { username, display_name: displayName ?? username, role },
          {
            onMessage: (peer) => {
              setTick((n) => n + 1);
              if (peer === currentRef.current) messenger?.markRead(peer);
            },
            toast: (msg, err) => (err ? toast.error(msg) : toast(msg)),
          },
        );
        await messenger.start();
        if (!dead) setM(messenger);
      } catch (e) {
        if (!dead) {
          setReason(e instanceof Error ? e.message : "");
          setStatus("unavailable");
        }
      }
    })();
    return () => {
      dead = true;
      messenger?.stop();
    };
  }, [username, displayName, role]);

  // 2. connection state: the socket reconnects by itself, so just watch it
  useEffect(() => {
    if (!m) return;
    const id = setInterval(() => setStatus(m.xmpp?.online ? "online" : "offline"), 1500);
    return () => clearInterval(id);
  }, [m]);

  // 3. conversations and groups
  useEffect(() => {
    if (!m) return;
    let alive = true;
    (async () => {
      const [list, gs] = await Promise.all([m.conversations(), m.loadGroups().catch(() => new Map<string, Group>())]);
      if (!alive) return;
      const seen = new Set(list.map((c) => c.peer));
      for (const g of gs.values()) if (!seen.has("g:" + g.id)) list.push({ peer: "g:" + g.id, display_name: g.name, group: true, last: g.created * 1000 });
      list.sort((a, b) => (b.last || 0) - (a.last || 0));
      setConvs(list);
      setGroups(gs);
    })().catch(() => {});
    return () => {
      alive = false;
    };
  }, [m, tick]);

  // 4. the open thread
  useEffect(() => {
    if (!m || !current) return;
    let alive = true;
    m.history(current).then((h) => alive && setMsgs(h), () => {});
    return () => {
      alive = false;
    };
  }, [m, current, tick]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [msgs]);

  // 5. find people
  useEffect(() => {
    const term = q.trim();
    if (!term) return;
    const id = setTimeout(() => searchDirectory(term).then(setHits, () => setHits([])), 250);
    return () => clearTimeout(id);
  }, [q]);

  const open = useCallback(
    async (peer: Peer) => {
      if (!m) return;
      setPeers((p) => ({ ...p, [peer.username]: peer }));
      setCurrent(peer.username);
      setQ("");
      setHits([]);
      await m.markRead(peer.username);
      setTick((n) => n + 1);
    },
    [m],
  );

  const group = current?.startsWith("g:") ? groups.get(current.slice(2)) : undefined;
  const conv = convs.find((c) => c.peer === current);
  const title = group?.name ?? conv?.display_name ?? peers[current ?? ""]?.display_name ?? current ?? "";

  const send = async (payload: object) => {
    if (!m || !current) return;
    try {
      if (group) {
        const { skipped } = await m.sendGroup(group, payload);
        if (skipped.length) toast(t(`Not delivered to ${skipped.join(", ")}: they have not signed in on a device yet.`, `ส่งไม่ถึง ${skipped.join(", ")}: ยังไม่ได้เข้าสู่ระบบบนอุปกรณ์`));
      } else {
        await m.send(peers[current] ?? conv ?? { username: current }, payload);
      }
      setTick((n) => n + 1);
    } catch (e) {
      toast.error(t(`Not sent: ${e instanceof Error ? e.message : ""}`, `ส่งไม่สำเร็จ: ${e instanceof Error ? e.message : ""}`));
    }
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v) return;
    setText("");
    send({ kind: "text", text: v });
  };
  const shareLocation = () => {
    if (!navigator.geolocation) return toast.error(t("This browser cannot share a location.", "เบราว์เซอร์นี้แชร์ตำแหน่งไม่ได้"));
    navigator.geolocation.getCurrentPosition(
      (p) => send({ kind: "location", lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.round(p.coords.accuracy) }),
      (err) => toast.error(t(`Location unavailable: ${err.message}. Browsers allow it only on HTTPS or localhost.`, `ใช้ตำแหน่งไม่ได้: ${err.message} เบราว์เซอร์อนุญาตเฉพาะ HTTPS หรือ localhost`)),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  };

  if (status === "checking" || !me) return <Skeleton className="h-96 w-full" />;
  if (status === "unavailable")
    return (
      <EmptyState
        icon={Lock}
        title={t("Chat server not available", "เซิร์ฟเวอร์แชทไม่พร้อมใช้งาน")}
        description={t(
          "The company's chat server (ejabberd) is not running on this machine, so crew chat cannot connect. The rest of iScale works as usual.",
          "เซิร์ฟเวอร์แชทของบริษัท (ejabberd) ไม่ได้ทำงานบนเครื่องนี้ จึงเชื่อมต่อแชทไม่ได้ ส่วนอื่นของ iScale ใช้งานได้ตามปกติ",
        )}
        action={reason ? <p className="text-xs text-muted-foreground">{reason}</p> : undefined}
      />
    );

  const notEnc = t(
    "End-to-end encrypted with OMEMO. Messages are stored only on your devices; the company's chat server passes them on and keeps only ciphertext.",
    "เข้ารหัสแบบ end-to-end ด้วย OMEMO ข้อความเก็บไว้บนอุปกรณ์ของคุณเท่านั้น เซิร์ฟเวอร์แชทของบริษัทแค่ส่งต่อและเก็บเฉพาะข้อมูลที่เข้ารหัส",
  );

  return (
    <div className="flex flex-col gap-3">
      {status !== "online" && (
        <p role="status" className="rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground">
          {status === "connecting" ? t("Connecting to the chat server…", "กำลังเชื่อมต่อเซิร์ฟเวอร์แชท…") : t("Chat is offline. Reconnecting…", "แชทออฟไลน์ กำลังเชื่อมต่อใหม่…")}
        </p>
      )}
      <div className="grid min-h-[480px] overflow-hidden rounded-lg border bg-card md:h-[calc(100dvh-14rem)] md:grid-cols-[300px_1fr]">
        <aside className={cn("flex min-h-0 flex-col border-b md:border-r md:border-b-0", current && "max-md:hidden")} aria-label={t("Conversations", "การสนทนา")}>
          <div className="relative border-b p-2">
            <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input className={cn(inputCls, "pl-9")} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Find by name or username", "ค้นหาด้วยชื่อหรือชื่อผู้ใช้")} aria-label={t("Find an engineer", "ค้นหาวิศวกร")} autoComplete="off" autoCapitalize="none" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {q.trim() ? (
              hits.length ? (
                hits.map((r) => (
                  <button key={r.username} type="button" disabled={!r.can_chat} onClick={() => open({ username: r.username, display_name: r.display_name, company: r.company })} className="flex min-h-11 w-full items-center gap-2 border-b px-3 py-2 text-left hover:bg-grey-50 disabled:opacity-50">
                    <Avatar name={r.display_name} />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{r.display_name}</span>
                      <span className="block truncate text-xs text-muted-foreground">@{r.username}, {r.company}{r.can_chat ? "" : ` (${t("has not signed in yet", "ยังไม่เคยเข้าสู่ระบบ")})`}</span>
                    </span>
                  </button>
                ))
              ) : (
                <p className="p-3 text-sm text-muted-foreground">{t("Nobody matches. People in other companies are found by their exact username.", "ไม่พบใคร คนในบริษัทอื่นค้นหาได้ด้วยชื่อผู้ใช้ที่ตรงกันเท่านั้น")}</p>
              )
            ) : convs.length ? (
              convs.map((c) => (
                <button key={c.peer} type="button" onClick={() => open({ username: c.peer, display_name: c.display_name, company: c.company })} aria-current={current === c.peer || undefined} className={cn("flex min-h-11 w-full items-start gap-2 border-b px-3 py-2 text-left hover:bg-grey-50", current === c.peer && "bg-brand/10")}>
                  <Avatar name={c.display_name} group={c.group} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <span className="truncate">{groups.get(c.peer.slice(2))?.name ?? c.display_name}</span>
                      {!!c.unread && <span className="num rounded-full bg-brand px-1.5 text-xs text-white" aria-label={t(`${c.unread} unread`, `ยังไม่ได้อ่าน ${c.unread}`)}>{c.unread}</span>}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">{c.preview || t("No messages yet", "ยังไม่มีข้อความ")}</span>
                  </span>
                </button>
              ))
            ) : (
              <p className="p-3 text-sm text-muted-foreground">{t("No conversations yet. Search for a colleague above.", "ยังไม่มีการสนทนา ค้นหาเพื่อนร่วมงานด้านบน")}</p>
            )}
          </div>
        </aside>

        <section className={cn("flex min-h-0 flex-col", !current && "max-md:hidden")} aria-label={t("Messages", "ข้อความ")}>
          {!current ? (
            <div className="m-auto flex max-w-sm flex-col items-center gap-2 p-6 text-center">
              <Lock className="size-7 text-brand" aria-hidden />
              <h2 className="text-lg font-semibold">{t("Talk to your crew", "คุยกับทีมของคุณ")}</h2>
              <p className="text-sm">{t("Find an engineer by username to start a chat, or open a conversation on the left.", "ค้นหาวิศวกรด้วยชื่อผู้ใช้เพื่อเริ่มแชท หรือเปิดการสนทนาทางซ้าย")}</p>
              <p className="text-xs text-muted-foreground">{notEnc}</p>
            </div>
          ) : (
            <>
              <header className="flex items-center gap-2 border-b px-3 py-2">
                <Button type="button" variant="ghost" size="icon" className="min-h-11 md:hidden" aria-label={t("Back to conversations", "กลับไปรายการสนทนา")} onClick={() => setCurrent(null)}>
                  <ArrowLeft className="size-4" />
                </Button>
                <Avatar name={title} group={!!current.startsWith("g:")} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">{title}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {current.startsWith("g:") ? (group ? group.members.map((x) => x.display_name.split(" ")[0]).join(", ") : t("You are no longer in this group", "คุณไม่ได้อยู่ในกลุ่มนี้แล้ว")) : `@${current}`}
                  </div>
                </div>
                {current.startsWith("g:") ? (
                  group && <Button type="button" variant="outline" className="min-h-8" onClick={() => setShowMembers(true)}>{t("Members", "สมาชิก")}</Button>
                ) : (
                  <Button type="button" variant="outline" className="min-h-8" onClick={async () => setCodes(await m!.safetyNumber(current))}>
                    <ShieldCheck className="size-4" aria-hidden />
                    {t("Security code", "รหัสความปลอดภัย")}
                  </Button>
                )}
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto p-3" aria-live="polite">
                {msgs.length === 0 && <p className="mb-2 rounded-md bg-grey-50 p-2 text-center text-xs text-muted-foreground">{notEnc}</p>}
                <ul className="flex flex-col gap-1.5">
                  {msgs.map((x, i) => (
                    <Bubble key={x.id} msg={x} showName={current.startsWith("g:") && !x.out && (i === 0 || msgs[i - 1].from !== x.from || msgs[i - 1].kind === "notice")} />
                  ))}
                </ul>
                <div ref={bottom} />
              </div>
              {(!current.startsWith("g:") || group) && (
                <form onSubmit={submit} className="flex items-center gap-2 border-t p-2">
                  <Button type="button" variant="outline" size="icon" className="min-h-11 md:min-h-9" aria-label={t("Share my location", "แชร์ตำแหน่งของฉัน")} title={t("Share my location", "แชร์ตำแหน่งของฉัน")} onClick={shareLocation}>
                    <MapPin className="size-4" />
                  </Button>
                  <input className={inputCls} value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder={group ? t("Message the group", "ส่งข้อความถึงกลุ่ม") : t("Message", "ข้อความ")} aria-label={t("Message", "ข้อความ")} autoComplete="off" enterKeyHint="send" />
                  <Button type="submit" className="min-h-11 bg-brand text-white hover:bg-brand/90 md:min-h-9" disabled={status !== "online" || !text.trim()}>
                    <Send className="size-4" aria-hidden />
                    {t("Send", "ส่ง")}
                  </Button>
                </form>
              )}
            </>
          )}
        </section>
      </div>

      <Dialog open={codes !== undefined} onOpenChange={(o) => !o && setCodes(undefined)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(`Security codes with ${title}`, `รหัสความปลอดภัยกับ ${title}`)}</DialogTitle>
            <DialogDescription>
              {codes
                ? t("These are OMEMO fingerprints. Compare them with what the other person sees, in person or on a call. If they match, nobody is reading your messages in between.", "นี่คือลายนิ้วมือ OMEMO ให้เทียบกับที่อีกฝ่ายเห็น ต่อหน้าหรือทางโทรศัพท์ ถ้าตรงกัน แปลว่าไม่มีใครแอบอ่านข้อความระหว่างทาง")
                : t("Send or receive a message first.", "ส่งหรือรับข้อความก่อน")}
            </DialogDescription>
          </DialogHeader>
          {codes && (
            <div className="flex flex-col gap-2 text-sm">
              <p className="text-xs text-muted-foreground">{t("Your device", "อุปกรณ์ของคุณ")}</p>
              <p className="num break-all">{codes.mine}</p>
              <p className="text-xs text-muted-foreground">{t("Their devices", "อุปกรณ์ของอีกฝ่าย")}</p>
              {codes.theirs.map((c) => <p key={c} className="num break-all">{c}</p>)}
            </div>
          )}
          <DialogFooter><DialogClose render={<Button type="button" variant="outline" />}>{t("Close", "ปิด")}</DialogClose></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showMembers && !!group} onOpenChange={setShowMembers}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{group?.name}</DialogTitle>
            <DialogDescription>
              {t("Members can be added or removed by an admin on the Team page.", "ผู้ดูแลเพิ่มหรือลบสมาชิกได้ที่หน้าทีม")}
            </DialogDescription>
          </DialogHeader>
          <ul className="flex flex-col gap-2 text-sm">
            {group?.members.map((x) => (
              <li key={x.username} className="flex items-center gap-2">
                <Avatar name={x.display_name} />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{x.display_name}{x.username === group.created_by && <span className="ml-1.5 text-xs text-muted-foreground">{t("admin", "ผู้ดูแล")}</span>}</span>
                  <span className="block truncate text-xs text-muted-foreground">@{x.username}</span>
                </span>
              </li>
            ))}
          </ul>
          <DialogFooter><DialogClose render={<Button type="button" variant="outline" />}>{t("Close", "ปิด")}</DialogClose></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Bubble({ msg: x, showName }: { msg: Msg; showName: boolean }) {
  const t = useT();
  const time = new Date(x.sent).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (x.kind === "notice") return <li className="self-center rounded-full bg-grey-50 px-3 py-1 text-center text-xs text-muted-foreground">{x.text}</li>;
  const geo = x.kind === "location" ? x : x.kind === "pin" ? x.pin : x.kind === "finding" ? x.finding : undefined;
  return (
    <li className={cn("max-w-[85%] rounded-lg border px-3 py-1.5 text-sm", x.out ? "self-end border-brand/20 bg-brand/10" : "self-start bg-card")}>
      {showName && <span className="block text-xs font-semibold text-brand">{x.from_name || x.from}</span>}
      {x.kind === "text" && <p className="break-words whitespace-pre-wrap">{x.text}</p>}
      {x.kind === "location" && (
        <p><b>{t("Location", "ตำแหน่ง")}</b><br /><span className="num">{(+x.lat!).toFixed(6)}, {(+x.lon!).toFixed(6)}</span>{x.acc ? ` (±${x.acc} m)` : ""}</p>
      )}
      {x.kind === "pin" && x.pin && <p><b>{x.pin.label}</b>, {x.pin.severity}<br /><span className="text-xs">{x.pin.note}</span></p>}
      {x.kind === "finding" && x.finding && <p><b>{x.finding.label}</b>{x.finding.severity ? `, ${x.finding.severity}` : ""}<br /><span className="text-xs">{x.finding.evidence}</span></p>}
      {geo && (
        <a className="mt-1 inline-block text-xs font-medium text-link underline underline-offset-4" href={`https://www.google.com/maps/@?api=1&map_action=map&center=${(+(geo.lat ?? 0)).toFixed(6)},${(+(geo.lon ?? 0)).toFixed(6)}&zoom=18`} target="_blank" rel="noopener noreferrer">
          {t("Open in Google Maps", "เปิดใน Google Maps")}
        </a>
      )}
      <span className="num mt-0.5 block text-right text-[11px] text-muted-foreground">{time}</span>
    </li>
  );
}

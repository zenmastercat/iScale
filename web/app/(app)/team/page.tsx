"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Smartphone, UserPlus } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { addMember, listTeam, qk, resetMemberDevice } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useAuthState } from "@/lib/queries";
import type { User } from "@/lib/types";

const USERNAME = /^[a-z0-9._-]{3,32}$/;

function Field({ label, children, help }: { label: string; children: (id: string) => React.ReactNode; help?: string }) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-grey-900">{label}</label>
      {children(id)}
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}

const inputCls =
  "h-11 rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9";

/** QR + link for "open the sign-in page on your phone". */
function SignInQr({ username }: { username: string }) {
  const t = useT();
  const [src, setSrc] = useState<string>();
  const url = typeof window === "undefined" ? "" : `${window.location.origin}/login`;
  const local = typeof window !== "undefined" && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 200 }).then(setSrc, () => setSrc(undefined));
  }, [url]);
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- data URL, nothing to optimise
        <img src={src} width={160} height={160} alt={t(`QR code that opens ${url}`, `คิวอาร์โค้ดสำหรับเปิด ${url}`)} className="rounded-md border" />
      ) : (
        <Skeleton className="size-40" />
      )}
      <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm text-grey-900">
        <li>{t("On their phone, scan the code (or open", "ให้สแกนโค้ดด้วยโทรศัพท์ (หรือเปิด")} <span className="num break-all">{url}</span>)</li>
        <li>
          {t("Sign in with the username", "เข้าสู่ระบบด้วยชื่อผู้ใช้")} <b className="num">{username}</b>
        </li>
        <li>{t("That phone becomes theirs. Nobody else can use the username.", "โทรศัพท์เครื่องนั้นจะผูกกับชื่อผู้ใช้นี้ ผู้อื่นใช้ไม่ได้")}</li>
        {local && (
          <li className="list-none text-sev-medium-fg">
            {t(
              "This page is open on localhost, which a phone can't reach. Open it with the laptop's network address (see PITCH.md).",
              "หน้านี้เปิดผ่าน localhost ซึ่งโทรศัพท์เข้าไม่ได้ ให้เปิดด้วยที่อยู่เครือข่ายของแล็ปท็อป (ดู PITCH.md)",
            )}
          </li>
        )}
      </ol>
    </div>
  );
}

function AddPerson() {
  const t = useT();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"engineer" | "admin">("engineer");
  const [added, setAdded] = useState<User | null>(null);
  const u = username.trim().toLowerCase().replace(/^@/, "");
  const valid = name.trim().length > 0 && USERNAME.test(u);
  const m = useMutation({
    mutationFn: () => addMember({ username: u, display_name: name.trim(), role }),
    onSuccess: (user) => {
      setAdded(user);
      setName("");
      setUsername("");
      qc.invalidateQueries({ queryKey: qk.team });
      toast.success(t(`Added ${user.display_name}`, `เพิ่ม ${user.display_name} แล้ว`));
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <section aria-labelledby="add-h" className="rounded-lg border bg-card p-5 md:p-4">
      <h2 id="add-h" className="mb-3 flex items-center gap-2 text-lg font-semibold text-grey-900 md:text-base">
        <UserPlus aria-hidden className="size-4" />
        {t("Add a person", "เพิ่มสมาชิก")}
      </h2>
      <form
        className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_10rem_auto] md:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) m.mutate();
        }}
      >
        <Field label={t("Name", "ชื่อ")}>
          {(id) => <input id={id} className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required autoComplete="off" placeholder="Somchai K." />}
        </Field>
        <Field label={t("Username", "ชื่อผู้ใช้")} help={t("3–32 letters, digits, . - _", "3–32 ตัว: a-z, 0-9, . - _")}>
          {(id) => (
            <input
              id={id}
              className={`${inputCls} num`}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={33}
              required
              autoCapitalize="none"
              spellCheck={false}
              autoComplete="off"
              placeholder="crew.somchai"
              aria-invalid={username !== "" && !USERNAME.test(u)}
            />
          )}
        </Field>
        <Field label={t("Role", "บทบาท")}>
          {(id) => (
            <select id={id} className={inputCls} value={role} onChange={(e) => setRole(e.target.value as "engineer" | "admin")}>
              <option value="engineer">{t("Engineer / crew", "วิศวกร / ช่าง")}</option>
              <option value="admin">{t("Admin", "ผู้ดูแล")}</option>
            </select>
          )}
        </Field>
        <Button type="submit" className="h-11 md:h-9" disabled={!valid || m.isPending}>
          {t("Add", "เพิ่ม")}
        </Button>
      </form>
      {added && (
        <div className="mt-4 border-t pt-4" role="status">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Smartphone aria-hidden className="size-4" />
            {t(`Next: ${added.display_name} signs in on their own device`, `ขั้นต่อไป: ${added.display_name} เข้าสู่ระบบบนอุปกรณ์ของตัวเอง`)}
          </h3>
          <SignInQr username={added.username} />
        </div>
      )}
    </section>
  );
}

function ResetDevice({ user }: { user: User }) {
  const t = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const m = useMutation({
    mutationFn: () => resetMemberDevice(user.username),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: qk.team });
      toast.success(t(`${user.display_name} can sign in on a new device`, `${user.display_name} เข้าสู่ระบบบนอุปกรณ์ใหม่ได้แล้ว`));
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <>
      <Button variant="outline" size="sm" className="h-11 md:h-8" onClick={() => setOpen(true)}>
        <KeyRound aria-hidden />
        {t("Reset device", "รีเซ็ตอุปกรณ์")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(`Reset ${user.display_name}'s device?`, `รีเซ็ตอุปกรณ์ของ ${user.display_name}?`)}</DialogTitle>
            <DialogDescription>
              {t(
                "They are signed out everywhere. The next device that signs in with this username becomes theirs.",
                "ผู้ใช้จะออกจากระบบทุกเครื่อง อุปกรณ์ถัดไปที่เข้าสู่ระบบด้วยชื่อนี้จะผูกกับผู้ใช้",
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" className="h-11 md:h-9" />}>{t("Cancel", "ยกเลิก")}</DialogClose>
            <Button variant="destructive" className="h-11 md:h-9" disabled={m.isPending} onClick={() => m.mutate()}>
              {t("Reset device", "รีเซ็ตอุปกรณ์")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function TeamPage() {
  const t = useT();
  const { data: auth } = useAuthState();
  const me = auth?.user;
  const isAdmin = me?.role === "admin";
  const team = useQuery({ queryKey: qk.team, queryFn: listTeam });

  return (
    <>
      <PageHeader title={t("Team", "ทีม")} crumb={me?.company} />
      <div className="flex flex-col gap-6 md:gap-4">
        {isAdmin && <AddPerson />}
        <section aria-labelledby="team-h" className="rounded-lg border bg-card p-5 md:p-4">
          <h2 id="team-h" className="mb-3 text-lg font-semibold text-grey-900 md:text-base">
            {t("People", "สมาชิก")} {team.data && <span className="num text-sm font-normal text-muted-foreground">({team.data.length})</span>}
          </h2>
          {team.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : team.isError ? (
            <p role="alert" className="text-sev-high-fg">{team.error.message}</p>
          ) : (
            <div className="relative overflow-x-auto" tabIndex={0} role="region" aria-label={t("People, scrolls sideways", "รายชื่อสมาชิก เลื่อนด้านข้างได้")}>
              <table className="w-full min-w-[560px] text-left text-sm md:text-[13px]">
                <thead>
                  <tr className="border-b text-xs font-semibold tracking-wider text-grey-600 uppercase">
                    <th scope="col" className="py-2 pr-3 font-semibold">{t("Name", "ชื่อ")}</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">{t("Username", "ชื่อผู้ใช้")}</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">{t("Role", "บทบาท")}</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">{t("Device", "อุปกรณ์")}</th>
                    {isAdmin && <th scope="col" className="py-2"><span className="sr-only">{t("Actions", "การทำงาน")}</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {team.data!.map((u) => (
                    <tr key={u.username} className="border-b last:border-0">
                      <td className="py-2 pr-3 font-medium text-grey-900 md:py-1.5">
                        {u.display_name}
                        {u.username === me?.username && <span className="ml-1.5 text-xs font-normal text-muted-foreground">({t("you", "คุณ")})</span>}
                      </td>
                      <td className="num py-2 pr-3 md:py-1.5">{u.username}</td>
                      <td className="py-2 pr-3 md:py-1.5">{u.role === "admin" ? t("Admin", "ผู้ดูแล") : t("Engineer", "วิศวกร")}</td>
                      <td className="py-2 pr-3 md:py-1.5">
                        {u.disabled ? (
                          <span className="text-muted-foreground">{t("Disabled", "ปิดใช้งาน")}</span>
                        ) : u.device_bound ? (
                          <span className="text-sev-low-fg">✓ {t("Linked", "ผูกแล้ว")}</span>
                        ) : (
                          <span className="text-sev-medium-fg">{t("Waiting for first sign-in", "รอเข้าสู่ระบบครั้งแรก")}</span>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="py-1 text-right">{u.device_bound && u.username !== me?.username && <ResetDevice user={u} />}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!isAdmin && <p className="mt-3 text-sm text-muted-foreground">{t("Only admins can add people.", "เฉพาะผู้ดูแลเท่านั้นที่เพิ่มสมาชิกได้")}</p>}
        </section>
      </div>
    </>
  );
}

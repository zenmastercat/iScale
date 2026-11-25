"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { addGroupMembers, createGroup, deleteGroup, listGroups, removeGroupMember, renameGroup } from "@/lib/chat/api";
import type { Group } from "@/lib/chat/messenger";
import { ApiError, listTeam, qk } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const GROUPS = ["chat", "groups"] as const;
const inputCls = "h-11 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9";

/** People picker over the company's team (people whose phone has not signed in yet cannot be added). */
function Picker({ exclude, picked, onToggle }: { exclude: Set<string>; picked: Set<string>; onToggle: (u: string) => void }) {
  const t = useT();
  const team = useQuery({ queryKey: qk.team, queryFn: listTeam });
  const people = (team.data ?? []).filter((u) => !u.disabled && !exclude.has(u.username));
  if (!people.length) return <p className="text-sm text-muted-foreground">{t("Nobody else to add.", "ไม่มีผู้ที่เพิ่มได้อีก")}</p>;
  return (
    <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-md border p-2">
      {people.map((u) => (
        <li key={u.username}>
          <label className={cn("flex min-h-11 items-center gap-2 text-sm md:min-h-8", !u.device_bound && "opacity-50")}>
            <input type="checkbox" className="size-4" disabled={!u.device_bound} checked={picked.has(u.username)} onChange={() => onToggle(u.username)} />
            <span className="font-medium">{u.display_name}</span>
            <span className="num text-xs text-muted-foreground">@{u.username}{!u.device_bound && ` (${t("has not signed in yet", "ยังไม่เคยเข้าสู่ระบบ")})`}</span>
          </label>
        </li>
      ))}
    </ul>
  );
}

const flip = (s: Set<string>, u: string) => {
  const n = new Set(s);
  if (n.has(u)) n.delete(u);
  else n.add(u);
  return n;
};
const fail = (t: ReturnType<typeof useT>) => (e: unknown) => toast.error(e instanceof ApiError ? e.message : t("That did not work", "ดำเนินการไม่สำเร็จ"));

function NewGroup({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const create = useMutation({
    mutationFn: () => createGroup(name.trim(), [...picked]),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: GROUPS });
      toast.success(t(`Group "${g.name}" created`, `สร้างกลุ่ม "${g.name}" แล้ว`));
      setName("");
      setPicked(new Set());
      onClose();
    },
    onError: fail(t),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("New group", "กลุ่มใหม่")}</DialogTitle>
          <DialogDescription>{t("Pick a crew from your company. Everyone sees messages from the moment they join.", "เลือกทีมจากบริษัทของคุณ ทุกคนเห็นข้อความตั้งแต่เข้าร่วม")}</DialogDescription>
        </DialogHeader>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t("Group name", "ชื่อกลุ่ม")}
          <input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={t("e.g. Night patch crew, Zone 3", "เช่น ทีมปะหลุมกะดึก เขต 3")} />
        </label>
        <Picker exclude={new Set()} picked={picked} onToggle={(u) => setPicked((s) => flip(s, u))} />
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>{t("Cancel", "ยกเลิก")}</DialogClose>
          <Button type="button" className="bg-brand text-white hover:bg-brand/90" disabled={!name.trim() || !picked.size || create.isPending} onClick={() => create.mutate()}>
            {t("Create group", "สร้างกลุ่ม")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Manage({ group, onClose }: { group: Group; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [name, setName] = useState(group.name);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const done = () => qc.invalidateQueries({ queryKey: GROUPS });
  const rename = useMutation({ mutationFn: () => renameGroup(group.id, name.trim()), onSuccess: () => { done(); toast.success(t("Renamed", "เปลี่ยนชื่อแล้ว")); }, onError: fail(t) });
  const add = useMutation({ mutationFn: () => addGroupMembers(group.id, [...picked]), onSuccess: () => { done(); setPicked(new Set()); toast.success(t("People added", "เพิ่มสมาชิกแล้ว")); }, onError: fail(t) });
  const remove = useMutation({ mutationFn: (u: string) => removeGroupMember(group.id, u), onSuccess: () => { done(); toast.success(t("Removed", "ลบแล้ว")); }, onError: fail(t) });
  const del = useMutation({ mutationFn: () => deleteGroup(group.id), onSuccess: () => { done(); onClose(); toast.success(t("Group deleted", "ลบกลุ่มแล้ว")); }, onError: fail(t) });
  const members = new Set(group.members.map((m) => m.username));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group.name}</DialogTitle>
          <DialogDescription>{t("Members keep the messages already on their devices if the group is deleted.", "ถ้าลบกลุ่ม สมาชิกยังเก็บข้อความที่อยู่ในอุปกรณ์ของตนไว้")}</DialogDescription>
        </DialogHeader>
        <div className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-sm font-medium">
            {t("Group name", "ชื่อกลุ่ม")}
            <input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </label>
          <Button type="button" variant="outline" disabled={!name.trim() || name.trim() === group.name || rename.isPending} onClick={() => rename.mutate()}>{t("Rename", "เปลี่ยนชื่อ")}</Button>
        </div>
        <h3 className="text-sm font-semibold">{t("Members", "สมาชิก")} <span className="num font-normal text-muted-foreground">({group.members.length})</span></h3>
        <ul className="flex flex-col gap-1 text-sm">
          {group.members.map((m) => (
            <li key={m.username} className="flex items-center justify-between gap-2">
              <span>{m.display_name} <span className="num text-xs text-muted-foreground">@{m.username}</span>{m.username === group.created_by && <span className="ml-1.5 text-xs text-muted-foreground">{t("admin", "ผู้ดูแล")}</span>}</span>
              {m.username !== group.created_by && (
                <Button type="button" variant="ghost" className="min-h-8" disabled={remove.isPending} onClick={() => confirm(t(`Remove @${m.username} from ${group.name}?`, `ลบ @${m.username} ออกจาก ${group.name}?`)) && remove.mutate(m.username)}>
                  {t("Remove", "ลบ")}
                </Button>
              )}
            </li>
          ))}
        </ul>
        <h3 className="text-sm font-semibold">{t("Add people", "เพิ่มสมาชิก")}</h3>
        <Picker exclude={members} picked={picked} onToggle={(u) => setPicked((s) => flip(s, u))} />
        <DialogFooter className="sm:justify-between">
          <Button type="button" variant="outline" className="text-sev-high-fg" disabled={del.isPending} onClick={() => confirm(t(`Delete ${group.name} for everyone?`, `ลบ ${group.name} สำหรับทุกคน?`)) && del.mutate()}>{t("Delete group", "ลบกลุ่ม")}</Button>
          <span className="flex gap-2">
            <Button type="button" className="bg-brand text-white hover:bg-brand/90" disabled={!picked.size || add.isPending} onClick={() => add.mutate()}>{t("Add selected", "เพิ่มที่เลือก")}</Button>
            <DialogClose render={<Button type="button" variant="outline" />}>{t("Close", "ปิด")}</DialogClose>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Admins only (Team page): create, rename, add or remove people, delete crew chat groups. */
export function GroupAdmin() {
  const t = useT();
  const groups = useQuery({ queryKey: GROUPS, queryFn: listGroups });
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState<string | null>(null);
  const managed = groups.data?.find((g) => g.id === managing);
  return (
    <section aria-labelledby="groups-h" className="rounded-lg border bg-card p-5 md:p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="groups-h" className="text-lg font-semibold text-grey-900 md:text-base">{t("Chat groups", "กลุ่มแชท")}</h2>
        <Button type="button" variant="outline" className="min-h-11 md:min-h-8" onClick={() => setCreating(true)}>
          <Plus className="size-4" aria-hidden />
          {t("New group", "กลุ่มใหม่")}
        </Button>
      </div>
      {groups.isError ? (
        <p role="alert" className="text-sev-high-fg">{groups.error.message}</p>
      ) : !groups.data?.length ? (
        <p className="text-sm text-muted-foreground">{t("No groups yet. Make one for a crew or a job.", "ยังไม่มีกลุ่ม สร้างกลุ่มสำหรับทีมหรืองาน")}</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {groups.data.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-2 py-2 text-sm">
              <span className="flex items-center gap-2"><Users className="size-4 text-muted-foreground" aria-hidden /><b>{g.name}</b> <span className="num text-xs text-muted-foreground">{g.members.length} {t("members", "สมาชิก")}</span></span>
              {g.can_manage && <Button type="button" variant="outline" className="min-h-11 md:min-h-8" onClick={() => setManaging(g.id)}>{t("Manage", "จัดการ")}</Button>}
            </li>
          ))}
        </ul>
      )}
      <NewGroup open={creating} onClose={() => setCreating(false)} />
      {managed && <Manage key={managed.id + managed.members.length} group={managed} onClose={() => setManaging(null)} />}
    </section>
  );
}

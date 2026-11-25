import { api } from "@/lib/api";
import type { Group, Person } from "./messenger";

export interface XmppToken { jid: string; domain: string; running?: boolean }
export interface DirectoryRow { username: string; display_name: string; company: string; can_chat: boolean }

export const getXmppToken = () => api<XmppToken>("/api/xmpp/token");
export const searchDirectory = (q: string) => api<DirectoryRow[]>(`/api/directory?q=${encodeURIComponent(q)}`);
export const listGroups = () => api<Group[]>("/api/groups");
export const createGroup = (name: string, members: string[]) => api<Group>("/api/groups", { body: { name, members } });
export const renameGroup = (id: string, name: string) => api<Group>(`/api/groups/${encodeURIComponent(id)}`, { method: "PATCH", body: { name } });
export const addGroupMembers = (id: string, usernames: string[]) => api<Group>(`/api/groups/${encodeURIComponent(id)}/members`, { body: { usernames } });
export const removeGroupMember = (id: string, username: string) =>
  api<unknown>(`/api/groups/${encodeURIComponent(id)}/members/${encodeURIComponent(username)}`, { method: "DELETE" });
export const deleteGroup = (id: string) => api<unknown>(`/api/groups/${encodeURIComponent(id)}`, { method: "DELETE" });
export type { Group, Person };

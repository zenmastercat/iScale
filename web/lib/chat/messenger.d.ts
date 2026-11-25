/** Types for the copied OMEMO/XMPP code in messenger.js (copied as-is from the old UI; do not edit the logic). */
export interface ChatUser { username: string; display_name: string; role?: string }
export interface Person { username: string; display_name: string; company: string; jid?: string }
export interface GroupMember extends Person { jid: string }
export interface Group {
  id: string;
  name: string;
  created: number;
  jid: string;
  created_by: string | null;
  members: GroupMember[];
  can_manage: boolean;
}
/** A conversation: peer is a username, or "g:<group id>" for a group. */
export interface Conv { peer: string; display_name: string; company?: string; group?: boolean; unread?: number; last?: number; preview?: string }
export interface Msg {
  id: string;
  kind: "text" | "notice" | "location" | "pin" | "finding";
  text?: string;
  lat?: number;
  lon?: number;
  acc?: number;
  pin?: { label: string; severity: string; note?: string; lat: number; lon: number };
  finding?: { label: string; severity?: string; evidence?: string; lat: number; lon: number };
  sent: number;
  from: string;
  from_name?: string;
  out: boolean;
  peer: string;
}
export interface Peer { username: string; display_name?: string; company?: string; group?: boolean }
export interface UiHooks {
  onMessage?: (peer: string, incoming: (Msg & { conv_name: string; group: boolean }) | null) => void;
  onUnread?: (n: number) => void;
  toast?: (msg: string, err?: boolean) => void;
}
export class Messenger {
  constructor(user: ChatUser, ui: UiHooks);
  user: ChatUser;
  xmpp?: { online: boolean };
  start(): Promise<void>;
  stop(): void;
  send(peer: Peer, payload: object): Promise<Msg>;
  sendGroup(g: Group, payload: object): Promise<{ msg: Msg; skipped: string[] }>;
  loadGroups(force?: boolean): Promise<Map<string, Group>>;
  conversations(): Promise<Conv[]>;
  history(peer: string): Promise<Msg[]>;
  markRead(peer: string): Promise<void>;
  unread(): Promise<number>;
  safetyNumber(peerUsername: string): Promise<{ mine: string; theirs: string[] } | null>;
}
export function mapsUrl(lat: number, lon: number): string;

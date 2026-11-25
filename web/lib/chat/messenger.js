/* eslint-disable */
// @ts-nocheck
/* Copied as-is from static/chat.js (the Messenger class, fingerprint, previews) (the old UI); only import paths changed. Typed by messenger.d.ts. */
/* Engineer chat over XMPP with OMEMO end-to-end encryption.

   Transport: XMPP over WebSocket (xmpp.js) to the company's ejabberd, through iScale's /xmpp.
   Encryption: OMEMO (XEP-0384, the "eu.siacs.conversations.axolotl" version used by
   Conversations, Gajim and Monal): each device has a Signal-Protocol identity, publishes its
   key bundle with PEP, and every message is AES-128-GCM encrypted with a fresh key that is
   sent to each recipient device over a Double-Ratchet session. Keys, sessions and the plaintext
   history live only in this browser's IndexedDB; ejabberd only ever sees ciphertext.
   1:1 chats are XMPP "chat" messages to <uid>@domain; groups are members-only XMPP rooms
   (XEP-0045), where a message is encrypted once for all members' devices.
   Conversations are stored under the person's username, or "g:<group id>" for groups. */
import { KeyHelper, SessionBuilder, SessionCipher, SignalProtocolAddress } from "./signal.js";
import { openDb } from "./idb.js";
import { XmppClient, NS, xesc, bare, child, children } from "./xmpp.js";

const HDR = { "X-Civil-Scan": "1", "Content-Type": "application/json" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const ab2b64 = (buf) => { let s = ""; const u = new Uint8Array(buf); for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); };
const b642ab = (b) => { const s = atob(b); const u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u.buffer; };
const sameBuf = (a, b) => { if (!a || !b || a.byteLength !== b.byteLength) return false; const x = new Uint8Array(a), y = new Uint8Array(b); return x.every((v, i) => v === y[i]); };
const PREKEY_BATCH = 100;
const OMEMO = "eu.siacs.conversations.axolotl";
const DEVICELIST = OMEMO + ".devicelist";
const BUNDLES = OMEMO + ".bundles:";
const DATA_PREFIX = "iscale-data:";
const FALLBACK = "This message is end-to-end encrypted with OMEMO. Open it in iScale or an OMEMO-capable XMPP app.";

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { ...HDR, ...(opts.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.detail || r.statusText); e.status = r.status; throw e; }
  return j;
}

/* ---------------------------------------------------------------- Signal store for OMEMO (IndexedDB) */
class Store {
  constructor(db, onIdentityChange) { this.db = db; this.onIdentityChange = onIdentityChange; this.usedPreKeys = 0; }
  kv(k) { return this.db.get("kv", "omemo:" + k); }
  setKv(k, v) { return this.db.put("kv", v, "omemo:" + k); }
  delKv(k) { return this.db.del("kv", "omemo:" + k); }
  async getIdentityKeyPair() { return this.kv("identityKey"); }
  async getLocalRegistrationId() { return this.kv("registrationId"); }
  async isTrustedIdentity() { return true; } // blind trust before verification, as most OMEMO clients; a change is announced
  async saveIdentity(encodedAddress, publicKey) {
    const old = await this.kv("identity:" + encodedAddress);
    await this.setKv("identity:" + encodedAddress, publicKey);
    if (old && !sameBuf(old, publicKey)) { this.onIdentityChange?.(encodedAddress.slice(0, encodedAddress.lastIndexOf("."))); return true; }
    return false;
  }
  async loadPreKey(id) { return this.kv("prekey:" + id); }
  async storePreKey(id, kp) { return this.setKv("prekey:" + id, kp); }
  async removePreKey(id) { this.usedPreKeys++; return this.delKv("prekey:" + id); }
  async loadSignedPreKey(id) { return this.kv("signed:" + id); }
  async storeSignedPreKey(id, kp) { return this.setKv("signed:" + id, kp); }
  async removeSignedPreKey(id) { return this.delKv("signed:" + id); }
  async loadSession(addr) { return this.kv("session:" + addr); }
  async storeSession(addr, rec) { return this.setKv("session:" + addr, rec); }
}

/* Plaintext inside OMEMO: readable text first (so other XMPP apps show something sensible), then one
   data line that iScale reads for locations, pins and survey defects. */
function encodePlain(msg, gid) {
  const human = msg.kind === "text" || msg.kind === "notice" ? msg.text
    : msg.kind === "location" ? `Location: ${(+msg.lat).toFixed(6)}, ${(+msg.lon).toFixed(6)} ${mapsUrl(msg.lat, msg.lon)}`
    : msg.kind === "pin" ? `Pothole pin: ${msg.pin.label} (${msg.pin.severity}) ${msg.pin.note || ""} ${mapsUrl(msg.pin.lat, msg.pin.lon)}`
    : msg.kind === "finding" ? `${msg.finding.label} from a survey: ${msg.finding.evidence || ""} ${mapsUrl(msg.finding.lat, msg.finding.lon)}` : "";
  const { id, sent, v, ...data } = msg;
  if (msg.kind === "text" && !gid) return human;
  return `${human}\n${DATA_PREFIX}${JSON.stringify({ ...data, ...(gid ? { g: gid } : {}) })}`;
}
function decodePlain(text) {
  const i = text.lastIndexOf("\n" + DATA_PREFIX);
  if (i < 0) return { kind: "text", text };
  try { return JSON.parse(text.slice(i + 1 + DATA_PREFIX.length)); } catch { return { kind: "text", text }; }
}

/* ---------------------------------------------------------------- messaging service */
export class Messenger {
  constructor(user, ui) {
    this.user = user;
    this.ui = ui; // { onMessage(convPeer), onUnread(n), toast(msg, err) }
    this.people = new Map();   // bare jid -> {username, display_name, company}
    this.byUser = new Map();   // username -> bare jid
    this.devices = new Map();  // bare jid -> {ids, at}
    this.occupants = new Map(); // room/nick -> real bare jid
    this.joined = new Set();
  }

  async start() {
    this.db = await openDb(`civil-scan-chat-${this.user.username}`, {
      kv: {}, convs: { key: "peer" }, msgs: { key: "id", auto: true, indexes: ["peer"] },
    });
    this.store = new Store(this.db, (jid) => this.identityChanged(jid));
    await this.ensureIdentity();
    this.xmpp = new XmppClient(() => api("/api/xmpp/token"), {
      onOnline: () => this.online().catch((e) => console.warn("chat setup", e)),
      onMessage: (el) => this.onStanza(el).catch((e) => console.warn("chat receive", e)),
      onPresence: (el) => this.onPresence(el),
    });
    this.xmpp.connect().catch((e) => this.ui.toast?.(`Chat is offline: ${e.message}`, true));
  }

  stop() { this.xmpp?.close(); }

  /* -- identity and published keys */
  async ensureIdentity() {
    if (await this.store.getIdentityKeyPair()) return;
    const ik = await KeyHelper.generateIdentityKeyPair();
    await this.store.setKv("identityKey", ik);
    await this.store.setKv("registrationId", KeyHelper.generateRegistrationId());
    await this.store.setKv("deviceId", 1 + Math.floor(Math.random() * 0x7ffffffe));
    const spk = await KeyHelper.generateSignedPreKey(ik, 1);
    await this.store.storeSignedPreKey(1, spk.keyPair);
    await this.store.setKv("signedSig", spk.signature);
    await this.store.setKv("nextPreKeyId", 1);
    await this.store.setKv("prekeyIds", []);
  }

  async online() {
    this.me = bare(this.xmpp.jid);
    this.deviceId = await this.store.kv("deviceId");
    await this.publishBundle();
    const mine = await this.deviceIds(this.me, true);
    if (!mine.includes(this.deviceId)) {
      const list = [...new Set([...mine, this.deviceId])];
      await this.xmpp.publish(DEVICELIST, `<list xmlns="${OMEMO}">${list.map((d) => `<device id="${d}"/>`).join("")}</list>`);
      this.devices.set(this.me, { ids: list, at: Date.now() });
    }
    this.xmpp.raw(`<presence xmlns="${NS.client}"><priority>1</priority></presence>`); // offline messages arrive now
    await this.loadGroups(true).catch(() => {});
    for (const g of this.groups?.values() || []) this.joinRoom(g);
  }

  async publishBundle() {
    let ids = (await this.store.kv("prekeyIds")) || [];
    const alive = [];
    for (const id of ids) if (await this.store.loadPreKey(id)) alive.push(id);
    if (alive.length < PREKEY_BATCH) alive.push(...(await this.makePreKeys(PREKEY_BATCH - alive.length)));
    ids = alive;
    await this.store.setKv("prekeyIds", ids);
    const ik = await this.store.getIdentityKeyPair();
    const spk = await this.store.loadSignedPreKey(1);
    const sig = await this.store.kv("signedSig");
    const pre = [];
    for (const id of ids) pre.push(`<preKeyPublic preKeyId="${id}">${ab2b64((await this.store.loadPreKey(id)).pubKey)}</preKeyPublic>`);
    await this.xmpp.publish(BUNDLES + this.deviceId, `<bundle xmlns="${OMEMO}">
      <signedPreKeyPublic signedPreKeyId="1">${ab2b64(spk.pubKey)}</signedPreKeyPublic><signedPreKeySignature>${ab2b64(sig)}</signedPreKeySignature>
      <identityKey>${ab2b64(ik.pubKey)}</identityKey><prekeys>${pre.join("")}</prekeys></bundle>`);
    this.store.usedPreKeys = 0;
  }

  async makePreKeys(n) {
    let next = (await this.store.kv("nextPreKeyId")) || 1;
    const out = [];
    for (let i = 0; i < n; i++, next++) {
      const id = ((next - 1) % 16000000) + 1;
      const pk = await KeyHelper.generatePreKey(id);
      await this.store.storePreKey(id, pk.keyPair);
      out.push(id);
    }
    await this.store.setKv("nextPreKeyId", next);
    return out;
  }

  async deviceIds(jid, fresh = false) {
    const c = this.devices.get(jid);
    if (!fresh && c && Date.now() - c.at < 60000) return c.ids;
    let ids = [];
    try {
      const items = await this.xmpp.items(jid, DEVICELIST);
      ids = children(child(items[0], "list", OMEMO), "device").map((d) => +d.getAttribute("id")).filter((n) => n > 0);
    } catch (e) {
      if (e.condition !== "item-not-found") throw e;
    }
    this.devices.set(jid, { ids, at: Date.now() });
    return ids;
  }

  async session(jid, deviceId) {
    const addr = new SignalProtocolAddress(jid, deviceId);
    if (await this.store.loadSession(addr.toString())) return addr;
    const items = await this.xmpp.items(jid, BUNDLES + deviceId);
    const b = child(items[0], "bundle", OMEMO);
    if (!b) throw new Error("no key bundle");
    const spk = child(b, "signedPreKeyPublic", OMEMO);
    const pre = children(child(b, "prekeys", OMEMO), "preKeyPublic", OMEMO);
    const pick = pre[Math.floor(Math.random() * pre.length)];
    await new SessionBuilder(this.store, addr).processPreKey({
      registrationId: deviceId, identityKey: b642ab(child(b, "identityKey", OMEMO).textContent),
      signedPreKey: { keyId: +spk.getAttribute("signedPreKeyId"), publicKey: b642ab(spk.textContent), signature: b642ab(child(b, "signedPreKeySignature", OMEMO).textContent) },
      preKey: pick ? { keyId: +pick.getAttribute("preKeyId"), publicKey: b642ab(pick.textContent) } : undefined,
    });
    return addr;
  }

  /* OMEMO-encrypt plaintext for every device of `jids` (and our own other devices). */
  async encrypt(jids, plaintext) {
    const key = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ck = await crypto.subtle.importKey("raw", key, "AES-GCM", false, ["encrypt"]);
    const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv, tagLength: 128 }, ck, new TextEncoder().encode(plaintext)));
    const payload = sealed.slice(0, sealed.length - 16);
    const material = new Uint8Array(32);
    material.set(key, 0);
    material.set(sealed.slice(sealed.length - 16), 16);
    const keys = [], missing = [];
    for (const jid of [...new Set([...jids, this.me])]) {
      const ids = (await this.deviceIds(jid)).filter((d) => !(jid === this.me && d === this.deviceId));
      if (!ids.length && jid !== this.me) { missing.push(jid); continue; }
      for (const d of ids) {
        try {
          const addr = await this.session(jid, d);
          const ct = await new SessionCipher(this.store, addr).encrypt(material.buffer);
          keys.push(`<key rid="${d}"${ct.type === 3 ? ' prekey="true"' : ""}>${btoa(ct.body)}</key>`);
        } catch (e) { console.warn("no OMEMO session", jid, d, e); }
      }
    }
    return { xml: `<encrypted xmlns="${OMEMO}"><header sid="${this.deviceId}">${keys.join("")}<iv>${ab2b64(iv)}</iv></header><payload>${ab2b64(payload)}</payload></encrypted>`, missing, count: keys.length };
  }

  async decrypt(fromJid, enc) {
    const header = child(enc, "header", OMEMO);
    const sid = +header.getAttribute("sid");
    const key = children(header, "key", OMEMO).find((k) => +k.getAttribute("rid") === this.deviceId);
    if (!key) return null; // not encrypted for this device
    const cipher = new SessionCipher(this.store, new SignalProtocolAddress(fromJid, sid));
    const body = atob(key.textContent);
    const isPre = key.getAttribute("prekey") === "true" || key.getAttribute("prekey") === "1";
    const material = new Uint8Array(isPre ? await cipher.decryptPreKeyWhisperMessage(body, "binary") : await cipher.decryptWhisperMessage(body, "binary"));
    if (this.store.usedPreKeys) this.publishBundle().catch(() => {});   // replace the one-time key that was used
    const p = child(enc, "payload", OMEMO);
    if (!p) return null; // key-transport message
    const iv = new Uint8Array(b642ab(child(header, "iv", OMEMO).textContent));
    const ct = new Uint8Array(b642ab(p.textContent));
    const tag = material.length >= 32 ? material.slice(16, 32) : new Uint8Array(0);
    const ck = await crypto.subtle.importKey("raw", material.slice(0, 16), "AES-GCM", false, ["decrypt"]);
    const all = new Uint8Array(ct.length + tag.length);
    all.set(ct, 0);
    all.set(tag, ct.length);
    return new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv, tagLength: 128 }, ck, all));
  }

  /* -- who is who: JIDs carry a hashed id, iScale knows the name */
  async jidOf(username) {
    if (this.byUser.has(username)) return this.byUser.get(username);
    const p = await api(`/api/xmpp/jid?username=${encodeURIComponent(username)}`);
    this.remember(p);
    return p.jid;
  }
  remember(p) { if (p?.jid) { this.people.set(p.jid, p); this.byUser.set(p.username, p.jid); } }
  async personOf(jid) {
    if (this.people.has(jid)) return this.people.get(jid);
    try { const p = await api(`/api/xmpp/whois?jid=${encodeURIComponent(jid)}`); this.remember(p); return p; }
    catch { return { username: jid.split("@")[0], display_name: "Unknown engineer", company: "", jid }; }
  }

  /* -- sending */
  async send(peer, payload) {
    if (!this.xmpp?.online) throw new Error("chat is offline; try again in a moment");
    const jid = await this.jidOf(peer.username);
    const msg = { v: 1, id: crypto.randomUUID(), sent: Date.now(), ...payload };
    const enc = await this.encrypt([jid], encodePlain(msg));
    if (enc.missing.includes(jid)) throw new Error(`${peer.display_name || peer.username} hasn't opened iScale chat on any device yet`);
    this.xmpp.raw(`<message xmlns="${NS.client}" to="${xesc(jid)}" type="chat" id="${msg.id}">${enc.xml}<store xmlns="${NS.hints}"/>`
      + `<encryption xmlns="${NS.eme}" namespace="${OMEMO}" name="OMEMO"/><origin-id xmlns="${NS.sid}" id="${msg.id}"/><body>${xesc(FALLBACK)}</body></message>`);
    await this.saveMsg(peer, { ...msg, from: this.user.username, out: true });
    return msg;
  }

  /* -- groups: iScale keeps the roster and mirrors it into an XMPP room */
  async loadGroups(force = false) {
    if (!force && this.groupsAt && Date.now() - this.groupsAt < 15000) return this.groups;
    const list = await api("/api/groups");
    this.groups = new Map(list.map((g) => [g.id, g]));
    this.groupsAt = Date.now();
    for (const g of list) {
      for (const m of g.members) this.remember(m);
      const c = await this.db.get("convs", "g:" + g.id);
      if (c && c.display_name !== g.name) { c.display_name = g.name; await this.db.put("convs", c); }
      if (this.xmpp?.online) this.joinRoom(g);
    }
    return this.groups;
  }

  joinRoom(g) {
    if (this.joined.has(g.jid) || !this.xmpp?.online) return;
    this.joined.add(g.jid);
    this.store.kv("roomSeen:" + g.jid).then((since) => {
      const hist = since ? `<history since="${new Date(since).toISOString()}"/>` : `<history maxstanzas="200"/>`;
      this.xmpp.raw(`<presence xmlns="${NS.client}" to="${xesc(g.jid)}/${xesc(this.me.split("@")[0])}"><x xmlns="${NS.muc}">${hist}</x></presence>`);
    });
  }

  groupPeer(g) { return { username: "g:" + g.id, display_name: g.name, company: `${g.members.length} ${g.members.length === 1 ? "member" : "members"}`, group: true }; }

  async sendGroup(g, payload) {
    if (!this.xmpp?.online) throw new Error("chat is offline; try again in a moment");
    this.joinRoom(g);
    const msg = { v: 1, id: crypto.randomUUID(), sent: Date.now(), group: g.id, ...payload };
    const jids = g.members.filter((m) => m.username !== this.user.username).map((m) => m.jid);
    const enc = await this.encrypt(jids, encodePlain(msg, g.id));
    this.xmpp.raw(`<message xmlns="${NS.client}" to="${xesc(g.jid)}" type="groupchat" id="${msg.id}">${enc.xml}<store xmlns="${NS.hints}"/>`
      + `<encryption xmlns="${NS.eme}" namespace="${OMEMO}" name="OMEMO"/><origin-id xmlns="${NS.sid}" id="${msg.id}"/><body>${xesc(FALLBACK)}</body></message>`);
    await this.saveMsg(this.groupPeer(g), { ...msg, from: this.user.username, out: true });
    const skipped = g.members.filter((m) => enc.missing.includes(m.jid)).map((m) => m.display_name);
    return { msg, skipped };
  }

  /* -- receiving */
  onPresence(el) {
    const from = el.getAttribute("from") || "";
    const item = child(child(el, "x", NS.mucUser), "item");
    if (item?.getAttribute("jid")) this.occupants.set(from, bare(item.getAttribute("jid")));
  }

  async onStanza(el) {
    const type = el.getAttribute("type") || "normal";
    const from = el.getAttribute("from") || "";
    if (type === "error") return this.bounced(el, from);
    const enc = child(el, "encrypted", OMEMO);
    const originId = child(el, "origin-id", NS.sid)?.getAttribute("id") || el.getAttribute("id") || crypto.randomUUID();
    const stamp = child(el, "delay", NS.delay)?.getAttribute("stamp");
    const sent = stamp ? Date.parse(stamp) : Date.now();
    if (await this.store.kv("seen:" + originId)) return;   // already have it (room history, carbons)
    let peer, fromJid, group = null;
    if (type === "groupchat") {
      const roomJid = bare(from);
      const nick = from.slice(roomJid.length + 1);
      if (!nick) return;  // room subject or status
      fromJid = this.occupants.get(from) || `${nick}@${this.xmpp.domain}`;
      await this.store.setKv("roomSeen:" + roomJid, Math.max(sent, (await this.store.kv("roomSeen:" + roomJid)) || 0));
      if (fromJid === this.me) return;   // our own message reflected by the room
      const gid = roomJid.split("@")[0].replace(/^g/, "");
      const groups = this.groups?.has(gid) ? this.groups : await this.loadGroups(true).catch(() => new Map());
      group = groups.get(gid);
      peer = group ? this.groupPeer(group) : { username: "g:" + gid, display_name: "Group", company: "", group: true };
    } else {
      fromJid = bare(from);
      if (fromJid === this.me || !fromJid.includes("@")) return;
      const p = await this.personOf(fromJid);
      peer = { username: p.username, display_name: p.display_name, company: p.company };
    }
    if (!enc && !child(el, "body")) return;   // chat states, receipts
    const sender = await this.personOf(fromJid);
    let msg;
    if (!enc) {
      msg = { kind: "text", text: `(Not encrypted) ${child(el, "body").textContent}` };
    } else {
      try {
        const plain = await this.decrypt(fromJid, enc);
        if (plain === null) return;
        msg = decodePlain(plain);
      } catch (e) {
        msg = { kind: "notice", text: "A message couldn't be decrypted on this device." };
      }
    }
    if (group || type === "groupchat") {
      if (msg.kind !== "notice" && msg.g !== peer.username.slice(2)) msg = { kind: "notice", text: "A group message was dropped because its room didn't match its encrypted content." };
      msg.group = peer.username.slice(2);
    } else delete msg.group;
    delete msg.g;
    await this.store.setKv("seen:" + originId, 1);
    await this.saveMsg(peer, { v: 1, ...msg, id: originId, sent, from: sender.username, from_name: sender.display_name, out: false }, true);
  }

  /* The server sent one of our messages back (person unknown, removed from a room, ...). */
  async bounced(el, from) {
    const cond = child(el, "error")?.firstElementChild?.localName || "error";
    const why = cond === "forbidden" || cond === "not-acceptable" || cond === "registration-required" ? "you're not a member of this group any more"
      : cond === "service-unavailable" || cond === "item-not-found" ? "the chat server doesn't know this person"
      : `the chat server refused it (${cond})`;
    const roomJid = bare(from);
    let peer;
    if (roomJid.endsWith("@" + (this.xmpp.muc || "conference." + this.xmpp.domain))) peer = "g:" + roomJid.split("@")[0].replace(/^g/, "");
    else peer = (await this.personOf(roomJid)).username;
    await this.notice(peer, `A message wasn't delivered: ${why}.`);
  }

  async identityChanged(jid) {
    const p = await this.personOf(jid);
    await this.notice(p.username, `Security code changed: ${p.display_name} is using a new device or app.`);
  }

  async saveMsg(peer, msg, incoming = false) {
    await this.db.put("msgs", { ...msg, peer: peer.username });
    const conv = (await this.db.get("convs", peer.username)) || { peer: peer.username, unread: 0 };
    conv.display_name = peer.display_name || conv.display_name || peer.username;
    conv.company = peer.company || conv.company || "";
    if (peer.group) conv.group = true;
    conv.last = msg.sent;
    conv.preview = preview(msg);
    if (incoming) conv.unread = (conv.unread || 0) + 1;
    await this.db.put("convs", conv);
    this.ui.onMessage?.(peer.username, incoming ? { ...msg, conv_name: conv.display_name, group: !!conv.group } : null);
    this.ui.onUnread?.(await this.unread());
  }

  async notice(peer, text) {
    await this.saveMsg({ username: peer }, { v: 1, id: crypto.randomUUID(), kind: "notice", text, sent: Date.now(), from: "", out: false });
  }

  async unread() { return (await this.db.all("convs")).reduce((t, c) => t + (c.unread || 0), 0); }
  async conversations() { return (await this.db.all("convs")).sort((a, b) => (b.last || 0) - (a.last || 0)); }
  async history(peer) { return (await this.db.byIndex("msgs", "peer", peer)).sort((a, b) => a.sent - b.sent); }
  async markRead(peer) {
    const c = await this.db.get("convs", peer);
    if (c && c.unread) { c.unread = 0; await this.db.put("convs", c); this.ui.onUnread?.(await this.unread()); }
  }

  /* OMEMO fingerprints (the hex form Conversations, Gajim and Monal show): this device and theirs */
  async safetyNumber(peerUsername) {
    const jid = await this.jidOf(peerUsername).catch(() => null);
    if (!jid) return null;
    const fmt = (buf) => [...new Uint8Array(buf).slice(1)].map((b) => b.toString(16).padStart(2, "0")).join("").match(/.{8}/g).join(" ");
    const mine = fmt((await this.store.getIdentityKeyPair()).pubKey);
    const theirs = [];
    for (const d of await this.deviceIds(jid).catch(() => [])) {
      const k = await this.store.kv(`identity:${jid}.${d}`);
      if (k) theirs.push(fmt(k));
    }
    if (!theirs.length) return null;
    return { mine, theirs };
  }
}

/* Signal's displayable fingerprint (version 0, 5200 SHA-512 rounds per side), computed with the
   browser's native WebCrypto. Same output as the bundled FingerprintGenerator, which hashes in
   pure JS and takes ~45 s. */
const FP_ITERATIONS = 5200;
const concat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.byteLength, 0)); let o = 0; for (const p of parts) { out.set(new Uint8Array(p), o); o += p.byteLength; } return out; };
const chunk5 = (b, i) => String((b[i] * 2 ** 32 + b[i + 1] * 2 ** 24 + b[i + 2] * 2 ** 16 + b[i + 3] * 2 ** 8 + b[i + 4]) % 1e5).padStart(5, "0");
async function displayPart(id, pubKey, n = FP_ITERATIONS) {
  const idBytes = Uint8Array.from(id, (c) => c.charCodeAt(0) & 0xff);   // binaryStringToArrayBuffer
  let h = concat(new Uint16Array([0]).buffer, pubKey, idBytes);
  for (let i = 0; i < n; i++) h = new Uint8Array(await crypto.subtle.digest("SHA-512", concat(h, pubKey)));
  return [0, 5, 10, 15, 20, 25].map((i) => chunk5(h, i)).join("");
}
export async function fingerprint(localId, localKey, remoteId, remoteKey, n = FP_ITERATIONS) {
  const [a, b] = await Promise.all([displayPart(localId, localKey, n), displayPart(remoteId, remoteKey, n)]);
  return [a, b].sort().join("");
}

function preview(m) {
  const who = m.from_name && !m.out ? `${m.from_name.split(" ")[0]}: ` : "";
  if (m.group && m.kind !== "notice") return who + previewText(m);
  return previewText(m);
}
function previewText(m) {
  if (m.kind === "location") return "Shared a location";
  if (m.kind === "pin") return `Pothole pin: ${m.pin?.label || ""}`;
  if (m.kind === "finding") return `${m.finding?.label || "Defect"} from a survey`;
  if (m.kind === "notice") return m.text;
  return (m.text || "").slice(0, 80);
}

export const mapsUrl = (lat, lon) => `https://www.google.com/maps/@?api=1&map_action=map&center=${(+lat).toFixed(6)},${(+lon).toFixed(6)}&zoom=18&layer=traffic`;


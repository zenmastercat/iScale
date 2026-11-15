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
import * as loc from "./location.js";
import { KeyHelper, SessionBuilder, SessionCipher, SignalProtocolAddress } from "./vendor/signal/signal.js";
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

/* ---------------------------------------------------------------- UI */
const SEG = typeof Intl !== "undefined" && Intl.Segmenter ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;
const firstGrapheme = (w) => (SEG ? SEG.segment(w)[Symbol.iterator]().next().value?.segment : Array.from(w)[0]) || "";
const SUFFIX = /^(jr|sr|ii|iii|iv|phd|pe)\.?$/i;
/* Initials from whole characters: first and last word, skipping suffixes (III, Jr) and words that
   don't start with a letter (an emoji). Thai, Vietnamese and emoji-first names stay intact. */
function initials(name) {
  const words = String(name || "").replace(/^g:/, "").split(/\s+/).filter((w) => w && !SUFFIX.test(w) && /^\p{L}/u.test(w));
  if (!words.length) return firstGrapheme(String(name || "?").trim()) || "?";
  const pick = words.length > 1 ? [words[0], words[words.length - 1]] : [words[0]];
  return pick.map((w) => firstGrapheme(w).toLocaleUpperCase()).join("");
}
const members = (n) => `${n.toLocaleString()} ${n === 1 ? "member" : "members"}`;
const hue = (key) => { let h = 0; for (const c of String(key)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const avatar = (key, name, group = false) => `<span class="avatar${group ? " group" : ""}" style="--h:${hue(key)}" aria-hidden="true">${group ? GROUP_ICON : esc(initials(name))}</span>`;
const GROUP_ICON = `<svg viewBox="0 0 20 20" width="16" height="16" fill="currentColor"><circle cx="7" cy="7" r="3"/><circle cx="14" cy="8" r="2.4"/><path d="M1.5 16.5c.6-3 2.8-4.8 5.5-4.8s4.9 1.8 5.5 4.8z"/><path d="M13 16.5c-.2-1.6-.8-2.9-1.8-3.9.7-.4 1.5-.6 2.4-.6 2.3 0 4 1.5 4.6 4.5z"/></svg>`;

export function chatView(root, messenger, hooks) {
  // hooks: { onShowOnMap(lat, lon), pickAttachment() -> Promise<payload|null>, toast(msg, err), takePending() }
  let current = null;
  const me = messenger.user;
  const isAdmin = me.role === "admin";
  root.innerHTML = `
    <div class="msg-layout">
      <aside class="conv-list">
        <div class="conv-top">
          <form class="conv-search" id="convSearch">
            <input class="input" id="peerSearch" placeholder="Find by name or username" autocomplete="off" aria-label="Find an engineer" autocapitalize="none">
          </form>
          ${isAdmin ? `<button class="btn small" id="newGroup" type="button">New group</button>` : ""}
        </div>
        <div id="peerResults"></div>
        <div id="convItems"></div>
      </aside>
      <section class="thread" id="thread">
        <div class="thread-empty">
          <div class="lock-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div>
          <h2>Talk to your crew</h2>
          <p>Find an engineer by username to start a chat, or open a conversation on the left.${isAdmin ? " As an admin you can also start a group for a crew or a job." : ""}</p>
          <p class="muted small">End-to-end encrypted with OMEMO over XMPP. Messages are stored only on your devices; the company's XMPP server passes them on and deletes them once delivered.</p>
        </div>
      </section>
    </div>`;

  const convItems = root.querySelector("#convItems");
  const results = root.querySelector("#peerResults");
  const thread = root.querySelector("#thread");

  async function renderConvs() {
    const convs = await messenger.conversations();
    const groups = await messenger.loadGroups().catch(() => new Map());
    const seen = new Set(convs.map((c) => c.peer));
    for (const g of groups.values()) {   // groups you're in show up before their first message
      if (!seen.has("g:" + g.id)) convs.push({ peer: "g:" + g.id, display_name: g.name, group: true, preview: "No messages yet", last: g.created * 1000 });
    }
    // conversations of groups you've left stay readable, marked as left
    convs.sort((a, b) => (b.last || 0) - (a.last || 0));
    convItems.innerHTML = convs.length ? convs.map((c) => {
      const g = c.group ? groups.get(c.peer.slice(2)) : null;
      const sub = c.group ? (g ? members(g.members.length) : "You're no longer in this group") : `@${esc(c.peer)}${c.company ? ", " + esc(c.company) : ""}`;
      return `<button class="conv${current?.username === c.peer ? " on" : ""}" data-peer="${esc(c.peer)}" type="button">
        ${avatar(c.peer, c.display_name, c.group)}
        <span class="conv-text"><span class="conv-name">${esc(g?.name || c.display_name)}${c.unread ? `<span class="badge-n">${c.unread}</span>` : ""}</span>
        <span class="conv-sub">${sub}</span>
        <span class="conv-prev">${esc(c.preview || "")}</span></span></button>`;
    }).join("") : `<p class="muted small conv-none">No conversations yet. Search for a colleague above.</p>`;
  }

  async function searchPeople(q, target, { pick = false, exclude = new Set() } = {}) {
    if (!q) { target.innerHTML = ""; return; }
    try {
      const rows = (await api(`/api/directory?q=${encodeURIComponent(q)}`)).filter((r) => !exclude.has(r.username));
      target.innerHTML = rows.length ? rows.map((r) => `<button class="conv result" data-${pick ? "pick" : "peer"}="${esc(r.username)}" data-name="${esc(r.display_name)}" data-company="${esc(r.company)}" ${r.can_chat ? "" : "disabled"} type="button">
          ${avatar(r.username, r.display_name)}
          <span class="conv-text"><span class="conv-name">${esc(r.display_name)}</span><span class="conv-sub">@${esc(r.username)}, ${esc(r.company)}${r.can_chat ? "" : " (hasn't signed in yet)"}</span></span></button>`).join("")
        : `<p class="muted small conv-none">Nobody matches. People in other companies are found by their exact username.</p>`;
    } catch (err) { hooks.toast(err.message, true); }
  }

  let searchTimer = 0;
  root.querySelector("#peerSearch").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    searchTimer = setTimeout(() => searchPeople(q, results), q ? 250 : 0);
  });
  root.querySelector("#convSearch").addEventListener("submit", (e) => e.preventDefault());
  root.querySelector("#newGroup")?.addEventListener("click", () => groupDialog());

  root.addEventListener("click", async (e) => {
    const c = e.target.closest(".conv-list [data-peer]");
    if (c && !c.disabled) {
      results.innerHTML = "";
      root.querySelector("#peerSearch").value = "";
      await open({ username: c.dataset.peer, display_name: c.dataset.name, company: c.dataset.company });
      return;
    }
    const act = e.target.closest("[data-act]");
    if (!act) return;
    if (act.dataset.act === "back") { root.querySelector(".msg-layout").classList.remove("thread-open"); return; }
    if (act.dataset.act === "map") hooks.onShowOnMap(+act.dataset.lat, +act.dataset.lon);
    if (act.dataset.act === "code") showCode();
    if (act.dataset.act === "members") membersDialog();
    if (act.dataset.act === "locate") shareLocation();
    if (act.dataset.act === "attach") {
      const payload = await hooks.pickAttachment();
      if (payload) await sendPayload(payload);
    }
  });

  async function open(peer) {
    const conv = await messenger.db.get("convs", peer.username);
    if (peer.username.startsWith("g:")) {
      const g = (await messenger.loadGroups(true).catch(() => new Map())).get(peer.username.slice(2));
      current = { username: peer.username, group: g || null, display_name: g?.name || conv?.display_name || "Group" };
    } else {
      current = { username: peer.username, display_name: peer.display_name || conv?.display_name || peer.username, company: peer.company || conv?.company || "" };
    }
    await messenger.markRead(peer.username);
    const isGroup = peer.username.startsWith("g:");
    const canWrite = !isGroup || current.group;
    root.querySelector(".msg-layout").classList.add("thread-open");
    thread.innerHTML = `
      <header class="thread-head">
        <button class="btn small quiet thread-back" data-act="back" type="button" aria-label="Back to conversations"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M10 3L5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
        ${avatar(current.username, current.display_name, isGroup)}
        <div class="thread-title"><b>${esc(current.display_name)}</b><span class="muted small">${isGroup
          ? (current.group ? esc(current.group.members.map((m) => m.display_name.split(" ")[0]).join(", ")) : "You're no longer in this group")
          : `@${esc(current.username)}${current.company ? ", " + esc(current.company) : ""}`}</span></div>
        ${isGroup ? (current.group ? `<button class="btn small quiet" data-act="members" type="button">Members</button>` : "")
          : `<button class="btn small quiet" data-act="code" type="button">Security code</button>`}</header>
      <div class="bubbles" id="bubbles" aria-live="polite"></div>
      ${canWrite ? `<form class="composer" id="composer">
        <button class="btn small icon-btn" data-act="locate" type="button" title="Share my location" aria-label="Share my location"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M10 18s6-5.2 6-10a6 6 0 0 0-12 0c0 4.8 6 10 6 10z"/><circle cx="10" cy="8" r="2.2"/></svg><span>Location</span></button>
        <button class="btn small icon-btn" data-act="attach" type="button" title="Share a pothole" aria-label="Share a pothole"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7"><ellipse cx="10" cy="11" rx="7" ry="4"/><path d="M6 10.5c1.2.8 2.5 1.1 4 1.1s2.8-.3 4-1.1"/></svg><span>Pothole</span></button>
        <input class="input" id="msgText" placeholder="${isGroup ? "Message the group" : "Message"}" autocomplete="off" maxlength="4000" enterkeyhint="send" aria-label="Message">
        <button class="btn primary" type="submit">Send</button>
      </form>` : ""}`;
    thread.querySelector("#composer")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const t = thread.querySelector("#msgText");
      const text = t.value.trim();
      if (!text) return;
      t.value = "";
      await sendPayload({ kind: "text", text });
    });
    await renderThread();
    await renderConvs();
    const pending = hooks.takePending?.();
    if (pending && canWrite) await sendPayload(pending);
    thread.querySelector("#msgText")?.focus();
  }

  async function sendPayload(payload) {
    if (!current) return;
    try {
      if (current.group) {
        const { skipped } = await messenger.sendGroup(current.group, payload);
        if (skipped.length) hooks.toast(`Not delivered to ${skipped.join(", ")}: they haven't signed in on a device yet.`);
      } else {
        await messenger.send(current, payload);
      }
      await renderThread();
      await renderConvs();
    } catch (err) { hooks.toast(`Not sent: ${err.message}`, true); }
  }

  async function shareLocation() {
    try { if (!(await loc.ensure("Sharing your location in chat uses it."))) return; }
    catch (err) { return hooks.toast(err.message, true); }
    navigator.geolocation.getCurrentPosition(
      (p) => sendPayload({ kind: "location", lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.round(p.coords.accuracy) }),
      (err) => hooks.toast(`Location unavailable: ${err.message}. Browsers allow it only on HTTPS or localhost.`, true),
      { enableHighAccuracy: true, timeout: 15000 });
  }

  function dialog(html) {
    const d = document.createElement("dialog");
    d.className = "dialog";
    d.innerHTML = html;
    document.body.appendChild(d);
    d.addEventListener("close", () => d.remove());
    d.showModal();
    return d;
  }

  async function showCode() {
    const code = await messenger.safetyNumber(current.username);
    dialog(`<form method="dialog"><h2>Security codes with ${esc(current.display_name)}</h2>
      ${code ? `<p class="muted small">Your device</p><p class="safety">${esc(code.mine)}</p>
        <p class="muted small">${esc(current.display_name)}'s ${code.theirs.length === 1 ? "device" : "devices"}</p>${code.theirs.map((t) => `<p class="safety">${esc(t)}</p>`).join("")}
        <p class="muted small">These are OMEMO fingerprints. Compare them with what ${esc(current.display_name.split(" ")[0])} sees, in person or on a call. If they match, nobody is reading your messages in between.</p>`
        : `<p class="muted">Send or receive a message first.</p>`}
      <div class="dialog-actions"><button class="btn primary" value="ok">Close</button></div></form>`);
  }

  /* -- people picker shared by "New group" and "Add people" */
  async function candidates(exclude) {
    const out = new Map();
    const team = await api("/api/team").catch(() => []);
    for (const t of team) if (!t.disabled && t.username !== me.username) out.set(t.username, { username: t.username, display_name: t.display_name, sub: "Your company", ready: t.device_bound });
    for (const c of await messenger.conversations()) {
      if (c.group || out.has(c.peer) || c.peer === me.username) continue;
      out.set(c.peer, { username: c.peer, display_name: c.display_name, sub: `You've talked${c.company ? ", " + c.company : ""}`, ready: true });
    }
    return [...out.values()].filter((p) => !exclude.has(p.username)).sort((a, b) => a.display_name.localeCompare(b.display_name));
  }
  const pickRow = (p, checked = false) => `<label class="pick-row"><input type="checkbox" name="m" value="${esc(p.username)}" ${checked ? "checked" : ""} ${p.ready === false ? "disabled" : ""}>
      ${avatar(p.username, p.display_name)}<span class="conv-text"><span class="conv-name">${esc(p.display_name)}</span><span class="conv-sub">@${esc(p.username)}, ${esc(p.sub)}${p.ready === false ? " (hasn't signed in yet)" : ""}</span></span></label>`;

  function wirePicker(d, exclude) {
    const list = d.querySelector(".pick-list");
    const extra = d.querySelector(".pick-search-results");
    let t = 0;
    d.querySelector(".pick-search").addEventListener("input", (e) => {
      clearTimeout(t);
      const q = e.target.value.trim();
      t = setTimeout(() => searchPeople(q, extra, { pick: true, exclude: new Set([...exclude, me.username, ...[...list.querySelectorAll("input")].map((i) => i.value)]) }), q ? 250 : 0);
    });
    extra.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pick]");
      if (!b || b.disabled) return;
      list.insertAdjacentHTML("afterbegin", pickRow({ username: b.dataset.pick, display_name: b.dataset.name, sub: b.dataset.company }, true));
      b.remove();
      const counter = d.querySelector(".pick-count");
      if (counter) counter.dispatchEvent(new Event("refresh"));
    });
    const counter = d.querySelector(".pick-count");
    const update = () => { const n = list.querySelectorAll("input:checked").length; counter.textContent = n ? `${n} selected` : "Nobody selected yet"; };
    list.addEventListener("change", update);
    counter.addEventListener("refresh", update);
    update();
  }
  const pickerHtml = (people) => `
      <input class="input pick-search" placeholder="Add anyone on this server by username" autocomplete="off" autocapitalize="none" aria-label="Search by username">
      <div class="pick-search-results"></div>
      <div class="pick-list">${people.length ? people.map((p) => pickRow(p)).join("") : `<p class="muted small">Nobody to suggest yet. Search by username above.</p>`}</div>
      <p class="muted small pick-count" aria-live="polite"></p>`;

  async function groupDialog() {
    const people = await candidates(new Set());
    const d = dialog(`<form class="group-form"><h2>New group</h2>
      <p class="muted small">Pick a crew from your company or anyone you've talked to. Everyone sees messages from the moment they join.</p>
      <label class="field"><span>Group name</span><input class="input" name="name" required maxlength="80" placeholder="e.g. Night patch crew, Zone 3"></label>
      ${pickerHtml(people)}
      <div class="dialog-actions"><button class="btn" value="cancel" formmethod="dialog" formnovalidate>Cancel</button><button class="btn primary" type="submit">Create group</button></div></form>`);
    wirePicker(d, new Set());
    d.querySelector("form").addEventListener("submit", async (e) => {
      if (e.submitter?.value === "cancel") return;
      e.preventDefault();
      const f = e.target;
      const members = [...f.querySelectorAll("input[name=m]:checked")].map((i) => i.value);
      if (!members.length) return hooks.toast("Pick at least one person.", true);
      try {
        const g = await api("/api/groups", { method: "POST", body: JSON.stringify({ name: f.name.value.trim(), members }) });
        d.close();
        await messenger.loadGroups(true);
        await open({ username: "g:" + g.id });
        await sendPayload({ kind: "notice", text: `${me.display_name} created the group "${g.name}".` });
      } catch (err) { hooks.toast(err.message, true); }
    });
  }

  async function membersDialog() {
    const g = (await messenger.loadGroups(true)).get(current.username.slice(2));
    if (!g) return;
    const d = dialog(`<form method="dialog" class="group-form"><h2>${esc(g.name)}</h2>
      ${g.can_manage ? `<label class="field"><span>Group name</span><span class="inline-form name-row"><input class="input" name="name" value="${esc(g.name)}" maxlength="80"><button class="btn small" data-g="rename" type="button">Rename</button></span></label>` : ""}
      <h3>${members(g.members.length)}</h3>
      <div class="member-list">${g.members.map((m) => `<div class="pick-row">${avatar(m.username, m.display_name)}
        <span class="conv-text"><span class="conv-name">${esc(m.display_name)}${m.username === g.created_by ? ` <span class="tag">admin</span>` : ""}</span><span class="conv-sub">@${esc(m.username)}${m.company && m.company !== me.company ? ", " + esc(m.company) : ""}</span></span>
        ${g.can_manage && m.username !== me.username ? `<button class="btn small quiet" data-g="remove" data-u="${esc(m.username)}" type="button">Remove</button>` : ""}</div>`).join("")}</div>
      ${g.can_manage ? `<h3>Add people</h3>${pickerHtml(await candidates(new Set(g.members.map((m) => m.username))))}` : ""}
      <div class="dialog-actions spread">
        <span>${g.can_manage ? `<button class="btn small danger" data-g="delete" type="button">Delete group</button>` : ""}
        <button class="btn small quiet" data-g="leave" type="button">Leave group</button></span>
        <span>${g.can_manage ? `<button class="btn primary" data-g="add" type="button">Add selected</button>` : ""}<button class="btn" value="ok">Close</button></span></div></form>`);
    if (g.can_manage) wirePicker(d, new Set(g.members.map((m) => m.username)));
    d.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-g]");
      if (!b) return;
      const base = `/api/groups/${encodeURIComponent(g.id)}`;
      try {
        if (b.dataset.g === "rename") {
          const name = d.querySelector("input[name=name]").value.trim();
          if (!name) return;
          await api(base, { method: "PATCH", body: JSON.stringify({ name }) });
          await sendPayload({ kind: "notice", text: `${me.display_name} renamed the group to "${name}".` });
        }
        if (b.dataset.g === "add") {
          const usernames = [...d.querySelectorAll(".pick-list input[name=m]:checked")].map((i) => i.value);
          if (!usernames.length) return hooks.toast("Pick someone to add.", true);
          const g2 = await api(`${base}/members`, { method: "POST", body: JSON.stringify({ usernames }) });
          current.group = g2;
          const names = g2.members.filter((m) => usernames.includes(m.username)).map((m) => m.display_name);
          await sendPayload({ kind: "notice", text: `${me.display_name} added ${names.join(", ")}.` });
        }
        if (b.dataset.g === "remove") {
          if (!confirm(`Remove @${b.dataset.u} from ${g.name}?`)) return;
          const who = g.members.find((m) => m.username === b.dataset.u);
          await api(`${base}/members/${encodeURIComponent(b.dataset.u)}`, { method: "DELETE" });
          current.group = (await messenger.loadGroups(true)).get(g.id);
          await sendPayload({ kind: "notice", text: `${me.display_name} removed ${who?.display_name || b.dataset.u}.` });
        }
        if (b.dataset.g === "leave") {
          if (!confirm(`Leave ${g.name}? You'll keep the messages you already have.`)) return;
          await sendPayload({ kind: "notice", text: `${me.display_name} left the group.` });
          await api(`${base}/members/${encodeURIComponent(me.username)}`, { method: "DELETE" });
        }
        if (b.dataset.g === "delete") {
          if (!confirm(`Delete ${g.name} for everyone? Members keep the messages already on their devices.`)) return;
          await api(base, { method: "DELETE" });
        }
        d.close();
        await messenger.loadGroups(true);
        await open({ username: current.username });
      } catch (err) { hooks.toast(err.message, true); }
    });
  }

  function bubble(m, prev) {
    const time = new Date(m.sent).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (m.kind === "notice") return `<div class="notice">${esc(m.text)}</div>`;
    let inner = "";
    if (m.kind === "text") inner = `<p>${esc(m.text)}</p>`;
    if (m.kind === "location") inner = `<p><b>Location</b><br>${(+m.lat).toFixed(6)}, ${(+m.lon).toFixed(6)}${m.acc ? ` (±${m.acc} m)` : ""}</p>${links(m.lat, m.lon)}`;
    if (m.kind === "pin") inner = `<p><b>${esc(m.pin.label)}</b>, ${esc(m.pin.severity)} severity<br><span class="small">${esc(m.pin.note || "")}</span></p>${links(m.pin.lat, m.pin.lon)}`;
    if (m.kind === "finding") inner = `<p><b>${esc(m.finding.label)}</b>${m.finding.severity ? `, ${esc(m.finding.severity)} severity` : ""}<br><span class="small">${esc(m.finding.evidence || "")}</span></p>${links(m.finding.lat, m.finding.lon)}`;
    const showName = current?.group !== undefined && current.username.startsWith("g:") && !m.out && (!prev || prev.from !== m.from || prev.kind === "notice");
    const from = showName ? `<span class="from" style="--h:${hue(m.from)}">${esc(m.from_name || m.from)}</span>` : "";
    return `<div class="bubble ${m.out ? "out" : "in"}">${from}${inner}<span class="time">${time}</span></div>`;
  }
  const links = (lat, lon) => `<div class="bubble-links"><a href="${mapsUrl(lat, lon)}" target="_blank" rel="noopener noreferrer">Open in Google Maps</a>
    <button class="linkish" data-act="map" data-lat="${+lat}" data-lon="${+lon}" type="button">Show on the map</button></div>`;

  async function renderThread() {
    if (!current) return;
    const box = thread.querySelector("#bubbles");
    const msgs = await messenger.history(current.username);
    box.innerHTML = msgs.length ? msgs.map((m, i) => bubble(m, msgs[i - 1])).join("")
      : `<div class="notice">${current.username.startsWith("g:") ? "End-to-end encrypted group. Say hello to the crew." : "Messages are end-to-end encrypted. Say hello."}</div>`;
    box.scrollTop = box.scrollHeight;
  }

  renderConvs();
  return {
    async refresh(peer) {
      await renderConvs();
      if (current && peer === current.username) { await messenger.markRead(peer); await renderThread(); }
    },
    open,
    isOpen: (peer) => current?.username === peer,
    async sendTo(peer, payload) { await open(peer); await sendPayload(payload); },
  };
}

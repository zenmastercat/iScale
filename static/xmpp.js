/* A small XMPP client over WebSocket (RFC 7395): SASL PLAIN sign-in with the token iScale
   issues, resource binding, presence, messages, IQ requests with promises, and reconnects.
   Enough for iScale's chat; any standard XMPP server (here ejabberd) works with it. */

export const NS = {
  framing: "urn:ietf:params:xml:ns:xmpp-framing", sasl: "urn:ietf:params:xml:ns:xmpp-sasl",
  bind: "urn:ietf:params:xml:ns:xmpp-bind", client: "jabber:client", pubsub: "http://jabber.org/protocol/pubsub",
  muc: "http://jabber.org/protocol/muc", mucUser: "http://jabber.org/protocol/muc#user", ping: "urn:xmpp:ping",
  delay: "urn:xmpp:delay", sid: "urn:xmpp:sid:0", hints: "urn:xmpp:hints", eme: "urn:xmpp:eme:0",
  dataforms: "jabber:x:data",
};

export const xesc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[c]);
export const bare = (jid) => String(jid || "").split("/")[0];
export const child = (el, name, ns) => el && [...el.children].find((c) => c.localName === name && (!ns || c.namespaceURI === ns));
export const children = (el, name, ns) => (el ? [...el.children].filter((c) => c.localName === name && (!ns || c.namespaceURI === ns)) : []);
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));

export class XmppClient {
  /* getCredentials() -> {jid, token, websocket, domain}; handlers: onMessage(el), onPresence(el), onStatus(text), onOnline() */
  constructor(getCredentials, handlers = {}) {
    this.getCredentials = getCredentials;
    this.h = handlers;
    this.pending = new Map();
    this.closed = false;
    this.backoff = 1000;
  }

  async connect() {
    this.closed = false;
    const c = await this.getCredentials();
    this.jid = null;
    this.bareJid = c.jid;
    this.domain = c.domain;
    const url = new URL(c.websocket, location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url.href, "xmpp");
      this.ws = ws;
      let stage = "open";
      let settled = false;
      const fail = (e) => { if (!settled) { settled = true; reject(e); } };
      ws.onopen = () => this.raw(`<open xmlns="${NS.framing}" to="${xesc(c.domain)}" version="1.0"/>`);
      ws.onmessage = (ev) => {
        const el = new DOMParser().parseFromString(ev.data, "text/xml").documentElement;
        if (!el || el.localName === "parsererror") return;
        if (el.localName === "open") return;
        if (el.localName === "close") { ws.close(); return; }
        if (stage === "open" && el.localName === "features") {
          const mechs = children(child(el, "mechanisms", NS.sasl), "mechanism").map((m) => m.textContent);
          if (!mechs.includes("PLAIN")) return fail(new Error("server offers no PLAIN sign-in"));
          const local = c.jid.split("@")[0];
          const plain = btoa(unescape(encodeURIComponent(`\0${local}\0${c.token}`)));
          this.raw(`<auth xmlns="${NS.sasl}" mechanism="PLAIN">${plain}</auth>`);
          stage = "auth";
        } else if (stage === "auth") {
          if (el.localName !== "success") return fail(new Error("chat sign-in refused"));
          stage = "bind";
          this.raw(`<open xmlns="${NS.framing}" to="${xesc(c.domain)}" version="1.0"/>`);
        } else if (stage === "bind" && el.localName === "features") {
          this.iq("set", null, `<bind xmlns="${NS.bind}"><resource>web-${uid().slice(0, 8)}</resource></bind>`).then((r) => {
            this.jid = child(child(r, "bind", NS.bind), "jid")?.textContent;
            stage = "online";
            this.backoff = 1000;
            settled = true;
            resolve(this.jid);
            this.h.onOnline?.();
          }, fail);
        } else if (el.localName === "iq") {
          this.onIq(el);
        } else if (el.localName === "message") {
          this.h.onMessage?.(el);
        } else if (el.localName === "presence") {
          this.h.onPresence?.(el);
        }
      };
      ws.onerror = () => fail(new Error("can't reach the chat server"));
      ws.onclose = () => {
        fail(new Error("chat connection closed"));
        for (const [, p] of this.pending) p.reject(new Error("chat connection closed"));
        this.pending.clear();
        clearInterval(this.pinger);
        this.h.onStatus?.("offline");
        if (!this.closed) {
          setTimeout(() => this.connect().catch(() => {}), this.backoff);
          this.backoff = Math.min(this.backoff * 2, 30000);
        }
      };
    }).then((jid) => {
      clearInterval(this.pinger);
      this.pinger = setInterval(() => this.iq("get", this.domain, `<ping xmlns="${NS.ping}"/>`, 20000).catch(() => {}), 60000);
      return jid;
    });
  }

  close() { this.closed = true; clearInterval(this.pinger); try { this.raw(`<close xmlns="${NS.framing}"/>`); this.ws?.close(); } catch { /* already closed */ } }
  raw(xml) { if (this.ws?.readyState === 1) this.ws.send(xml); else throw new Error("chat is offline"); }
  get online() { return !!this.jid && this.ws?.readyState === 1; }

  iq(type, to, inner, timeout = 15000) {
    const id = uid();
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => { this.pending.delete(id); reject(new Error("chat server timed out")); }, timeout);
      this.pending.set(id, { resolve: (el) => { clearTimeout(t); resolve(el); }, reject: (e) => { clearTimeout(t); reject(e); } });
      try {
        this.raw(`<iq xmlns="${NS.client}" type="${type}" id="${id}"${to ? ` to="${xesc(to)}"` : ""}>${inner}</iq>`);
      } catch (e) { clearTimeout(t); this.pending.delete(id); reject(e); }
    });
  }

  onIq(el) {
    const id = el.getAttribute("id");
    const type = el.getAttribute("type");
    if ((type === "result" || type === "error") && this.pending.has(id)) {
      const p = this.pending.get(id);
      this.pending.delete(id);
      if (type === "result") p.resolve(el);
      else {
        const cond = child(el, "error")?.firstElementChild?.localName || "error";
        const e = new Error(cond);
        e.condition = cond;
        p.reject(e);
      }
      return;
    }
    if (type === "get" || type === "set") {
      const from = el.getAttribute("from");
      if (child(el, "ping", NS.ping)) return this.raw(`<iq xmlns="${NS.client}" type="result" id="${xesc(id)}"${from ? ` to="${xesc(from)}"` : ""}/>`);
      this.raw(`<iq xmlns="${NS.client}" type="error" id="${xesc(id)}"${from ? ` to="${xesc(from)}"` : ""}><error type="cancel"><service-unavailable xmlns="urn:ietf:params:xml:ns:xmpp-stanzas"/></error></iq>`);
    }
  }

  /* PEP / pubsub helpers (XEP-0060, XEP-0163) */
  async items(jid, node) {
    const r = await this.iq("get", jid, `<pubsub xmlns="${NS.pubsub}"><items node="${xesc(node)}" max_items="1"/></pubsub>`);
    return children(child(child(r, "pubsub", NS.pubsub), "items"), "item");
  }

  publish(node, itemXml, itemId = "current", access = "open") {
    return this.iq("set", null, `<pubsub xmlns="${NS.pubsub}"><publish node="${xesc(node)}"><item id="${xesc(itemId)}">${itemXml}</item></publish>
      <publish-options><x xmlns="${NS.dataforms}" type="submit"><field var="FORM_TYPE" type="hidden"><value>http://jabber.org/protocol/pubsub#publish-options</value></field>
      <field var="pubsub#access_model"><value>${access}</value></field></x></publish-options></pubsub>`);
  }
}

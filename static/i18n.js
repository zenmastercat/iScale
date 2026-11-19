// Thai / English switch for the whole UI.
//
// The app writes English. When Thai is on, this module translates every text node and the
// placeholder / title / aria-label attributes from /static/i18n/th.json, including text the
// app adds later (a MutationObserver watches the page). Switching back restores the English
// originals. Keys are the English text with whitespace collapsed; a key with {0}, {1}... is a
// pattern whose placeholders match any text, e.g. "{0} potholes" -> "หลุม {0} จุด".
// User content (chat bubbles, names, Civil Helper answers, the agreement document) is skipped.

const STORE = "iscale-lang";
const ATTRS = ["placeholder", "title", "aria-label"];
const SKIP = [
  ".bubble", ".chat-log .msg.bot", ".chat-log .msg.user", ".conv-name", ".conv-prev", ".thread-title b",
  "#projectSelect", "#surveySelect", ".me-name", "code", "pre", "textarea", "script", "style",
  ".dialog.agreement", ".ag-doc", ".maplibregl-ctrl-attrib", "[data-no-i18n]", ".lang-switch",
].join(",");

let lang = "en";
try { lang = localStorage.getItem(STORE) || ((navigator.language || "").toLowerCase().startsWith("th") ? "th" : "en"); } catch { /* private mode */ }

const exact = new Map();
let patterns = [];
let loaded = null;
const origText = new WeakMap();  // text node -> English original
const setText = new WeakMap();   // text node -> value this module wrote
const origAttr = new WeakMap();  // element -> {attr: English original}
const setAttr = new WeakMap();   // element -> {attr: value this module wrote}

const norm = (s) => s.replace(/\s+/g, " ").trim();
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function load() {
  loaded ??= fetch("/static/i18n/th.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : {}).catch(() => ({})).then((d) => {
    for (const [k, v] of Object.entries(d)) {
      if (k.startsWith("_")) continue;
      const key = norm(k);
      if (/\{\d+\}/.test(key)) {
        const parts = key.split(/\{(\d+)\}/);
        let re = "^", anchor = "";
        parts.forEach((p, i) => { if (i % 2) re += "(.+?)"; else { re += esc(p); if (p.trim().length > anchor.length) anchor = p.trim(); } });
        patterns.push({ re: new RegExp(re + "$", "s"), anchor, th: v, n: key.length });
      } else exact.set(key, v);
    }
    patterns.sort((a, b) => b.n - a.n);  // most specific first
  });
  return loaded;
}

export function t(s) {
  const k = norm(s);
  if (!k || lang !== "th") return null;
  const hit = exact.get(k);
  if (hit !== undefined) return hit;
  if (!/[A-Za-z]/.test(k)) return null;
  for (const p of patterns) {
    if (p.anchor && !k.includes(p.anchor)) continue;
    const m = p.re.exec(k);
    if (m) return p.th.replace(/\{(\d+)\}/g, (_, i) => { const v = m[+i + 1] ?? ""; return exact.get(norm(v)) ?? v; });
  }
  return null;
}

const skipped = (el) => !el || (el.closest && el.closest(SKIP));

function doText(node) {
  if (skipped(node.parentElement)) return;
  const cur = node.nodeValue;
  if (setText.get(node) !== cur) origText.set(node, cur);  // the app wrote new text
  const en = origText.get(node);
  if (en === undefined) return;
  let next = en;
  if (lang === "th") {
    const tr = t(en);
    if (tr != null) { const lead = en.match(/^\s*/)[0], trail = en.match(/\s*$/)[0]; next = lead + tr + trail; }
  }
  if (next !== cur) { setText.set(node, next); node.nodeValue = next; } else setText.set(node, cur);
}

function doAttrs(el) {
  if (skipped(el)) return;
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const cur = el.getAttribute(a);
    const o = origAttr.get(el) || {}, s = setAttr.get(el) || {};
    if (s[a] !== cur) o[a] = cur;
    origAttr.set(el, o);
    const en = o[a];
    const next = lang === "th" ? (t(en) ?? en) : en;
    s[a] = next; setAttr.set(el, s);
    if (next !== cur) el.setAttribute(a, next);
  }
}

function walk(root) {
  if (root.nodeType === 3) return doText(root);
  if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
  if (root.nodeType === 1) { if (skipped(root)) return; doAttrs(root); }
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => n.nodeType === 1 && n.matches(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? doText(n) : doAttrs(n);
}

function applyAll() {
  document.documentElement.lang = lang;
  walk(document.body);
  const titleNode = document.querySelector("title");
  if (titleNode) walk(titleNode);
  document.querySelectorAll(".lang-switch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}

export function getLang() { return lang; }

export async function setLang(next) {
  lang = next === "th" ? "th" : "en";
  try { localStorage.setItem(STORE, lang); localStorage.setItem("iscale-agreement-lang", lang); } catch { /* private mode */ }
  if (lang === "th") await load();
  applyAll();
  window.dispatchEvent(new CustomEvent("iscale:lang", { detail: lang }));
}

/** A small EN | ไทย switch; put one wherever it is needed (sidebar, sign-in). */
export function langSwitch() {
  const g = document.createElement("div");
  g.className = "lang-switch";
  g.setAttribute("role", "group");
  g.setAttribute("aria-label", "Language / ภาษา");
  g.innerHTML = '<button type="button" data-lang="en">EN</button><button type="button" data-lang="th" lang="th">ไทย</button>';
  g.querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
    b.addEventListener("click", () => setLang(b.dataset.lang));
  });
  return g;
}

new MutationObserver((muts) => {
  if (lang !== "th") return;  // English is the source text; switching walks the page anyway
  for (const m of muts) {
    if (m.type === "characterData") doText(m.target);
    else if (m.type === "attributes") doAttrs(m.target);
    else m.addedNodes.forEach(walk);
  }
}).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });

for (const slot of document.querySelectorAll("[data-lang-switch]")) slot.replaceChildren(langSwitch());
if (lang === "th") load().then(applyAll); else applyAll();

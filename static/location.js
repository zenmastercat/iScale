/* Opt-in device location: the agreement (accept / decline), the Settings switch, live GPS while
   iScale is open, a precise fix for pins, and the GPS track of a recorded drive.

   Nothing runs unless the person accepted the current agreement version on the server.
   The live position stays on this device; it is sent only as a pin position ("Pin where I am"),
   a recorded drive's track, or a one-off location in chat. Tracking stops when the tab is hidden. */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HDR = { "X-Civil-Scan": "1", "Content-Type": "application/json" };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: HDR });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

/* The agreement is plain Markdown: headings, lists, bold, paragraphs. */
function mdLite(src) {
  const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of src.split("\n")) {
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)/))) { close(); out.push(`<h${m[1].length + 1}>${inline(m[2])}</h${m[1].length + 1}>`); }
    else if ((m = line.match(/^\s*[-*]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+\.\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (line.trim()) { close(); out.push(`<p>${inline(line)}</p>`); }
    else close();
  }
  close();
  return out.join("");
}

const listeners = new Set();
let state = null;          // server state: {version, text, enabled, decision, ask, ...}
let watchId = null;
let last = null;           // {lat, lon, acc, t (epoch ms), heading, speed}
let blocked = false;       // the browser refused permission
let tracks = new Set();    // active drive recordings

const supported = () => "geolocation" in navigator && window.isSecureContext;

function emit() { for (const fn of listeners) fn(fix()); }

/** The latest position, marked stale when older than 30 s, or null. */
export function fix() {
  if (!last || !state?.enabled) return null;
  return { ...last, stale: Date.now() - last.t > 30000 };
}
export const isOn = () => !!state?.enabled;
export const isBlocked = () => blocked;
export const onChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const serverState = () => state;

function start() {
  if (watchId !== null || !state?.enabled || document.hidden || !supported()) return;
  watchId = navigator.geolocation.watchPosition((p) => {
    blocked = false;
    last = { lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy, t: p.timestamp || Date.now(),
      heading: p.coords.heading, speed: p.coords.speed };
    for (const tr of tracks) tr.add(last);
    emit();
  }, (err) => {
    if (err.code === 1) { blocked = true; stop(); emit(); }
  }, { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
}

function stop() {
  if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
}

document.addEventListener("visibilitychange", () => {
  // only while iScale is on screen; a recording keeps its own screen awake, so it stays visible
  if (document.hidden) stop(); else start();
});

export async function refresh() {
  state = await api("/api/location");
  if (state.enabled) start(); else { stop(); last = null; }
  emit();
  return state;
}

async function decide(decision) {
  state = await api("/api/location/consent", { method: "POST", body: JSON.stringify({ decision, version: state.version }) });
  if (state.enabled) start(); else { stop(); last = null; }
  emit();
  return state;
}

const UI = {
  en: { title: "Use your location?", sub: "Optional. Read what iScale does with it, then choose.", doc: "Location agreement",
    foot: (v) => `Agreement version ${v}. You can change your answer any time in Settings, Location.`, no: "Decline", yes: "Accept", close: "Close" },
  th: { title: "ใช้ตำแหน่งของคุณหรือไม่", sub: "เป็นทางเลือก อ่านว่า iScale ใช้ตำแหน่งอย่างไร แล้วเลือก", doc: "ข้อตกลงการใช้ตำแหน่ง",
    foot: (v) => `ข้อตกลงฉบับ ${v} คุณเปลี่ยนคำตอบได้ทุกเมื่อที่ ตั้งค่า ตำแหน่ง`, no: "ไม่ยินยอม", yes: "ยินยอม", close: "ปิด" },
};
// Thai for Thai browsers, English otherwise; the person's last choice wins
let lang = (navigator.language || "").toLowerCase().startsWith("th") ? "th" : "en";
try { lang = localStorage.getItem("iscale-agreement-lang") || lang; } catch { /* private mode */ }

/* The agreement body with a ไทย / English switch; returns [html, wire(dialog)]. */
function agreementBody(withActions, footExtra = "") {
  const html = `
    <div class="ag-head">
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="9.5" r="2.4" fill="currentColor"/></svg>
      <div class="ag-titles"><h2 id="agTitle"></h2><p class="muted small" id="agSub"></p></div>
      <div class="ag-lang" role="group" aria-label="Language">
        <button type="button" data-lang="th" lang="th">ไทย</button><button type="button" data-lang="en">English</button></div>
    </div>
    <div class="ag-doc" tabindex="0"></div>
    <p class="muted small" id="agFoot"></p>
    <div class="dialog-actions ag-actions">${withActions
      ? `<button class="btn ag-choice" value="declined"></button><button class="btn ag-choice" value="accepted"></button>`
      : `<button class="btn ag-choice" value="ok"></button>`}</div>`;
  const wire = (d, reason) => {
    const paint = () => {
      const u = UI[lang];
      d.querySelector("form").lang = lang;
      d.querySelector("#agTitle").textContent = withActions ? u.title : u.doc;
      d.querySelector("#agSub").textContent = withActions ? `${reason ? reason + " " : ""}${u.sub}` : "";
      const doc = d.querySelector(".ag-doc");
      doc.innerHTML = mdLite(lang === "th" ? state.text_th : state.text);
      doc.setAttribute("aria-label", u.doc);
      doc.scrollTop = 0;
      d.querySelector("#agFoot").textContent = u.foot(state.version) + footExtra;
      const b = d.querySelectorAll(".ag-choice");
      if (withActions) { b[0].textContent = u.no; b[1].textContent = u.yes; } else b[0].textContent = u.close;
      d.querySelectorAll("[data-lang]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.lang === lang)));
    };
    d.querySelectorAll("[data-lang]").forEach((x) => x.addEventListener("click", () => {
      lang = x.dataset.lang;
      try { localStorage.setItem("iscale-agreement-lang", lang); } catch { /* private mode */ }
      paint();
    }));
    paint();
  };
  return [html, wire];
}

/** Show the agreement. Resolves true if the person accepts (and location is now on). */
export function showAgreement({ reason = "" } = {}) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "dialog agreement";
    d.setAttribute("aria-labelledby", "agTitle");
    const [html, wire] = agreementBody(true);
    d.innerHTML = `<form method="dialog">${html}</form>`;
    document.body.appendChild(d);
    wire(d, reason);
    d.addEventListener("cancel", (e) => e.preventDefault()); // Escape must not count as an answer
    d.addEventListener("close", async () => {
      const v = d.returnValue;
      d.remove();
      try {
        if (v === "accepted") {
          await decide("accepted");
          askBrowser();
          return resolve(true);
        }
        // a decline at entry is remembered so it isn't asked again; from a button it only cancels
        if (v === "declined" && (state.decision === null || state.ask)) await decide("declined");
      } catch (err) { console.warn(err); }
      resolve(false);
    });
    d.showModal();
  });
}

/* Trigger the browser's own permission prompt right after Accept. */
function askBrowser() {
  if (!supported()) return;
  navigator.geolocation.getCurrentPosition(() => { blocked = false; start(); }, (err) => { if (err.code === 1) { blocked = true; emit(); } },
    { enableHighAccuracy: true, timeout: 20000 });
}

/** On entry: ask if there is no answer yet, or the agreement changed since it was accepted. */
export async function onEntry() {
  try { await refresh(); } catch { return; }
  if (state.ask) await showAgreement();
}

/** Make sure location is on before a feature that needs it. Resolves true when it is. */
export async function ensure(reason) {
  if (!state) await refresh();
  if (!supported()) throw new Error("Location needs HTTPS (or this computer's own address). Ask your admin to set up HTTPS in Settings, Network.");
  if (state.enabled) {
    if (blocked) {
      blocked = false;
      askBrowser(); // the person may have allowed it since; this re-checks for the next try
      throw new Error("Your browser blocks location for iScale. Allow it in the browser's site settings, then try again.");
    }
    start();
    return true;
  }
  return showAgreement({ reason });
}

export async function turnOn() { return ensure(""); }
export async function turnOff() { return decide("withdrawn"); }  // the server also deletes the person's drive tracks

/** A position good enough for a pin. Calls onProgress(fix) while waiting; resolves with the
    first fix at or under `target` m, or the best one when `signal` says "use it now". */
export function preciseFix({ target = 10, maxAgeMs = 5000, onProgress, until } = {}) {
  return new Promise((resolve, reject) => {
    let best = null;
    const consider = (f) => {
      if (!f || f.stale || Date.now() - f.t > maxAgeMs) return;
      if (!best || f.acc <= best.acc) best = f;
      onProgress?.(best);
      if (best.acc <= target) done(best);
    };
    const off = onChange(consider);
    const done = (f) => { off(); resolve(f); };
    consider(fix());
    until?.then((why) => {
      off();
      if (why === "use" && best) resolve(best); else reject(new Error(why === "use" ? "No position yet" : "cancelled"));
    });
    if (blocked) { off(); reject(new Error("Your browser blocks location for iScale. Allow it in the browser's site settings.")); }
    start();
  });
}

/** Log the GPS track of a drive. t is seconds from `t0` (epoch ms, the video's first frame). */
export function recordTrack() {
  const rows = [];
  let t0 = null;
  const tr = { add(f) { if (t0 !== null && f.t >= t0 - 2000) rows.push([+((f.t - t0) / 1000).toFixed(3), f.lat, f.lon, Math.round(f.acc * 10) / 10]); } };
  tracks.add(tr);
  return {
    begin(epochMs) { t0 = epochMs; rows.length = 0; const f = fix(); if (f && !f.stale) tr.add({ ...f, t: Math.max(f.t, t0) }); },
    rows: () => rows.filter((r) => r[0] >= -1),
    stop() { tracks.delete(tr); return rows.filter((r) => r[0] >= -1); },
  };
}

/** Settings panel: the switch, the agreement, the person's answers, and their recorded tracks. */
export async function renderSettingsPanel(el, toast) {
  const s = await refresh();
  const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "");
  el.innerHTML = `
    <div class="panel-head"><h2>Location</h2><span class="muted small">${s.enabled ? "On while iScale is open" : "Off"}</span></div>
    <div class="set-body">
      <div class="switch-row">
        <div><b>Use my location</b>
          <p class="muted small">Shows where you are on the map, pins potholes where you stand, and saves a GPS track with drives you record, so surveys get real position and size. Only you see your live position.</p></div>
        <button class="switch" type="button" role="switch" id="locSwitch" aria-checked="${s.enabled}" aria-label="Use my location"><span></span></button>
      </div>
      ${!supported() ? `<p class="warn small">This connection isn't HTTPS, so the browser won't share location. Ask your admin to set up HTTPS in Settings, Network.</p>` : ""}
      ${s.enabled && blocked ? `<p class="warn small">Your browser blocks location for iScale. Allow it in the browser's site settings.</p>` : ""}
      <p class="muted small">${!s.decision ? "You haven't answered the location agreement yet."
        : s.decision === "withdrawn" ? `You turned location off on ${esc(when(s.decided_at))}.`
        : `You ${s.decision} the location agreement (version ${esc(s.decided_version)}) on ${esc(when(s.decided_at))}.`}</p>
      <div class="row-actions">
        <button class="btn small" type="button" id="locRead">Read the agreement</button>
        <button class="btn small quiet" type="button" id="locForget" ${s.my_tracks ? "" : "disabled"}>Delete my GPS tracks${s.my_tracks ? ` (${s.my_tracks})` : ""}</button>
      </div>
      ${s.contact_editable ? `<form class="grid-form" id="locContact">
        <h3>Who people contact about their data</h3>
        <label class="field"><span>Contact (email or phone)</span><input class="input" name="contact" maxlength="200" value="${esc(s.privacy_contact)}" placeholder="privacy@yourcompany.co.th, 02 123 4567"></label>
        <label class="field"><span>Postal address</span><textarea class="input" name="address" maxlength="400" rows="2" placeholder="Company name, street, district, province, postcode">${esc(s.privacy_address)}</textarea></label>
        <div class="form-actions"><button class="btn small primary" type="submit">Save</button>
          <span class="muted small">Shown in the agreement. Thailand's PDPA requires a postal address for data requests.</span></div></form>` : ""}
    </div>`;
  const re = () => renderSettingsPanel(el, toast);
  el.querySelector("#locSwitch").addEventListener("click", async () => {
    try {
      if (state.enabled) {
        const r = await turnOff();
        toast(`Location is off. iScale stopped using it${r.tracks_deleted ? ` and deleted ${r.tracks_deleted} GPS ${r.tracks_deleted === 1 ? "track" : "tracks"}` : ""}.`);
      }
      else if (await turnOn()) toast("Location is on while iScale is open.");
    } catch (err) { toast(err.message, true); }
    re();
  });
  el.querySelector("#locRead").addEventListener("click", async () => {
    if (state.enabled) {
      const d = document.createElement("dialog");
      d.className = "dialog agreement";
      d.setAttribute("aria-labelledby", "agTitle");
      const [html, wire] = agreementBody(false, ` (${when(state.decided_at)})`);
      d.innerHTML = `<form method="dialog">${html}</form>`;
      document.body.appendChild(d);
      wire(d, "");
      d.addEventListener("close", () => d.remove());
      d.showModal();
    } else if (await showAgreement()) { toast("Location is on while iScale is open."); re(); }
  });
  el.querySelector("#locForget").addEventListener("click", async () => {
    if (!confirm("Delete the GPS tracks of drives you recorded? Surveys already processed keep their results; reprocessing them would lose the real position and scale.")) return;
    try { const r = await api("/api/location/forget-tracks", { method: "POST", body: "{}" }); toast(`Deleted ${r.deleted} GPS ${r.deleted === 1 ? "track" : "tracks"}`); }
    catch (err) { toast(err.message, true); }
    re();
  });
  el.querySelector("#locContact")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await api("/api/location/contact", { method: "PUT", body: JSON.stringify({ contact: f.get("contact"), address: f.get("address") }) }); toast("Saved"); }
    catch (err) { toast(err.message, true); }
    re();
  });
}

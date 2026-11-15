/* Pothole job card: Location, Cost & materials, Best time, Repair plan.
   Full-screen sheet on phones and tablets, a centred two-column window on a computer. */
import { mountCheck } from "./check3d.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HDR = { "X-Civil-Scan": "1" };
const SECTIONS = [["loc", "Location"], ["cost", "Cost"], ["time", "Time"], ["plan", "Plan"]];

const ICON = {
  pin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  nav: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 21 3l-8 18-2-8-8-2z"/></svg>',
  clock: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  tool: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z"/></svg>',
  alert: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17v.01"/></svg>',
  list: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg>',
};

export function moneyFmt(x, sym = "฿", digits = 0) {
  return `${sym}${Number(x || 0).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function ago(t) {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d < 60 ? `${d} day${d === 1 ? "" : "s"} ago` : new Date(t * 1000).toLocaleDateString();
}

const fmtTile = (t) => {
  if (t.key === "depth_max_m") return [`${(t.value * 100).toFixed(t.value < 0.1 ? 1 : 0)}`, "cm"];
  if (t.key === "volume_m3") return [`${Math.round(t.value * 1000)}`, "L"];
  return [Number(t.value).toFixed(t.value < 10 ? 2 : 1), t.unit];
};

// One OpenStreetMap tile with the spot marked, when there is no photo from the drive.
function tileFor(lat, lon, z = 18) {
  const n = 2 ** z, x = ((lon + 180) / 360) * n;
  const r = (lat * Math.PI) / 180, y = ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n;
  return { url: `https://tile.openstreetmap.org/${z}/${Math.floor(x)}/${Math.floor(y)}.png`, fx: x % 1, fy: y % 1 };
}

function photoHtml(c) {
  const L = c.location;
  const badge = `<span class="jc-sev ${esc(c.severity)}">${esc(c.severity[0].toUpperCase() + c.severity.slice(1))} severity</span>`;
  if (L.photo) {
    const boxes = (L.photo.boxes || []).map((raw) => {
      const b = raw.map(Number);
      return b.length === 4 && b.every(Number.isFinite) ? `<rect x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}"/>` : "";
    }).join("");
    return `<figure class="jc-hero">
      <img src="${esc(L.photo.url)}" alt="Road photo near the pothole" decoding="async" data-boxes='${esc(JSON.stringify(L.photo.boxes || []))}'>
      <svg class="jc-boxes" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${boxes}</svg>
      ${badge}<figcaption>${esc(L.photo.note)}</figcaption></figure>`;
  }
  const t = tileFor(L.lat, L.lon);
  return `<figure class="jc-hero map" style="--fx:${t.fx};--fy:${t.fy}">
    <img src="${esc(t.url)}" alt="Map of the spot" decoding="async" referrerpolicy="no-referrer">
    <span class="jc-dot" aria-hidden="true"></span>${badge}<figcaption>No photo. Map © OpenStreetMap contributors</figcaption></figure>`;
}

function locationHtml(c) {
  const L = c.location, a = L.address;
  const title = a?.line1 || L.road_name || "Address not found";
  const sub = a?.line2 || "";
  return `<section class="jc-card" id="jc-loc" aria-labelledby="jc-loc-h">
    <h3 class="sr-only" id="jc-loc-h">Location</h3>
    ${photoHtml(c)}
    <div class="jc-pad">
      <div class="jc-meta"><span class="jc-job">JOB ${esc(c.id)}</span><span>${L.reported ? `Reported ${esc(ago(L.reported))}` : ""}${L.reporter ? ` by ${esc(L.reporter)}` : ""}</span></div>
      <p class="jc-addr">${esc(title)}</p>
      ${sub ? `<p class="jc-addr2">${esc(sub)}</p>` : ""}
      <button class="jc-coords" type="button" data-copy="${L.lat.toFixed(6)}, ${L.lon.toFixed(6)}" title="Copy coordinates">${ICON.pin}<span>${L.lat.toFixed(6)}, ${L.lon.toFixed(6)}</span></button>
      <a class="btn primary jc-nav" href="${esc(L.nav_url)}" target="_blank" rel="noopener noreferrer">${ICON.nav}Navigate to the repair site</a>
      ${L.tiles.length ? `<p class="jc-label">Measured damage</p><div class="jc-tiles">${L.tiles.map((t) => { const [v, u] = fmtTile(t); return `<div class="jc-tile"><span>${esc(t.label)}</span><b>${esc(v)}<small> ${esc(u)}</small></b></div>`; }).join("")}</div>`
        : `<p class="jc-label">No size measured yet</p>`}
      ${L.evidence ? `<p class="muted small">${esc(L.evidence)}</p>` : ""}
    </div></section>`;
}

function costHtml(c, canEdit) {
  const b = c.cost;
  if (!b.available) {
    return `<section class="jc-card" id="jc-cost"><div class="jc-pad"><h3 class="jc-h">${ICON.list}Bill of materials</h3>
      <p class="muted">${esc(b.reason)}</p>
      ${c.kind === "pin" ? sizeForm() : ""}</div></section>`;
  }
  const sym = b.symbol;
  const lines = b.lines.map((l) => `<li class="jc-line">
      <span class="jc-code">${esc(l.code)}</span>
      <div class="jc-what"><b>${esc(l.label)}</b>${l.label_th ? `<span class="th">${esc(l.label_th)}</span>` : ""}<small>${esc(l.detail)}</small></div>
      <div class="jc-qty"><b>${esc(l.qty)}</b><small>${esc(l.unit)}</small>
        <span>${l.amount != null ? `× ${moneyFmt(l.unit_price, sym, Number.isInteger(l.unit_price) ? 0 : 2)} = ${moneyFmt(l.amount, sym, Number.isInteger(l.amount) ? 0 : 2)}` : `<em>price not set</em>`}</span></div></li>`).join("");
  return `<section class="jc-card" id="jc-cost" aria-labelledby="jc-cost-h"><div class="jc-pad">
    <h3 class="jc-h" id="jc-cost-h">${ICON.list}Bill of materials <span class="muted">materials only</span></h3>
    <div class="jc-bom">
      <p class="jc-method"><span class="jc-pill">${b.method === "full_depth" ? "Base + cold mix" : "Cold mix"}</span>${esc(b.method_label)}</p>
      <ul class="jc-lines">${lines}</ul>
      <div class="jc-sum"><span>Materials subtotal</span><span>${moneyFmt(b.subtotal, sym, 2)}</span></div>
      <div class="jc-total"><span>Materials cost</span><b>${moneyFmt(b.subtotal, sym, 2)}</b></div>
      ${b.missing_prices.length ? `<p class="jc-warn small">${esc(b.missing_prices.join(", "))}: no price set, so not in the total.${canEdit ? " Set it in Settings, Material prices." : " Ask your admin to set it."}</p>` : ""}
      <p class="jc-label">Tools (not costed)</p>
      <div class="jc-chips">${b.tools.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
      <p class="jc-note">${esc(b.excludes)} The cut, ${esc(b.cut_w_m)} × ${esc(b.cut_l_m)} m, goes ${esc(Math.round(b.cut_edge_m * 100))} cm past the damage on every side (DOH method), so it is larger than the measured ${esc(b.area_m2)} m².</p>
    </div>
    ${c.kind === "pin" ? `<details class="jc-more"><summary>Change the size</summary>${sizeForm()}</details>` : ""}
  </div></section>`;
}

function sizeForm() {
  return `<form class="jc-size" data-size>
    <label class="field"><span>Width (cm)</span><input class="input num" name="width_cm" type="number" inputmode="decimal" min="1" max="5000" required></label>
    <label class="field"><span>Length (cm)</span><input class="input num" name="length_cm" type="number" inputmode="decimal" min="1" max="5000" required></label>
    <label class="field"><span>Depth (cm)</span><input class="input num" name="depth_cm" type="number" inputmode="decimal" min="0.5" max="200" step="0.5" required></label>
    <button class="btn primary small" type="submit">Estimate materials</button></form>`;
}

const LEVEL = { low: "Low traffic", medium: "Moderate traffic", high: "Heavy traffic", unknown: "Traffic not known" };

function timeHtml(c) {
  const t = c.timing;
  const [a, b] = t.window.split("-");
  return `<section class="jc-card" id="jc-time" aria-labelledby="jc-time-h"><div class="jc-pad">
    <h3 class="jc-h" id="jc-time-h">${ICON.clock}Best time to repair</h3>
    <div class="jc-window">
      <p class="jc-label center">Suggested window</p>
      <p class="jc-big">${esc(a)}<span>–</span>${esc(b)}</p>
      <p class="center"><span class="jc-level ${esc(t.level)}">${esc(LEVEL[t.level] || t.level)}</span>${t.now ? ` <span class="jc-level now ${esc(t.now.level)}">Now: ${esc(t.now.level)} (×${esc(t.now.ratio)})</span>` : ""}</p>
      <dl>
        <dt>Days</dt><dd>${esc(t.days)}</dd>
        <dt>Why</dt><dd>${esc(t.reason)}</dd>
        <dt>Road</dt><dd>${t.road ? esc(t.road.replace(/_/g, " ")) : "unknown"}${t.road_name ? `, ${esc(t.road_name)}` : ""}${t.factor ? `; traffic weight ×${esc(t.factor)}` : ""}</dd>
      </dl>
      <p class="jc-note">Based on: ${esc(t.basis)}. Not a traffic forecast.</p>
      <a class="btn small" href="${esc(c.location.maps_url)}" target="_blank" rel="noopener noreferrer">Live traffic in Google Maps</a>
    </div></div></section>`;
}

function planHtml(c) {
  const p = c.plan;
  return `<section class="jc-card" id="jc-plan" aria-labelledby="jc-plan-h"><div class="jc-pad">
    <h3 class="jc-h" id="jc-plan-h">${ICON.tool}Repair plan <span class="muted">Civil Helper</span></h3>
    <div class="jc-analysis ${esc(c.severity)}">
      <div class="jc-ah"><div><b>${esc(c.label)}</b><small>Severity: ${esc(c.severity)}</small></div><span class="jc-urg ${esc(p.urgency_code)}">${esc(p.urgency)}</span></div>
      ${p.warning ? `<p class="jc-alert">${ICON.alert}<span>${esc(p.warning)}</span></p>` : ""}
      ${p.method ? `<div class="jc-ab">
        <p><b>Method:</b> ${esc(p.method)}</p>
        <div class="jc-chips">${p.materials.map((m) => `<span>${esc(m)}</span>`).join("")}</div>
        ${p.mass_kg ? `<p class="muted small">Cold mix: ${esc(Math.round(p.mass_kg))} kg</p>` : ""}
        <ol class="jc-steps">${p.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>` : `<p class="jc-ab muted">Add the size to get a method and steps.</p>`}
    </div>
    <div class="jc-actions">
      <button class="btn small" type="button" data-jc="ask">Ask Civil Helper about this pothole</button>
      ${c.kind === "finding" && ["open", "not_fixed"].includes(c.status) ? `<button class="btn small" type="button" data-jc="wo">Add to a work order</button>` : ""}
      <button class="btn small" type="button" data-jc="send">Send to an engineer</button>
      <button class="btn small quiet" type="button" data-jc="map">Show on map</button>
    </div>
  </div></section>`;
}

let dlg = null, hooks = {}, current = null, spy = null;

function ensureDialog() {
  if (dlg) return dlg;
  dlg = document.createElement("dialog");
  dlg.className = "jobcard";
  dlg.setAttribute("aria-labelledby", "jc-title");
  document.body.append(dlg);
  dlg.addEventListener("click", onClick);
  dlg.addEventListener("submit", onSubmit);
  dlg.addEventListener("close", () => { spy?.disconnect(); current = null; });
  // tap on the backdrop closes it on a computer
  dlg.addEventListener("pointerdown", (e) => { if (e.target === dlg) dlg.close(); });
  return dlg;
}

function setCurrent(k) {
  for (const b of dlg.querySelectorAll(".jc-seg button")) b.toggleAttribute("aria-current", b.dataset.go === k);
}

function render(c, canEdit, ref) {
  const d = ensureDialog();
  d.innerHTML = `
    <header class="jc-top">
      <button class="btn icon quiet jc-close" type="button" aria-label="Close" data-jc="close">✕</button>
      <div class="jc-title"><h2 id="jc-title">${esc(c.label)} <span class="muted">${esc(c.id)}</span></h2>
        ${c.cost.available ? `<span class="jc-headcost">${moneyFmt(c.cost.subtotal, c.cost.symbol)} <small>materials</small></span>` : ""}</div>
      <nav class="jc-seg" aria-label="Sections">${SECTIONS.map(([k, l], i) => `<button type="button" data-go="${k}" ${i === 0 ? 'aria-current="true"' : ""}>${l}</button>`).join("")}</nav>
    </header>
    <div class="jc-body">
      <div class="jc-col">${locationHtml(c)}${ref?.kind === "finding" ? `<section class="jc-card chk" id="jc-check" aria-label="3D check"><div class="jc-pad"></div></section>` : ""}${timeHtml(c)}</div>
      <div class="jc-col">${costHtml(c, canEdit)}${planHtml(c)}</div>
    </div>`;
  if (ref?.kind === "finding") mountCheck(d.querySelector("#jc-check .jc-pad"), { project: ref.project, survey: ref.survey, id: ref.id }, { toast: hooks.toast });
  const img = d.querySelector(".jc-hero img[data-boxes]");
  if (img) {
    const fit = () => d.querySelector(".jc-boxes")?.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    img.complete ? fit() : img.addEventListener("load", fit, { once: true });
    img.addEventListener("error", () => img.closest("figure").classList.add("broken"), { once: true });
  }
  // keep the section tabs in step with scrolling: the current section is the last one whose top has
  // passed the top 35 % of the scroll area
  spy?.disconnect();
  const body = d.querySelector(".jc-body");
  const onScroll = () => {
    const line = body.getBoundingClientRect().top + body.clientHeight * 0.35;
    let cur = SECTIONS[0][0];
    for (const [k] of SECTIONS) { const el = d.querySelector(`#jc-${k}`); if (el && el.getBoundingClientRect().top <= line) cur = k; }
    if (body.scrollTop + body.clientHeight >= body.scrollHeight - 4) cur = SECTIONS[SECTIONS.length - 1][0];
    if (body.scrollTop < 8) cur = SECTIONS[0][0];  // two columns put Location and Cost side by side
    setCurrent(cur);
  };
  body.addEventListener("scroll", onScroll, { passive: true });
  spy = { disconnect: () => body.removeEventListener("scroll", onScroll) };
}

async function load(url) {
  const r = await fetch(url, { headers: HDR });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

/** Open the job card. ref = {kind: "finding", project, survey, id} or {kind: "pin", id}. */
export async function openJobCard(ref, opts = {}) {
  hooks = opts;
  const url = ref.kind === "pin" ? `/api/pins/${encodeURIComponent(ref.id)}/card`
    : `/api/projects/${ref.project}/surveys/${ref.survey}/findings/${encodeURIComponent(ref.id)}/card`;
  const d = ensureDialog();
  if (!d.open) {
    d.innerHTML = `<header class="jc-top"><button class="btn icon quiet jc-close" type="button" aria-label="Close" data-jc="close">✕</button><div class="jc-title"><h2 id="jc-title">Loading…</h2></div></header><div class="jc-body"><div class="jc-skel"></div><div class="jc-skel"></div></div>`;
    d.showModal();
  }
  try {
    current = { ref, card: await load(url) };
    render(current.card, !!opts.canEdit, ref);
    d.querySelector(".jc-body").scrollTop = 0;
  } catch (e) {
    d.close();
    opts.toast?.(e.message, true);
  }
}

function onClick(e) {
  const go = e.target.closest("[data-go]");
  if (go) {
    setCurrent(go.dataset.go);
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    dlg.querySelector(`#jc-${go.dataset.go}`)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    return;
  }
  const cp = e.target.closest("[data-copy]");
  if (cp) {
    navigator.clipboard?.writeText(cp.dataset.copy).then(() => hooks.toast?.("Coordinates copied"), () => {});
    return;
  }
  const b = e.target.closest("[data-jc]");
  if (!b) return;
  const a = b.dataset.jc;
  if (a === "close") return dlg.close();
  const c = current?.card;
  if (!c) return;
  dlg.close();
  hooks.onAction?.(a, c);
}

async function onSubmit(e) {
  if (!e.target.matches("[data-size]")) return;
  e.preventDefault();
  const f = new FormData(e.target);
  const size = Object.fromEntries(["width_cm", "length_cm", "depth_cm"].map((k) => [k, Number(f.get(k))]));
  try {
    const r = await fetch(`/api/pins/${encodeURIComponent(current.ref.id)}`, {
      method: "PATCH", headers: { ...HDR, "Content-Type": "application/json" }, body: JSON.stringify({ size }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    hooks.onChanged?.();
    await openJobCard(current.ref, hooks);
  } catch (err) { hooks.toast?.(err.message, true); }
}

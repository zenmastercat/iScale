/* Fix a 3D clip's scale with objects of known size seen in its frames (civil/scene_scale.py does the maths).

   1 choose an object from the catalog (road markings / vehicles / street furniture / custom distance)
   2 pick a frame with the slider and tap the object's two ends (drag a point to adjust it, magnifier on press)
   3 add it; every reference shows the scale it implies, the combination shows ± and flags outliers
   4 Apply: the clip is rescaled and re-analysed (findings get metric sizes and a cost); Undo puts it back.
   Same sheet layout, tap handling, magnifier and API helper as the photo measuring tool (static/measure.js). */
import { api } from "./measure.js";
import { getLang } from "./i18n.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
const LOUPE = 140;
const GROUP_LABEL = { road_markings: "Road markings", vehicles: "Vehicles", street_furniture: "Street furniture", custom: "Custom" };

let dlg = null, S = null, previewTimer = 0, previewSeq = 0;

const fx = (k) => `×${k >= 10 ? k.toFixed(1) : k.toFixed(3)}`;
const pctTxt = (p) => (p == null ? "" : `±${p < 10 ? p.toFixed(1) : Math.round(p)}%`);
const metres = (m) => (m >= 10 ? `${m.toFixed(1)} m` : m >= 1 ? `${m.toFixed(2)} m` : `${Math.round(m * 1000) / 10} cm`);
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
const base = () => `/api/projects/${S.opts.project}/surveys/${S.opts.survey}`;

/** opts: project, survey (clip survey id), title, toast, onApplied(result) */
export async function openSceneScale(opts) {
  const [info, cat] = await Promise.all([api(`/api/projects/${opts.project}/surveys/${opts.survey}/scale`), api("/api/scene_scale/refs")]);
  if (!info.available) throw new Error(info.why || "This survey cannot be scaled with scene objects.");
  const committed = (info.refs || []).filter((r) => r.points?.length === 2).map((r) => ({
    ref_id: r.ref_id, label: r.label, known_m: r.known_m, tol_m: r.tol_m ?? null,
    points: r.points.map((p) => ({ frame: p.frame, x: p.xy[0], y: p.xy[1] })), result: null, saved: true,
  }));
  const objs = cat.objects;
  S = {
    opts, info, objs, ref: objs.find((o) => !o.custom)?.id || "custom", knownM: "", tolCm: "",
    frame: committed[0]?.points[0].frame ?? Math.floor(info.frames / 2), frames: info.frames,
    pending: [], refs: committed, out: null, error: "", busy: false, zoom: 0, natW: 0, natH: 0, scale: 1, drag: null,
  };
  ensureDialog();
  dlg.innerHTML = shell();
  dlg.showModal();
  await loadFrame(S.frame);
  renderPanel();
  if (S.refs.length) schedule(0);
}

function ensureDialog() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "msheet ss-sheet";
  dlg.setAttribute("aria-labelledby", "ss-title");
  document.body.append(dlg);
  dlg.addEventListener("click", onClick);
  dlg.addEventListener("input", onInput);
  dlg.addEventListener("change", onInput);
  dlg.addEventListener("pointerdown", onDown);
  dlg.addEventListener("pointermove", onMove);
  dlg.addEventListener("pointerup", onUp);
  dlg.addEventListener("pointercancel", () => { if (S) { S.drag = null; loupe(null, null); draw(); } });
  dlg.addEventListener("close", () => { clearTimeout(previewTimer); S = null; dlg.innerHTML = ""; });
  new ResizeObserver(() => { if (S?.natW) { fit(true); draw(); } }).observe(dlg);
}

function shell() {
  return `<header class="ms-top">
      <button class="btn icon quiet jc-close" type="button" aria-label="Close" data-ss="close">✕</button>
      <div class="ms-title"><h2 id="ss-title">Fix the scale with scene objects</h2>${S.opts.title ? `<span class="muted">${esc(S.opts.title)}</span>` : ""}</div>
    </header>
    <div class="ms-body">
      <div class="ms-stage">
        <div class="ms-scroll"><div class="ms-canvas"><img alt="Clip frame to tap on" draggable="false"><svg class="ms-svg" aria-hidden="true"></svg></div></div>
        <p class="ms-hint" aria-live="polite"></p>
        <div class="ss-frames" role="group" aria-label="Frame">
          <button class="btn icon small" type="button" data-ss="prev" aria-label="Previous frame">‹</button>
          <input type="range" min="0" max="${S.frames - 1}" step="1" value="${S.frame}" data-k="frame" aria-label="Frame">
          <button class="btn icon small" type="button" data-ss="next" aria-label="Next frame">›</button>
          <span class="ss-fn"></span>
        </div>
        <div class="ms-zoom" role="group" aria-label="Zoom">
          <button class="btn icon small" type="button" data-ss="zout" aria-label="Zoom out">−</button>
          <span class="ms-zv">100%</span>
          <button class="btn icon small" type="button" data-ss="zin" aria-label="Zoom in">+</button>
        </div>
      </div>
      <aside class="ms-panel"></aside>
    </div>
    <div class="ms-loupe" hidden></div>`;
}

const frameUrl = (n) => `${base()}/frames/${n}`;

async function loadFrame(n) {
  S.frame = Math.max(0, Math.min(S.frames - 1, n));
  const img = dlg.querySelector(".ms-canvas img");
  await new Promise((ok, fail) => {
    img.addEventListener("load", ok, { once: true });
    img.addEventListener("error", () => fail(new Error("Could not load the frame")), { once: true });
    img.src = frameUrl(S.frame);
  }).catch((e) => { S.error = e.message; });
  const first = !S.natW;
  S.natW = img.naturalWidth || S.natW; S.natH = img.naturalHeight || S.natH;
  fit(!first);
  dlg.querySelector(".ss-fn").textContent = `Frame ${S.frame + 1} of ${S.frames}`;
  const r = dlg.querySelector('[data-k="frame"]');
  if (r && +r.value !== S.frame) r.value = S.frame;
  draw();
  hint();
}

// ------------------------------------------------------------------------------------------- state helpers
const cur = () => S.objs.find((o) => o.id === S.ref);
function objReady() {
  const o = cur();
  return o && (!o.custom || Number(S.knownM) > 0);
}
const pairDone = () => S.pending.length === 2;
function pendingSpec() {
  if (!pairDone() || !objReady()) return null;
  const o = cur();
  return { ref_id: o.id, label: o.custom ? `${Number(S.knownM)} m (custom)` : o.name_en, known_m: o.custom ? Number(S.knownM) : o.value_m,
    tol_m: o.custom && Number(S.tolCm) > 0 ? Number(S.tolCm) / 100 : null, points: S.pending.map((p) => ({ frame: p.frame, x: p.x, y: p.y })) };
}
const objName = (o) => (getLang() === "th" && o.name_th) || o.name_en;
const shown = (r) => { const o = S.objs.find((x) => x.id === r.ref_id); return o && !o.custom ? objName(o) : r.label; };
const isProv = (r) => r.ref_id !== "custom" && !!S.objs.find((o) => o.id === r.ref_id)?.provisional;
const allSpecs = () => [...S.refs, ...(pendingSpec() ? [pendingSpec()] : [])];

// ------------------------------------------------------------------------------------------- panel
function objChoice(o) {
  const size = o.custom ? "" : `${metres(o.value_m)} ${pctTxt(o.rel_error * 100)}`;
  const src = (o.source_urls || []).slice(0, 2).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(host(u))}</a>`).join(", ");
  return `<label class="ms-ref ss-obj ${S.ref === o.id ? "on" : ""}"><input type="radio" name="ss-obj" value="${esc(o.id)}" ${S.ref === o.id ? "checked" : ""}>
    <span>${getLang() === "th" && o.name_th
      ? `<b lang="th" data-no-i18n>${esc(o.name_th)}</b><small data-no-i18n>${esc(o.name_en)}</small>`
      : `<b data-no-i18n>${esc(o.name_en)}</b>${o.name_th ? `<small lang="th" data-no-i18n>${esc(o.name_th)}</small>` : ""}`}
      ${o.dimension_name ? `<small>${esc(o.dimension_name)}${size ? `: <b class="ss-size">${esc(size)}</b>` : ""}</small>` : ""}
      ${o.rel_unknown && !o.custom ? `<small>No tolerance in the source: ±10% assumed</small>` : ""}
      ${src ? `<small class="ss-src">Source: ${src}${o.source_dates?.length ? ` (${esc(o.source_dates.join(", "))})` : ""}</small>` : ""}
      ${o.provisional && !o.custom ? `<small class="ss-prov" title="${esc(o.source_note || "")}">Provisional size, no source yet: check it on site if you can</small>` : ""}
      ${S.ref === o.id && o.notes ? `<small class="ss-how">${esc(o.notes)}</small>` : ""}</span></label>`;
}

function objectsHtml() {
  const groups = {};
  for (const o of S.objs) (groups[o.group] ||= []).push(o);
  const order = ["road_markings", "vehicles", "street_furniture", "custom"];
  const o = cur();
  return order.filter((g) => groups[g]).map((g) => `<div class="ss-group"><p class="ss-gh">${esc(GROUP_LABEL[g] || g)}</p>
      <div class="ss-objs" role="radiogroup" aria-label="${esc(GROUP_LABEL[g] || g)}">${groups[g].map(objChoice).join("")}</div></div>`).join("")
    + (o?.custom ? `<div class="ms-row2"><label class="field"><span>Known distance (m)</span><input class="input num" data-k="knownM" type="number" inputmode="decimal" min="0.05" max="200" step="0.01" value="${esc(S.knownM)}" placeholder="e.g. 3.50"></label>
        <label class="field"><span>± (cm), optional</span><input class="input num" data-k="tolCm" type="number" inputmode="decimal" min="0" max="500" step="0.5" value="${esc(S.tolCm)}" placeholder="1 %"></label></div>
        <p class="ms-note">A length you measured on site with a tape, between two marks you can see in the clip.</p>` : "")
    + (o && !o.custom && o.vertical ? `<p class="ms-note">A height: tap the foot where it meets the road and the top straight above it. Only the vertical part of the distance counts.</p>`
      : o && !o.custom && o.plane === "upright" ? `<p class="ms-note">An upright object: both ends must be on surfaces the 3D shows, close to the camera.</p>` : "")
    + (S.objs.length === 1 ? `<p class="ms-note">The catalog of standard objects (lane width, licence plates, manhole covers…) is not installed on this server yet, so only a distance you know can be used.</p>` : "");
}

function refRow(r, i, res) {
  const f = r.points[0].frame, f2 = r.points[1].frame;
  const where = f === f2 ? `Frame ${f + 1}` : `Frames ${f + 1} and ${f2 + 1}`;
  const body = res?.error ? `<span class="ss-err">${esc(res.error)}</span>`
    : res ? `<span class="ss-k"><b>${esc(fx(res.scale))}</b> ${esc(pctTxt(res.pct))}</span>${res.outlier ? `<span class="ss-flag" title="More than 3σ from the others: left out of the result">Outlier</span>` : ""}`
      : `<span class="muted">…</span>`;
  return `<li class="ss-row ${res?.outlier ? "out" : ""} ${res?.error ? "bad" : ""}">
      <button class="btn small quiet" type="button" data-ss="goto" data-i="${i}">${esc(where)}</button>
      <span class="ss-lab"><span data-no-i18n>${esc(shown(r))}</span>${r.saved ? ` <small class="muted">applied</small>` : ""}${isProv(r) ? ` <small class="ss-prov">provisional size</small>` : ""}</span>${body}
      <button class="btn icon small quiet" type="button" data-ss="remove" data-i="${i}" aria-label="Remove this reference">✕</button></li>`;
}

function renderPanel() {
  const p = dlg.querySelector(".ms-panel");
  const st = !objReady() ? 1 : !pairDone() ? 2 : 3;
  const sec = (n, title, body, cls = "") => `<section class="ms-sec ${cls} ${st === n ? "now" : st > n ? "done" : ""}" data-n="${n}"><h3><span class="ms-n">${n}</span>${title}</h3>${body}</section>`;
  const tapBody = `<p class="ms-note">Choose a frame where the object is close and sharp, then tap its two ends. Drag a point to adjust it.</p>
    <div class="ms-acts"><button class="btn small" type="button" data-ss="undo-pt" ${S.pending.length ? "" : "disabled"}>Undo point</button>
      <button class="btn small quiet" type="button" data-ss="clear" ${S.pending.length ? "" : "disabled"}>Clear</button>
      <button class="btn small primary" type="button" data-ss="add" ${pendingSpec() ? "" : "disabled"}>Add reference</button></div>
    <div class="ss-pair" aria-live="polite"></div>`;
  p.innerHTML = `<section class="ms-sec ss-now"><p class="ms-note">Scale now: <b>${esc(S.info.text)}</b>${S.info.clip_length_m ? `. Clip length ${esc(metres(S.info.clip_length_m))}` : ""}</p>
      ${S.info.method === "scene" && S.info.mark ? `<p class="ms-note">${esc(S.info.mark)}</p>` : ""}
      ${S.info.method === "camera_height" ? `<p class="ms-note">The size of this clip is a guess from an assumed camera height, so depths, areas and costs are not real measurements yet.</p>` : ""}</section>
    ${sec(1, "Object of known size", objectsHtml())}
    ${sec(2, "Tap its two ends", tapBody)}
    <section class="ms-sec ss-list"><h3>References <span class="muted">${S.refs.length}</span></h3>
      ${S.refs.length ? `<ul class="ss-rows"></ul>` : `<p class="ms-note">Each reference you add shows the scale it implies. Two or three different objects give a check on each other.</p>`}</section>
    <section class="ms-sec ms-out" aria-live="polite"></section>
    <footer class="ms-foot"><button class="btn primary big" type="button" data-ss="apply" disabled>Apply scale and re-analyse</button>
      ${S.info.can_undo ? `<button class="btn quiet" type="button" data-ss="undo">Undo last scale fix</button>` : ""}</footer>`;
  updateLive();
}

function updateLive() {
  if (!dlg || !S) return;
  const out = S.out;
  const rows = dlg.querySelector(".ss-rows");
  if (rows) rows.innerHTML = S.refs.map((r, i) => refRow(r, i, out?.refs?.[i])).join("");
  const pair = dlg.querySelector(".ss-pair");
  if (pair) {
    const pr = pendingSpec() && out?.refs?.length > S.refs.length ? out.refs[S.refs.length] : null;
    pair.innerHTML = !S.pending.length ? ""
      : !pairDone() ? `<p class="ms-note">Point 1 on frame ${S.pending[0].frame + 1}. Tap the other end${S.frames > 1 ? " (on this or another frame)" : ""}.</p>`
        : !objReady() ? `<p class="ms-note">Type the known distance first.</p>`
          : pr?.error ? `<p class="ms-err">${esc(pr.error)}</p>`
            : pr ? `<p class="ss-pairres">This pair: <b>${esc(fx(pr.scale))}</b> ${esc(pctTxt(pr.pct))} <small>(${esc(pr.support.join(" and "))} 3D points at its ends)</small></p>${pr.warnings?.length ? `<ul class="ms-warn">${pr.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}`
              : `<p class="ms-note">Measuring…</p>`;
  }
  const res = dlg.querySelector(".ms-out");
  if (res) res.innerHTML = resultHtml();
  const ap = dlg.querySelector('[data-ss="apply"]');
  if (ap) ap.disabled = !canApply();
  const add = dlg.querySelector('[data-ss="add"]');
  if (add) add.disabled = !pendingSpec();
  hint();
}

const canApply = () => !!(S.out?.combined && !S.error && !S.busy && allSpecs().length && !(S.out.refs || []).some((r) => r.error));

function resultHtml() {
  if (S.error) return `<h3>Result</h3><p class="ms-err">${esc(S.error)}</p>`;
  const c = S.out?.combined;
  if (!allSpecs().length) return `<h3>Result</h3><p class="ms-note">The combined scale appears here as soon as a reference is marked.</p>`;
  if (!c) return `<h3>Result</h3><p class="ms-note">Measuring…</p>`;
  const lenRow = S.out.clip_length_m ? `<div><dt>Clip length</dt><dd><b>${esc(metres(S.out.clip_length_after_m))}</b><small>now ${esc(metres(S.out.clip_length_m))}</small></dd></div>` : "";
  return `<h3>Result <span class="muted">${esc(c.used)} of ${esc(allSpecs().length)} references</span></h3>
    <dl class="ms-res">
      <div><dt>Scale factor</dt><dd><b>${esc(fx(c.scale))}</b><small>${esc(pctTxt(c.pct))}, p10–p90 ${esc(c.range[0].toFixed(3))}–${esc(c.range[1].toFixed(3))}</small></dd></div>
      ${lenRow}
    </dl>
    <p class="ms-note">Every length in the 3D clip is multiplied by this factor; areas by its square. Apply re-runs the analysis, so depths, areas and the repair cost follow.</p>
    ${allSpecs().some(isProv) ? `<p class="ms-note ss-prov">Some sizes are provisional (no published source yet): the result is only as good as those sizes. A distance measured with a tape is better.</p>` : ""}
    ${c.warnings?.length ? `<ul class="ms-warn">${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}`;
}

function hint() {
  const h = dlg?.querySelector(".ms-hint");
  if (!h || !S) return;
  let t;
  if (!objReady()) t = "Type the known distance";
  else if (S.pending.length < 2) t = `Tap the ${S.pending.length ? "second" : "first"} end of the ${cur().custom ? "known distance" : objName(cur())} (${S.pending.length} of 2)`;
  else if (S.error) t = S.error;
  else if (S.out?.combined) t = `Scale ${fx(S.out.combined.scale)} ${pctTxt(S.out.combined.pct)}`;
  else t = "Measuring…";
  h.textContent = t;
}

// ------------------------------------------------------------------------------------------- drawing
function fit(keep = false) {
  const sc = dlg.querySelector(".ms-scroll");
  if (!S.natW) return;
  const fitS = Math.min(sc.clientWidth / S.natW, sc.clientHeight / S.natH);
  if (!keep || !S.fitS) S.zoom = 0;
  S.fitS = fitS;
  S.scale = fitS * ZOOMS[S.zoom];
  const cv = dlg.querySelector(".ms-canvas");
  cv.style.width = `${S.natW * S.scale}px`;
  cv.style.height = `${S.natH * S.scale}px`;
  cv.classList.toggle("zoomed", S.zoom > 0);
  dlg.querySelector(".ms-svg").setAttribute("viewBox", `0 0 ${S.natW} ${S.natH}`);
  dlg.querySelector(".ms-zv").textContent = `${Math.round(ZOOMS[S.zoom] * 100)}%`;
}

function setZoom(dz) {
  const sc = dlg.querySelector(".ms-scroll");
  const cx = (sc.scrollLeft + sc.clientWidth / 2) / S.scale, cy = (sc.scrollTop + sc.clientHeight / 2) / S.scale;
  S.zoom = Math.max(0, Math.min(ZOOMS.length - 1, S.zoom + dz));
  fit(true);
  sc.scrollLeft = cx * S.scale - sc.clientWidth / 2;
  sc.scrollTop = cy * S.scale - sc.clientHeight / 2;
  draw();
}

function draw() {
  if (!dlg || !S) return;
  const svg = dlg.querySelector(".ms-svg");
  const k = 1 / S.scale;
  // keep labels inside the frame: near the right edge they end at the point, near the left they start there
  const label = (x, y, text) => {
    const anchor = x > S.natW * 0.7 ? "end" : x < S.natW * 0.3 ? "start" : "middle";
    return `<text x="${x}" y="${y - 16 * k}" font-size="${13 * k}" stroke-width="${3 * k}" style="text-anchor:${anchor}">${esc(text)}</text>`;
  };
  let out = "";
  S.refs.forEach((r, i) => {
    const pts = r.points.filter((p) => p.frame === S.frame);
    const res = S.out?.refs?.[i];
    const cls = res?.outlier || res?.error ? "ss-line out" : "ss-line";
    if (pts.length === 2) {
      out += `<line class="${cls}" x1="${pts[0].x}" y1="${pts[0].y}" x2="${pts[1].x}" y2="${pts[1].y}"/>`;
      out += label((pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2, res && !res.error ? `${shown(r)} ${fx(res.scale)}` : shown(r));
    }
    out += pts.map((p) => `<circle class="${cls}-end" cx="${p.x}" cy="${p.y}" r="${5 * k}" stroke-width="${2 * k}"/>`).join("");
  });
  const here = S.pending.map((p, i) => ({ ...p, i })).filter((p) => p.frame === S.frame);
  if (here.length === 2) {
    out += `<line class="ss-line pending" x1="${here[0].x}" y1="${here[0].y}" x2="${here[1].x}" y2="${here[1].y}"/>`;
    const o = cur();
    if (objReady()) out += label((here[0].x + here[1].x) / 2, (here[0].y + here[1].y) / 2, o.custom ? `${Number(S.knownM)} m` : metres(o.value_m));
  }
  const hitR = matchMedia("(pointer: coarse)").matches ? 20 : 11;
  out += here.map((p) => `<g class="ms-h ref" data-i="${p.i}"><circle class="hit" cx="${p.x}" cy="${p.y}" r="${hitR * k}"/><circle class="dot" cx="${p.x}" cy="${p.y}" r="${7 * k}" stroke-width="${2.5 * k}"/></g>`).join("");
  svg.innerHTML = out;
}

// ------------------------------------------------------------------------------------------- pointer
function toImage(e) {
  const rc = dlg.querySelector(".ms-canvas").getBoundingClientRect();
  const x = (e.clientX - rc.left) / S.scale, y = (e.clientY - rc.top) / S.scale;
  return [Math.round(Math.max(0, Math.min(S.natW, x)) * 10) / 10, Math.round(Math.max(0, Math.min(S.natH, y)) * 10) / 10];
}

function loupe(e, p) {
  const el = dlg.querySelector(".ms-loupe");
  if (!el) return;
  if (!p) { el.hidden = true; return; }
  const mag = Math.min(8, Math.max(S.scale * 4, 2));
  el.hidden = false;
  el.style.backgroundImage = `url("${frameUrl(S.frame)}")`;
  el.style.backgroundSize = `${S.natW * mag}px ${S.natH * mag}px`;
  el.style.backgroundPosition = `${LOUPE / 2 - p[0] * mag}px ${LOUPE / 2 - p[1] * mag}px`;
  let top = e.clientY - LOUPE - 48;
  if (top < 8) top = e.clientY + 48;
  el.style.left = `${Math.max(8, Math.min(innerWidth - LOUPE - 8, e.clientX - LOUPE / 2))}px`;
  el.style.top = `${top}px`;
}

function onDown(e) {
  if (!S || e.button > 0) return;
  const cv = e.target.closest(".ms-canvas");
  if (!cv) return;
  const h = e.target.closest(".ms-h");
  if (h) {
    e.preventDefault();
    S.drag = { i: +h.dataset.i, id: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
  } else if (e.pointerType === "touch" && S.zoom > 0) {
    S.drag = { tap: true, id: e.pointerId, x: e.clientX, y: e.clientY };
    return;
  } else {
    if (!objReady() || pairDone()) { hint(); return; }
    e.preventDefault();
    S.drag = { add: true, id: e.pointerId, p: toImage(e) };
  }
  try { cv.setPointerCapture?.(e.pointerId); } catch { /* pointer gone */ }
  onMove(e);
}

function onMove(e) {
  const d = S?.drag;
  if (!d || d.id !== e.pointerId || d.tap) return;
  if (d.i != null && !d.moved) {
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) return;
    d.moved = true;
  }
  const p = toImage(e);
  if (d.add) d.p = p;
  else { S.pending[d.i] = { frame: S.frame, x: p[0], y: p[1] }; draw(); schedule(250); }
  loupe(e, p);
}

function onUp(e) {
  const d = S?.drag;
  if (!d || d.id !== e.pointerId) return;
  S.drag = null;
  loupe(e, null);
  if (d.tap) {
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 8 || !objReady() || pairDone()) return;
    addPoint(toImage(e));
  } else if (d.add) addPoint(d.p);
  else if (d.moved) { draw(); schedule(0); }
}

function addPoint(p) {
  if (pairDone()) return;
  S.pending.push({ frame: S.frame, x: p[0], y: p[1] });
  S.error = "";
  draw();
  renderPanel();
  schedule(0);
}

// ------------------------------------------------------------------------------------------- preview / apply
function payload(specs) {
  return { refs: specs.map((r) => ({ ref_id: r.ref_id, known_m: r.ref_id === "custom" ? r.known_m : null, tol_m: r.tol_m ?? null, points: r.points })), tol_px: 3 };
}

function schedule(ms) {
  clearTimeout(previewTimer);
  if (!S) return;
  if (!allSpecs().length) { S.out = null; S.error = ""; updateLive(); draw(); return; }
  previewTimer = setTimeout(preview, ms);
}

async function preview() {
  const seq = ++previewSeq;
  const specs = allSpecs();
  try {
    const j = await api(`${base()}/scale/preview`, { method: "POST", body: JSON.stringify(payload(specs)) });
    if (!S || seq !== previewSeq) return;
    S.out = j; S.error = "";
  } catch (e) {
    if (!S || seq !== previewSeq) return;
    S.out = null; S.error = e.message;
  }
  updateLive();
  draw();
}

function addRef() {
  const sp = pendingSpec();
  if (!sp) return;
  S.refs.push({ ...sp, result: null });
  S.pending = [];
  renderPanel();
  draw();
  schedule(0);
}

async function apply() {
  if (!canApply()) return;
  S.busy = true;
  const btn = dlg.querySelector('[data-ss="apply"]');
  if (btn) { btn.disabled = true; btn.textContent = "Re-analysing the clip…"; }
  try {
    const out = await api(`${base()}/scale/apply`, { method: "POST", body: JSON.stringify(payload(allSpecs())) });
    const { toast, onApplied } = S.opts;
    dlg.close();
    toast?.(`Scale fixed: ${fx(out.factor)} ${pctTxt(out.combined.pct)}. The clip was re-analysed: ${out.stats.findings} ${out.stats.findings === 1 ? "finding" : "findings"}.`);
    onApplied?.(out);
  } catch (e) {
    S.busy = false;
    S.error = e.message;
    renderPanel();
  }
}

async function undo() {
  if (S.busy) return;
  S.busy = true;
  try {
    const out = await api(`${base()}/scale/undo`, { method: "POST", body: "{}" });
    const { toast, onApplied } = S.opts;
    dlg.close();
    toast?.(`Scale put back: ${out.scale.text}.`);
    onApplied?.(out);
  } catch (e) {
    S.busy = false;
    S.error = e.message;
    renderPanel();
  }
}

// ------------------------------------------------------------------------------------------- events
function onClick(e) {
  if (e.target === dlg || !S) return;
  const b = e.target.closest("[data-ss]");
  if (!b) return;
  const a = b.dataset.ss;
  if (a === "close") return dlg.close();
  if (a === "zin") return setZoom(1);
  if (a === "zout") return setZoom(-1);
  if (a === "prev") return loadFrame(S.frame - 1);
  if (a === "next") return loadFrame(S.frame + 1);
  if (a === "apply") return apply();
  if (a === "undo") return undo();
  if (a === "add") return addRef();
  if (a === "goto") return loadFrame(S.refs[+b.dataset.i].points[0].frame);
  if (a === "remove") S.refs.splice(+b.dataset.i, 1);
  if (a === "undo-pt") S.pending.pop();
  if (a === "clear") S.pending = [];
  S.error = "";
  renderPanel();
  draw();
  schedule(0);
}

function onInput(e) {
  const t = e.target;
  if (!S) return;
  if (t.name === "ss-obj" && e.type === "change") {
    S.ref = t.value;
    renderPanel(); draw(); schedule(0);
    return;
  }
  const k = t.dataset.k;
  if (!k) return;
  if (k === "frame") { if (e.type === "input") loadFrame(+t.value); return; }
  if (e.type !== "input") return;
  S[k] = t.value;
  draw();
  updateLive();
  schedule(300);
}

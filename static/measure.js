/* Measuring sheet: measure a pothole in a photo from a reference object of known size lying on the road.

   1 choose the reference (A4, A3, ID card, custom W x L, or a 2-point ruler for straight-down photos)
   2 tap its corners   3 trace the hole (or use the detector box)   4 depth (typed, or the 3D depth rescaled)
   The numbers, their ranges, warnings and the materials bill come live from POST /api/measure/preview
   (civil/measure.py does the maths). Points are kept in the photo's own pixels. Works with mouse and touch:
   tap to add a point, drag a handle to move it, a magnifier shows the spot under the finger. */
import { moneyFmt } from "./jobcard.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HDR = { "X-Civil-Scan": "1" };
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
const LOUPE = 140;

let dlg = null, S = null, refsCache = null, previewTimer = 0, previewSeq = 0;

export async function api(url, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const r = await fetch(url, { ...opts, headers: { ...HDR, ...(opts.body && !isForm ? { "Content-Type": "application/json" } : {}) } });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg || msg); } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}

async function refs() {
  refsCache ??= api("/api/measure/refs").catch((e) => { refsCache = null; throw e; });
  return refsCache;
}

const cm = (m, d = 1) => `${Number((m * 100).toFixed(d))}`;
const m2 = (v) => (v < 10 ? v.toFixed(2) : v.toFixed(1));

/** Where to save: URL for a finding or a pin. */
export function measureUrl(t) {
  return t.kind === "pin" ? `/api/pins/${encodeURIComponent(t.id)}/measurement`
    : `/api/projects/${t.project}/surveys/${t.survey}/findings/${encodeURIComponent(t.id)}/measurement`;
}
function photoUrl(t) {
  return t.kind === "pin" ? `/api/pins/${encodeURIComponent(t.id)}/photo`
    : `/api/projects/${t.project}/surveys/${t.survey}/findings/${encodeURIComponent(t.id)}/photo`;
}

export async function undoMeasure(t) {
  return api(measureUrl(t) + "/undo", { method: "POST", body: "{}" });
}

/** Ask for a photo, shrink it in the browser (upright, at most 3000 px, JPEG) and upload it to the finding or pin. */
export function pickAndUploadPhoto(t) {
  return new Promise((resolve, reject) => {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = "image/*";
    inp.addEventListener("change", async () => {
      const f = inp.files?.[0];
      if (!f) return resolve(null);
      try {
        const bmp = await createImageBitmap(f, { imageOrientation: "from-image" });
        const s = Math.min(1, 3000 / Math.max(bmp.width, bmp.height));
        const c = document.createElement("canvas");
        c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
        c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
        const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.9));
        const fd = new FormData();
        fd.append("file", blob || f, "photo.jpg");
        resolve(await api(photoUrl(t), { method: "POST", body: fd }));
      } catch (e) { reject(e); }
    }, { once: true });
    inp.click();
  });
}

/** From a card or drawer: measure on the photo it has, or ask for one first (newPhoto = always ask). */
export async function startMeasure({ target, photo, box = null, title = "", newPhoto = false, toast, onSaved }) {
  try {
    let url = photo?.url, imageRef = photo?.kind === "frame" ? { kind: "frame", frame: photo.frame } : { kind: "photo" };
    if (!url || newPhoto) {
      const up = await pickAndUploadPhoto(target);
      if (!up) return;
      url = up.url; imageRef = { kind: "photo" }; box = null;
      onSaved?.({ photoOnly: true });
    }
    await openMeasure({ image: url, imageRef, box, target, title, toast, onSaved });
  } catch (e) { toast?.(e.message, true); }
}

// ------------------------------------------------------------------------------------------- the sheet
/** opts: image (url), imageRef {kind, frame?, survey?, file?, t?}, box [x0,y0,x1,y1] or null,
    target {kind, id, project?, survey?} or null, targets [{target, label}] (choose where to save), title, toast, onSaved */
export async function openMeasure(opts) {
  const list = await refs();
  S = {
    opts, refs: list.refs, ref: opts.initialRef || "a4",
    customW: opts.initialCustomW || "", customL: opts.initialCustomL || "", rulerL: opts.initialRulerL || "",
    refPts: [], outline: [], useBox: false,
    firstEdge: null, depthCm: "", depthMode: null, zoom: 0, natW: 0, natH: 0, scale: 1, result: null, error: "",
    drag: null, busy: false, target: opts.target || opts.targets?.[0]?.target || null,
  };
  ensureDialog();
  dlg.innerHTML = shell();
  dlg.showModal();
  const img = dlg.querySelector(".ms-canvas img");
  await new Promise((ok, fail) => {
    img.addEventListener("load", ok, { once: true });
    img.addEventListener("error", () => fail(new Error("Could not load the photo")), { once: true });
    img.src = opts.image;
  }).catch((e) => { dlg.close(); throw e; });
  S.natW = img.naturalWidth; S.natH = img.naturalHeight;
  fit();
  renderPanel();
  draw();
}

function ensureDialog() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "msheet";
  dlg.setAttribute("aria-labelledby", "ms-title");
  document.body.append(dlg);
  dlg.addEventListener("click", onClick);
  dlg.addEventListener("input", onInput);
  dlg.addEventListener("change", onInput);
  dlg.addEventListener("pointerdown", onDown);
  dlg.addEventListener("pointermove", onMove);
  dlg.addEventListener("pointerup", onUp);
  dlg.addEventListener("pointercancel", onCancel);
  dlg.addEventListener("close", () => { clearTimeout(previewTimer); S = null; dlg.innerHTML = ""; });
  new ResizeObserver(() => { if (S?.natW) { fit(true); draw(); } }).observe(dlg);
}

function shell() {
  return `<header class="ms-top">
      <button class="btn icon quiet jc-close" type="button" aria-label="Close" data-ms="close">✕</button>
      <div class="ms-title"><h2 id="ms-title">Measure the pothole</h2>${S.opts.title ? `<span class="muted">${esc(S.opts.title)}</span>` : ""}</div>
    </header>
    <div class="ms-body">
      <div class="ms-stage">
        <div class="ms-scroll"><div class="ms-canvas"><img alt="Photo to measure on" draggable="false"><svg class="ms-svg" aria-hidden="true"></svg></div></div>
        <p class="ms-hint" aria-live="polite"></p>
        <div class="ms-zoom" role="group" aria-label="Zoom">
          <button class="btn icon small" type="button" data-ms="zout" aria-label="Zoom out">−</button>
          <span class="ms-zv">100%</span>
          <button class="btn icon small" type="button" data-ms="zin" aria-label="Zoom in">+</button>
        </div>
      </div>
      <aside class="ms-panel"></aside>
    </div>
    <div class="ms-loupe" hidden></div>`;
}

const curRef = () => S.refs.find((r) => r.id === S.ref);
const isLine = () => curRef()?.kind === "line";
const needPts = () => (isLine() ? 2 : 4);
function refReady() {
  const r = curRef();
  if (r.kind === "line") return Number(S.rulerL) > 0;
  if (r.custom) return Number(S.customW) > 0 && Number(S.customL) > 0;
  return true;
}
const outlineReady = () => S.useBox || S.outline.length >= 3;
const ready = () => refReady() && S.refPts.length === needPts() && outlineReady();
function step() {
  if (!refReady()) return 1;
  if (S.refPts.length < needPts()) return 2;
  if (!outlineReady()) return 3;
  return 4;
}

// ------------------------------------------------------------------------------------------- panel
function refChoice(r) {
  const dims = r.kind === "rect" && !r.custom ? `${cm(r.width_m, 2)} × ${cm(r.length_m, 2)} cm` : "";
  return `<label class="ms-ref ${S.ref === r.id ? "on" : ""}"><input type="radio" name="ms-ref" value="${esc(r.id)}" ${S.ref === r.id ? "checked" : ""}>
    <span><b>${esc(r.label)}</b>${dims ? `<small>${esc(dims)}</small>` : ""}</span></label>`;
}

function renderPanel() {
  const p = dlg.querySelector(".ms-panel");
  const st = step(), r = curRef();
  const sec = (n, title, body) => `<section class="ms-sec ${st === n ? "now" : st > n ? "done" : ""}" data-n="${n}"><h3><span class="ms-n">${n}</span>${title}</h3>${body}</section>`;
  const dimsTxt = r.kind === "line" ? (Number(S.rulerL) > 0 ? `${S.rulerL} cm` : "") : r.custom ? (refReady() ? `${S.customW} × ${S.customL} cm` : "")
    : `${cm(r.width_m, 2)} × ${cm(r.length_m, 2)} cm`;
  const collapsed = S.refPts.length > 0 && refReady() && !S.showRefs;   // chosen and in use: one line, Change opens it
  const refBody = collapsed ? `<p class="ms-chosen"><b>${esc(r.label)}</b><span>${esc(dimsTxt)}</span><button class="btn small quiet" type="button" data-ms="refs">Change</button></p>`
    : `<div class="ms-refs" role="radiogroup" aria-label="Reference object">${S.refs.map(refChoice).join("")}</div>
    ${r.kind === "rect" && r.custom ? `<div class="ms-row2"><label class="field"><span>Width (cm)</span><input class="input num" data-k="customW" type="number" inputmode="decimal" min="0.5" max="5000" step="0.1" value="${esc(S.customW)}"></label>
      <label class="field"><span>Length (cm)</span><input class="input num" data-k="customL" type="number" inputmode="decimal" min="0.5" max="5000" step="0.1" value="${esc(S.customL)}"></label></div>` : ""}
    ${r.kind === "line" ? `<label class="field"><span>Length between the two marks (cm)</span><input class="input num" data-k="rulerL" type="number" inputmode="decimal" min="1" max="10000" step="0.1" value="${esc(S.rulerL)}"></label>
      <p class="ms-note">Only for a photo taken straight down at the hole: two points give a scale but no perspective.</p>` : ""}
    ${r.kind === "rect" ? `<p class="ms-note">Lay it flat on the road next to the hole, fully in the photo.</p>` : ""}`;
  const canSwap = !isLine() && S.refPts.length === 4 && r.width_m !== r.length_m && (!r.custom || Number(S.customW) !== Number(S.customL));
  const cornersBody = `<p class="ms-note">${isLine() ? "Tap both ends of the known length." : "Tap the 4 corners, in any order. Drag a corner to adjust it."}</p>
    <div class="ms-acts"><button class="btn small" type="button" data-ms="undo-ref" ${S.refPts.length ? "" : "disabled"}>Undo point</button>
      <button class="btn small quiet" type="button" data-ms="clear-ref" ${S.refPts.length ? "" : "disabled"}>Clear</button>
      ${canSwap ? `<button class="btn small" type="button" data-ms="swap" title="Swap which side is the long one">Swap long side</button>` : ""}</div>`;
  const outlineBody = `<p class="ms-note">Tap round the edge of the hole (at least 3 points). Drag a point to adjust it.</p>
    <div class="ms-acts"><button class="btn small" type="button" data-ms="undo-out" ${S.outline.length && !S.useBox ? "" : "disabled"}>Undo point</button>
      <button class="btn small quiet" type="button" data-ms="clear-out" ${S.outline.length || S.useBox ? "" : "disabled"}>Clear</button>
      ${S.opts.box ? `<button class="btn small" type="button" data-ms="box" aria-pressed="${S.useBox}">Use detector box</button>` : ""}</div>
    ${S.useBox ? `<p class="ms-note">The detector's box is larger than the hole inside it, so this gives an upper bound.</p>` : ""}`;
  const three = S.result?.three_d;
  if (S.depthMode === null && three) S.depthMode = "rescale";
  const mode = S.depthMode || "typed";
  const depthBody = `${three ? `<div class="ms-seg" role="radiogroup" aria-label="Depth">
      <label><input type="radio" name="ms-dm" value="typed" ${mode === "typed" ? "checked" : ""}><span>Type the depth</span></label>
      <label><input type="radio" name="ms-dm" value="rescale" ${mode === "rescale" ? "checked" : ""}><span>Rescale the 3D depth</span></label></div>` : ""}
    ${mode === "typed" || !three ? `<label class="field"><span>Depth measured on site with a ruler (cm)</span><input class="input num" data-k="depthCm" type="number" inputmode="decimal" min="0.1" max="200" step="0.5" value="${esc(S.depthCm)}" placeholder="e.g. 6"></label>`
      : `<p class="ms-note"><span>3D depth</span> <b>${esc(cm(three.depth_max_m ?? three.depth_median_m))} cm</b>, <span>3D area</span> <b>${esc(m2(three.area_m2))} m²</b></p>
         <p class="ms-note">The 3D depth is multiplied by k = √(area measured here ÷ 3D area). It is refused when k is outside 0.2–5.</p>`}`;
  const targets = S.opts.targets;
  const saveBody = targets ? (targets.length ? `<label class="field"><span>Save to</span><select class="input" data-k="target">${targets.map((t, i) => `<option value="${i}" ${t.target === S.target ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></label>`
    : `<p class="ms-note">Preview only: this clip has no pothole finding to save to yet.</p>`) : "";
  p.innerHTML = `${sec(1, "Reference object", refBody)}${sec(2, isLine() ? "Ends of the ruler" : "Corners of the reference", cornersBody)}
    ${sec(3, "Pothole outline", outlineBody)}${sec(4, "Depth", depthBody)}
    <section class="ms-sec ms-out" aria-live="polite">${resultsHtml()}</section>
    <footer class="ms-foot">${saveBody}<button class="btn primary big" type="button" data-ms="save" ${canSave() ? "" : "disabled"}>${!S.target && S.opts.onSelect ? "Use in project" : "Save measurement"}</button></footer>`;
  hint();
}

const canSave = () => !!(ready() && (S.target || S.opts.onSelect) && S.result?.result && !S.error && !S.busy);

/** Refresh what changes while someone types (step marks, results, Save, hint) without rebuilding the inputs. */
function updateLive() {
  const st = step();
  dlg.querySelectorAll(".ms-sec[data-n]").forEach((el) => {
    const n = +el.dataset.n;
    el.classList.toggle("now", st === n);
    el.classList.toggle("done", st > n);
  });
  const out = dlg.querySelector(".ms-out");
  if (out) out.innerHTML = resultsHtml();
  const b = dlg.querySelector('[data-ms="save"]');
  if (b) b.disabled = !canSave();
  hint();
}

function rangeTxt(lo, hi, f) { return `${f(lo)}–${f(hi)}`; }

function resultsHtml() {
  if (S.error) return `<h3>Result</h3><p class="ms-err">${esc(S.error)}</p>`;
  const j = S.result;
  if (!j || !ready()) return `<h3>Result</h3><p class="ms-note">The size appears here as soon as the reference and the outline are marked.</p>`;
  const r = j.result, m = j.metrics, d = j.depth, b = j.bill, rg = r.ranges;
  const pct = (k) => (r.pct[k] != null ? `±${Math.round(r.pct[k])}%` : "");
  const row = (label, val, sub) => `<div><dt>${label}</dt><dd><b>${val}</b>${sub ? `<small>${sub}</small>` : ""}</dd></div>`;
  const depthSub = d.source === "typed" ? "<span>typed</span>" : d.source === "3d_rescaled" ? `<span>3D × k</span> ${esc(d.k.toFixed(2))}` : "";
  const rows = [
    row("Width × length", `${esc(m.width_m.toFixed(2))} × ${esc(m.length_m.toFixed(2))} m`,
      `${esc(rangeTxt(rg.width_m[0], rg.width_m[1], (v) => v.toFixed(2)))} × ${esc(rangeTxt(rg.length_m[0], rg.length_m[1], (v) => v.toFixed(2)))}`),
    row("Area", `${esc(m2(m.area_m2))} m²`, `${esc(pct("area_m2"))} (${esc(rangeTxt(rg.area_m2[0], rg.area_m2[1], m2))})`),
    row("Perimeter", `${esc(m.perimeter_m.toFixed(2))} m`, esc(pct("perimeter_m"))),
    m.depth_max_m != null ? row("Depth", `${esc(cm(m.depth_max_m))} cm`, depthSub) : row("Depth", "–", "<span>needed for the cost</span>"),
    m.volume_m3 != null ? row("Volume", `${esc(Math.round(m.volume_m3 * 1000))} L`, d.volume_range ? `${esc(rangeTxt(d.volume_range[0] * 1000, d.volume_range[1] * 1000, (v) => Math.round(v)))} L` : "") : "",
  ].join("");
  const warns = [...r.warnings, ...(d.error ? [d.error] : [])];
  const bill = b.available
    ? `<div class="ms-bill"><p class="ms-bill-h"><span>Materials</span><b>${esc(moneyFmt(b.subtotal, b.symbol))}</b></p>
        <p class="ms-note">${esc(b.method_label)}</p>
        <ul>${b.lines.map((l) => `<li><span>${esc(l.label)}${l.label_th ? ` <small lang="th">${esc(l.label_th)}</small>` : ""}</span><span>${esc(l.qty)} <span>${esc(l.unit)}</span></span></li>`).join("")}</ul>
        <p class="ms-note"><span>Cut</span> ${esc(b.cut_w_m)} × ${esc(b.cut_l_m)} m, <span>30 cm past the damage (DOH)</span></p></div>`
    : `<div class="ms-bill none"><p class="ms-note">${esc(b.reason)}</p></div>`;
  return `<h3>Result <span class="muted">${esc(r.ref.label)}, ±${esc(r.tol_px)} px taps</span></h3>
    <dl class="ms-res">${rows}</dl>
    <p class="ms-note">Ranges are the 10th to 90th percentile when every tapped point is off by up to ${esc(r.tol_px)} pixels.</p>
    ${warns.length ? `<ul class="ms-warn">${warns.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    ${bill}`;
}

function hint() {
  const h = dlg.querySelector(".ms-hint");
  const st = step(), r = curRef();
  let t;
  if (st === 1) t = r.kind === "line" ? "Type the length between the two marks" : "Type the size of your rectangle";
  else if (st === 2) t = isLine() ? `Tap the two ends of the known length (${S.refPts.length} of 2)` : `Tap the 4 corners of the ${r.label} (${S.refPts.length} of 4)`;
  else if (st === 3) t = `Tap round the edge of the hole (${S.outline.length} points)`;
  else if (S.error) t = S.error;
  else if (S.result) {
    const m = S.result.metrics, p = S.result.result.pct.area_m2;
    t = `${m.width_m.toFixed(2)} × ${m.length_m.toFixed(2)} m · ${m2(m.area_m2)} m² ±${Math.round(p)}%`;
  } else t = "Measuring…";
  h.textContent = t;
}

// ------------------------------------------------------------------------------------------- drawing
function fit(keep = false) {
  const sc = dlg.querySelector(".ms-scroll");
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
  S.scale = S.fitS * ZOOMS[S.zoom];
  const cv = dlg.querySelector(".ms-canvas");
  cv.style.width = `${S.natW * S.scale}px`;
  cv.style.height = `${S.natH * S.scale}px`;
  cv.classList.toggle("zoomed", S.zoom > 0);
  dlg.querySelector(".ms-zv").textContent = `${Math.round(ZOOMS[S.zoom] * 100)}%`;
  sc.scrollLeft = cx * S.scale - sc.clientWidth / 2;
  sc.scrollTop = cy * S.scale - sc.clientHeight / 2;
  draw();
}

/** The same order the server uses: around the centre, starting at the top-left corner. */
function orderQuad(p) {
  const c = [p.reduce((a, q) => a + q[0], 0) / p.length, p.reduce((a, q) => a + q[1], 0) / p.length];
  const q = p.map((x, i) => ({ x, i, a: Math.atan2(x[1] - c[1], x[0] - c[0]) })).sort((a, b) => a.a - b.a);
  let s = 0;
  q.forEach((v, k) => { if (v.x[0] + v.x[1] < q[s].x[0] + q[s].x[1]) s = k; });
  return [...q.slice(s), ...q.slice(0, s)].map((v) => v.x);
}

function draw() {
  const svg = dlg.querySelector(".ms-svg");
  const k = 1 / S.scale;                       // natural pixels per screen pixel
  const r = curRef();
  let out = "";
  const pts = (a) => a.map((p) => `${p[0]},${p[1]}`).join(" ");
  const label = (x, y, text) => `<text x="${x}" y="${y}" font-size="${13 * k}" stroke-width="${3 * k}">${esc(text)}</text>`;
  if (S.useBox && S.opts.box) {
    const b = S.opts.box;
    out += `<rect class="ms-box" x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}"/>`;
  }
  if (S.outline.length) {
    out += S.outline.length >= 3 ? `<polygon class="ms-hole" points="${pts(S.outline)}"/>` : `<polyline class="ms-hole open" points="${pts(S.outline)}"/>`;
  }
  if (S.refPts.length === 4 && !isLine()) {
    const q = orderQuad(S.refPts);
    out += `<polygon class="ms-ref-shape" points="${pts(q)}"/>`;
    const fe = S.result?.result?.ref?.first_edge;
    if (fe && refReady()) {
      const w = r.custom ? Math.min(+S.customW, +S.customL) / 100 : r.width_m, l = r.custom ? Math.max(+S.customW, +S.customL) / 100 : r.length_m;
      const a = fe === "width" ? w : l, b = fe === "width" ? l : w;
      [[0, 1, a], [1, 2, b], [2, 3, a], [3, 0, b]].forEach(([i, j, v]) => {
        out += label((q[i][0] + q[j][0]) / 2, (q[i][1] + q[j][1]) / 2, `${cm(v)} cm`);
      });
    }
  } else if (S.refPts.length >= 2) {
    out += `<polyline class="ms-ref-shape open" points="${pts(S.refPts)}"/>`;
    if (isLine() && Number(S.rulerL) > 0) out += label((S.refPts[0][0] + S.refPts[1][0]) / 2, (S.refPts[0][1] + S.refPts[1][1]) / 2, `${S.rulerL} cm`);
  }
  const hitR = matchMedia("(pointer: coarse)").matches ? 20 : 11;
  const handle = (p, set, i) => `<g class="ms-h ${set}" data-set="${set}" data-i="${i}"><circle class="hit" cx="${p[0]}" cy="${p[1]}" r="${hitR * k}"/><circle class="dot" cx="${p[0]}" cy="${p[1]}" r="${7 * k}" stroke-width="${2.5 * k}"/></g>`;
  out += S.refPts.map((p, i) => handle(p, "ref", i)).join("");
  out += S.outline.map((p, i) => handle(p, "out", i)).join("");
  svg.innerHTML = out;
  svg.style.setProperty("--k", k);
}

// ------------------------------------------------------------------------------------------- pointer
function toImage(e) {
  const rc = dlg.querySelector(".ms-canvas").getBoundingClientRect();
  const x = (e.clientX - rc.left) / S.scale, y = (e.clientY - rc.top) / S.scale;
  return [Math.round(Math.max(0, Math.min(S.natW, x)) * 10) / 10, Math.round(Math.max(0, Math.min(S.natH, y)) * 10) / 10];
}

function loupe(e, p) {
  const el = dlg.querySelector(".ms-loupe");
  if (!p) { el.hidden = true; return; }
  const mag = Math.min(8, Math.max(S.scale * 4, 2));
  el.hidden = false;
  el.style.backgroundImage = `url("${S.opts.image}")`;
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
  const zoomedTouch = e.pointerType === "touch" && S.zoom > 0;
  if (h) {
    e.preventDefault();  // a handle moves once the pointer travels 4 px; a still press adds a point instead
    S.drag = { set: h.dataset.set, i: +h.dataset.i, id: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
  } else if (zoomedTouch) {
    S.drag = { tap: true, id: e.pointerId, x: e.clientX, y: e.clientY };  // the page may scroll; a still tap adds a point
    return;
  } else {
    if (!refReady()) { S.error = ""; hint(); return; }
    if (S.useBox && S.refPts.length === needPts()) return;
    e.preventDefault();
    S.drag = { add: true, id: e.pointerId, p: toImage(e) };
  }
  try { cv.setPointerCapture?.(e.pointerId); } catch { /* a pointer the browser no longer tracks */ }
  onMove(e);
}

function onMove(e) {
  const d = S?.drag;
  if (!d || d.id !== e.pointerId || d.tap) return;
  if (d.set && !d.moved) {
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) return;
    d.moved = true;
  }
  const p = toImage(e);
  if (d.add) d.p = p;
  else (d.set === "ref" ? S.refPts : S.outline)[d.i] = p;
  loupe(e, p);
  if (!d.add) { draw(); schedule(250); }
}

function onUp(e) {
  const d = S?.drag;
  if (!d || d.id !== e.pointerId) return;
  S.drag = null;
  loupe(e, null);
  if (d.tap) {
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 8 || !refReady()) return;
    addPoint(toImage(e));
  } else if (d.add) addPoint(d.p);
  else if (!d.moved) { if (refReady() && !(S.useBox && S.refPts.length === needPts())) addPoint(toImage(e)); }
  else { draw(); schedule(0); }
}

function onCancel(e) {
  if (S?.drag?.id === e.pointerId) { S.drag = null; loupe(e, null); draw(); }
}

function addPoint(p) {
  if (S.refPts.length < needPts()) S.refPts.push(p);
  else if (!S.useBox) S.outline.push(p);
  else return;
  draw();
  renderPanel();
  schedule(0);
}

// ------------------------------------------------------------------------------------------- preview / save
function payload() {
  const r = curRef();
  const b = {
    image_w: S.natW, image_h: S.natH, ref_type: r.id, ref_points: S.refPts, first_edge: S.firstEdge, tol_px: 3,
    depth_cm: null, rescale_3d: false, target: S.target, image: S.opts.imageRef || null,
  };
  if (r.kind === "line") b.ref_length_cm = Number(S.rulerL);
  else if (r.custom) { b.ref_width_cm = Number(S.customW); b.ref_length_cm = Number(S.customL); }
  if (S.useBox) b.box = S.opts.box; else b.outline = S.outline;
  const three = S.result?.three_d;
  if ((S.depthMode || "typed") === "rescale" && three) b.rescale_3d = true;
  else if (Number(S.depthCm) > 0) b.depth_cm = Number(S.depthCm);
  return b;
}

function schedule(ms) {
  clearTimeout(previewTimer);
  if (!S) return;
  if (!ready()) { S.result = null; S.error = ""; updateLive(); return; }
  previewTimer = setTimeout(preview, ms);
}

async function preview() {
  const seq = ++previewSeq;
  try {
    const j = await api("/api/measure/preview", { method: "POST", body: JSON.stringify(payload()) });
    if (!S || seq !== previewSeq) return;
    const hadThree = !!S.result?.three_d, first = !S.result;
    S.result = j; S.error = "";
    if (first) requestAnimationFrame(() => dlg?.querySelector(".ms-out")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    if (!hadThree && j.three_d) {           // the depth section gains "Rescale the 3D depth"
      if (S.depthMode === null && !(Number(S.depthCm) > 0)) { S.depthMode = "rescale"; renderPanel(); draw(); return schedule(0); }
      renderPanel();
    }
  } catch (e) {
    if (!S || seq !== previewSeq) return;
    S.error = e.message;
  }
  updateLive();
  draw();
}

async function save() {
  if (!S.target && S.opts.onSelect && S.result?.result) {
    const out = S.result, cb = S.opts.onSelect;
    dlg.close();
    cb(out);
    return;
  }
  if (!S.target || S.busy) return;
  S.busy = true;
  const btn = dlg.querySelector('[data-ms="save"]');
  if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
  try {
    const out = await api(measureUrl(S.target), { method: "POST", body: JSON.stringify(payload()) });
    const { toast, onSaved } = S.opts;
    const label = S.result.result.ref.label;
    dlg.close();
    toast?.(`Measured with ${label}. Saved.`);
    onSaved?.(out);
  } catch (e) {
    S.busy = false;
    S.error = e.message;
    renderPanel();
  }
}

// ------------------------------------------------------------------------------------------- events
function onClick(e) {
  if (e.target === dlg) return;
  const b = e.target.closest("[data-ms]");
  if (!b || !S) return;
  const a = b.dataset.ms;
  if (a === "close") return dlg.close();
  if (a === "zin") return setZoom(1);
  if (a === "zout") return setZoom(-1);
  if (a === "save") return save();
  if (a === "undo-ref") S.refPts.pop();
  if (a === "clear-ref") { S.refPts = []; S.firstEdge = null; }
  if (a === "undo-out") S.outline.pop();
  if (a === "clear-out") { S.outline = []; S.useBox = false; }
  if (a === "refs") S.showRefs = !S.showRefs;
  if (a === "box") { S.useBox = !S.useBox; if (S.useBox) S.outline = []; }
  if (a === "swap") {
    const cur = S.result?.result?.ref?.first_edge || "width";
    S.firstEdge = cur === "width" ? "length" : "width";
  }
  if (!ready()) S.result = null;
  renderPanel();
  draw();
  schedule(0);
}

function onInput(e) {
  const t = e.target;
  if (!S) return;
  if (t.name === "ms-ref" && e.type === "change") {
    const was = curRef().kind;
    S.ref = t.value;
    S.firstEdge = null;
    if (curRef().kind !== was) S.refPts = [];
    S.result = null;
    renderPanel(); draw(); schedule(0);
    return;
  }
  if (t.name === "ms-dm" && e.type === "change") { S.depthMode = t.value; renderPanel(); schedule(0); return; }
  const k = t.dataset.k;
  if (!k) return;
  if (k === "target") { if (e.type === "change") { S.target = S.opts.targets[+t.value].target; S.result = null; schedule(0); } return; }
  if (e.type !== "input") return;
  S[k] = t.value;
  if (k !== "depthCm") S.firstEdge = null;
  if (k === "depthCm" && Number(t.value) > 0) S.depthMode = "typed";
  draw();
  updateLive();
  schedule(300);
}

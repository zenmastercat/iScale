import { createMap } from "./map.js";
import { createViewer } from "./viewer.js";
import * as session from "./session.js";
import { Messenger, chatView, mapsUrl } from "./chat.js";
import { renderSettings } from "./settings.js";
import { adminSteps, progress, getStartedHtml, wireGetStarted, maybeWelcome } from "./onboarding.js";
import { openJobCard, moneyFmt } from "./jobcard.js";
import * as loc from "./location.js";
import { mountCheck } from "./check3d.js";
import { openRecorder } from "./recorder.js";
import { openMeasure, startMeasure } from "./measure.js";
import { openSceneScale } from "./scene_scale.js";
import { createProjectWizard } from "./project_wizard.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const state = {
  meta: null, catalog: {}, projects: [], project: null, surveys: [], sid: null,
  analysis: null, workorders: [], verification: null, view: "map",
  highlight: [], highlightSegs: [], selected: new Set(), plan: null, planMode: "spot", planTotal: null,
  sort: { key: "severity", dir: 1 }, pointsFor: null,
  user: null, messenger: null, chatUi: null, pins: [], pendingShare: null, pinMode: false,
};

// ---------------------------------------------------------------- helpers
async function api(path, opts = {}) {
  const headers = { "X-Civil-Scan": "1", ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401 && !path.startsWith("/api/auth/")) {
    location.reload(); // session ended (signed out elsewhere, or the admin reset this device)
    throw new Error("signed out");
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}
let toastTimer = 0;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", err);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), err ? 7000 : 3500);
}
const money = (x, cur = state.meta?.currency || "USD") =>
  `${cur} ${Number(x || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const label = (t) => state.catalog[t]?.label || t;
const kindOf = (t) => state.catalog[t]?.kind || "asset";
const SEV_RANK = { high: 0, medium: 1, low: 2, "": 3 };
const STATE_LABEL = { open: "Open", planned: "Planned", fixed: "Fixed", verified: "Verified", not_fixed: "Not fixed",
  dismissed: "Dismissed", not_covered: "Not covered", scheduled: "Scheduled", completed: "Completed",
  partially_verified: "Partly verified", cancelled: "Cancelled", queued: "Queued", running: "Processing", done: "Ready", error: "Failed" };
const stateTag = (s) => `<span class="state ${esc(s)}">${esc(STATE_LABEL[s] || s)}</span>`;
const sevTag = (s) => (s ? `<span class="sev ${esc(s)}">${esc(s[0].toUpperCase() + s.slice(1))}</span>` : `<span class="sev">Asset</span>`);
const METRIC_LABEL = {
  area_m2: ["Area", "m²"], depth_max_m: ["Deepest point", "m"], depth_median_m: ["Typical depth", "m"], volume_m3: ["Volume", "m³"],
  diameter_m: ["Width", "m"], width_m: ["Width", "m"], length_m: ["Length", "m"], perimeter_m: ["Perimeter", "m"], circularity: ["Roundness", ""], flat_share: ["Flat floor share", ""], bowl: ["Bowl curvature", ""],
  height_max_m: ["Height", "m"], texture_std_mm: ["Texture deviation", "mm"], step_m: ["Step", "m"], direction: ["Direction", ""],
  height_m: ["Height", "m"], trunk_width_m: ["Post width", "m"], top_span_m: ["Reach at top", "m"], canopy_m: ["Canopy", "m"],
  plate_points: ["Plate points", ""], points: ["3D points", ""], detector_points: ["Detector points", ""],
};
const fmtNum = (v) => (typeof v === "number" ? (Math.abs(v) < 10 ? v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : v.toFixed(1)) : esc(v));
const chainage = (m) => `${Math.floor(m / 1000)}+${String(Math.round(m % 1000)).padStart(3, "0")}`;
// materials-only repair cost; a click opens the full job card
const costChip = (c, attrs = "") => (c
  ? `<button class="cost-chip" type="button" ${attrs} title="Materials only, no labour. Open the full job card">${esc(moneyFmt(c.materials_cost, c.symbol))}<small>materials${c.missing_prices ? "*" : ""}</small></button>`
  : "");
// "Scaled by: lane width ×2, ±4%" / "Scale: camera height guess": where a 3D-measured size comes from (static/scene_scale.js)
const scaledTag = (f) => (f.scaled_by ? `<span class="scl-tag ${f.scaled_by.startsWith("Scaled by") ? "scene" : "guess"}" title="${esc(f.scaled_by)}">${esc(f.scaled_by.startsWith("Scaled by") ? "scene scale" : "scale guessed")}</span>` : "");
// "measured with A4 sheet ±4%": a reference-object measurement (static/measure.js)
const measuredText = (m) => (m ? `Size measured with ${m.ref}${m.pct != null ? ` ±${Math.round(m.pct)}%` : ""}` : "");
const measuredTag = (m) => (m ? `<span class="meas-tag" title="${esc(measuredText(m))} (10th to 90th percentile)">${esc(m.ref)}${m.pct != null ? ` ±${esc(Math.round(m.pct))}%` : ""}</span>` : "");
const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

function md(text) {
  // small, safe markdown: escape first, then **bold**, `code`, _italic_, "- " lists
  const lines = esc(text).split("\n");
  let html = "", inList = false;
  for (const raw of lines) {
    const l = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>");
    if (/^- /.test(raw)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${l.slice(2)}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (l.trim()) html += `<p>${l}</p>`;
    }
  }
  return html + (inList ? "</ul>" : "");
}

// ---------------------------------------------------------------- map + viewer
const mapApi = createMap($("#map"), {
  onSelect: (id) => openDrawer(id), onSegment: (id) => setHighlight([], [id]),
  onPin: (id) => openPin(id), onMapClick: (lat, lon) => placePin(lat, lon),
});
const viewer = createViewer($("#viewer"), { onSelect: (id) => openDrawer(id), onTag: tagAt });

// ---------------------------------------------------------------- views
const VIEWS = ["map", "scan", "inventory", "plan", "verify", "video", "messages", "settings", "create"];
let projectWizard = null;
function openProjectWizard() {
  projectWizard ??= createProjectWizard($("#view-create"), {
    api, toast, loc, openMeasure,
    onCreated: async (pid, { openVideo } = {}) => {
      await loadProjects(pid);
      setView(openVideo ? "video" : "map");
    },
    onCancel: () => setView("map"),
  });
  return projectWizard.open();
}
function setView(v) {
  if (!VIEWS.includes(v)) v = "map";
  state.view = v;
  if (location.hash.slice(1) !== v) history.replaceState(null, "", `#${v}`);
  for (const t of $$(".tab")) {
    if (t.dataset.view === v) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  }
  for (const s of $$(".view")) s.toggleAttribute("data-active", s.id === `view-${v}`);
  viewer.setActive(v === "scan");
  if (v === "map") requestAnimationFrame(() => { mapApi.resize(); if (state.analysis && !state.highlight.length) mapApi.fit(); });
  if (v === "scan") ensurePoints();
  if (v === "plan") loadPlan();
  if (v === "verify") renderVerifyControls();
  if (v === "video") renderVideo();
  if (v === "create") openProjectWizard();
  if (v === "settings" && state.user) {
    renderSettings($("#view-settings"), state.user, toast)
      .then(() => showGetStarted())
      .catch((e) => toast(e.message, true));
  }
}

// ---------------------------------------------------------------- onboarding
$("#view-settings").addEventListener("settings:rendered", () => showGetStarted());
async function showGetStarted() {
  if (state.user?.role !== "admin") return;
  const steps = await adminSteps(state.user?.account);
  const root = $("#view-settings");
  root.querySelector(".getstarted")?.remove();
  root.querySelector(".page-head")?.insertAdjacentHTML("afterend", getStartedHtml(steps));
  wireGetStarted(root, steps, goTo);
  setupBadge(steps);
}

function setupBadge(steps) {
  const b = $("#setupLeft");
  if (!b) return;
  const p = progress(steps);
  b.hidden = p.done >= p.total;
  b.textContent = `${p.total - p.done}`;
  b.title = `${p.total - p.done} setup steps left`;
}

/* Switch to a view and put the cursor where the next step happens. */
function goTo(view, focusSel) {
  if (view === "helper") {
    const app = $("#app");
    app.classList.remove("chat-hidden");
    if (matchMedia("(max-width: 1100px)").matches) app.classList.add("chat-open");
    $("#chatInput").focus();
    return;
  }
  setView(view);
  if (!focusSel) return;
  const t0 = performance.now();
  (function find() {
    const el = document.querySelector(focusSel);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.focus({ preventScroll: true }); return; }
    if (performance.now() - t0 < 2000) requestAnimationFrame(find);
  })();
}
for (const t of $$(".tab[data-view]")) t.addEventListener("click", () => setView(t.dataset.view));

// ---------------------------------------------------------------- projects & surveys
const isVideoJob = (s) => s && (s.decoder === "pothole_video" || s.kind === "video");

async function loadProjects(selectId) {
  state.projects = await api("/api/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = state.projects.length
    ? state.projects.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")
    : `<option value="">No projects yet</option>`;
  const id = selectId || state.project?.id || state.projects[0]?.id;
  if (id) { sel.value = id; await selectProject(id); }
  else renderEmpty();
}

async function selectProject(pid) {
  state.project = await api(`/api/projects/${pid}`);
  state.surveys = state.project.survey_list;
  state.workorders = await api(`/api/projects/${pid}/workorders`);
  state.verification = await api(`/api/projects/${pid}/verification`);
  renderSurveySelect();
  const done = state.surveys.filter((s) => s.status === "done" && !isVideoJob(s));
  const sid = state.surveys.find((s) => s.id === state.sid)?.id || state.project.baseline || done[0]?.id || state.surveys[0]?.id;
  await selectSurvey(sid);
  poll();
}

function surveyLabel(s) {
  let t = s.name;
  if (isVideoJob(s)) t += " (video)";
  if (s.id === state.project.baseline) t += ", baseline";
  if (s.status !== "done") t += `, ${(STATE_LABEL[s.status] || s.status).toLowerCase()}`;
  return t;
}
function renderSurveySelect() {
  const sel = $("#surveySelect");
  sel.innerHTML = state.surveys.length
    ? state.surveys.map((s) => `<option value="${esc(s.id)}">${esc(surveyLabel(s))}</option>`).join("")
    : `<option value="">No surveys yet</option>`;
  if (state.sid) sel.value = state.sid;
}

async function selectSurvey(sid) {
  state.sid = sid || null;
  state.analysis = null;
  state.planTotal = null;
  state.selected.clear();
  state.highlight = []; state.highlightSegs = [];
  $("#surveySelect").value = sid || "";
  closeDrawer();
  const sv = state.surveys.find((s) => s.id === sid);
  renderStatus(sv);
  if (sv && sv.status === "done" && !isVideoJob(sv)) {
    state.analysis = await api(`/api/projects/${state.project.id}/surveys/${sid}/analysis`);
    mapApi.setData(state.analysis, state.catalog, true);
  } else {
    mapApi.clear();
  }
  state.pointsFor = null;
  viewer.clear();
  renderAll();
  if (isVideoJob(sv) && state.view !== "video") setView("video");
  if (state.view === "scan") ensurePoints();
  renderScaleTools();
}

function renderStatus(sv) {
  const el = $("#surveyStatus");
  if (!sv || sv.status === "done") { el.hidden = true; return; }
  el.hidden = false;
  el.className = "status" + (sv.status === "error" ? " err" : "");
  el.textContent = sv.status === "error" ? `Failed: ${sv.error}` : `${sv.stage || "Queued"}…`;
  el.title = sv.error || "";
}

let pollTimer = 0;
function poll() {
  clearTimeout(pollTimer);
  if (!state.project) return;
  if (!state.surveys.some((s) => ["queued", "running"].includes(s.status))) return;
  pollTimer = setTimeout(async () => {
    try {
      const proj = await api(`/api/projects/${state.project.id}`);
      const before = Object.fromEntries(state.surveys.map((s) => [s.id, s.status]));
      state.project = proj;
      state.surveys = proj.survey_list;
      renderSurveySelect();
      const cur = state.surveys.find((s) => s.id === state.sid);
      renderStatus(cur);
      const finished = state.surveys.filter((s) => s.status !== before[s.id] && ["done", "error"].includes(s.status));
      for (const s of finished) {
        if (s.status === "error") toast(`${s.name} failed: ${s.error}`, true);
        else if (isVideoJob(s)) toast(`${s.name}: ${s.stats.detections} detections, ${s.stats.windows} clips`);
        else toast(`${s.name} is ready: ${s.stats.findings} findings`);
      }
      if (cur && finished.some((s) => s.id === cur.id)) await selectSurvey(cur.id);
      else if (!state.analysis && proj.baseline && state.surveys.find((s) => s.id === proj.baseline)?.status === "done" && !isVideoJob(cur)) await selectSurvey(proj.baseline);
      if (state.view === "video") renderVideo();
    } catch { /* transient */ }
    poll();
  }, 1500);
}

$("#projectSelect").addEventListener("change", (e) => e.target.value && selectProject(e.target.value));
$("#surveySelect").addEventListener("change", (e) => selectSurvey(e.target.value));

$("#demoBtn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const p = await api("/api/demo", { method: "POST" });
    toast("Building the demo street. It takes about 20 seconds.");
    await loadProjects(p.id);
  } catch (err) { toast(err.message, true); }
  btn.disabled = false;
});

// ---------------------------------------------------------------- render
function renderEmpty() {
  $("#summary").innerHTML = `Load the demo street or create a project to begin. <button class="btn small primary inline-cta" type="button" data-open-wizard>Create project</button>`;
  $("#strip").innerHTML = "";
  $("#legend").innerHTML = "";
  $("#invTable").innerHTML = `<tbody><tr><td class="empty">Create a project or load the demo street to begin. <button class="btn small primary inline-cta" type="button" data-open-wizard>Create project</button></td></tr></tbody>`;
}
$(".stage").addEventListener("click", (e) => {
  if (e.target.closest("[data-open-wizard]")) setView("create");
});

function renderAll() {
  renderSummary();
  renderStrip();
  renderLegend();
  renderInventory();
  renderWorkorders();
  if (state.view === "plan") loadPlan();
  if (state.view === "verify") renderVerifyControls();
  if (state.view === "video") renderVideo();
  const a = state.analysis;
  if (a) viewer.setFindings(a.findings, state.catalog);
  $("#exportCsv").href = state.sid ? `/api/projects/${state.project.id}/surveys/${state.sid}/export.csv` : "#";
  $("#exportGeo").href = state.sid ? `/api/projects/${state.project.id}/surveys/${state.sid}/export.geojson` : "#";
  const sv3 = state.surveys.find((s) => s.id === state.sid);
  const has3d = !!(sv3 && sv3.status === "done" && !isVideoJob(sv3));
  $("#exportPly").hidden = !has3d;
  $("#exportPly").href = has3d ? `/api/projects/${state.project.id}/surveys/${state.sid}/export.ply` : "#";
}

function renderSummary() {
  const a = state.analysis;
  const el = $("#summary");
  const sv = state.surveys.find((s) => s.id === state.sid);
  if (!a) {
    el.textContent = isVideoJob(sv) ? "This is a video job. Its 3D clips are listed under Video and in the survey menu."
      : sv ? "This survey is still being processed." : "Load the demo street or add a survey to begin.";
    return;
  }
  const scored = a.segments.filter((s) => s.condition != null);
  const len = scored.reduce((t, s) => t + s.length_m, 0);
  const avg = len ? scored.reduce((t, s) => t + s.condition * s.length_m, 0) / len : 0;
  const defects = a.findings.filter((f) => kindOf(f.type) === "defect" && !["verified", "dismissed"].includes(f.status));
  const high = defects.filter((f) => f.severity === "high").length;
  const assets = a.findings.filter((f) => kindOf(f.type) === "asset").length;
  const cost = state.planTotal != null ? `, and fixing them is estimated at <b>${esc(money(state.planTotal))}</b>` : "";
  el.innerHTML = `<b>${len.toFixed(0)} m</b> of road scored <b>${avg.toFixed(0)} out of 100</b>. ` +
    `There are <b>${defects.length}</b> open defects, <b>${high}</b> of them high severity${cost}. ${assets} assets are on record.`;
  if (state.planTotal == null && state.sid) {
    api(`/api/projects/${state.project.id}/surveys/${state.sid}/plan`).then((p) => { state.planTotal = p.total; renderSummary(); }).catch(() => {});
  }
}

function renderStrip() {
  // straight-line diagram: each segment along the drive, coloured by condition, with defect ticks
  const a = state.analysis;
  const el = $("#strip");
  if (!a || !a.segments.length) { el.innerHTML = ""; return; }
  const total = a.segments[a.segments.length - 1].s1 || 1;
  const segs = a.segments.map((s) => `<div class="strip-seg${state.highlightSegs.includes(s.id) ? " hl" : ""}" data-seg="${esc(s.id)}"
      style="width:${((s.length_m / total) * 100).toFixed(3)}%;background:${esc(s.color)}"
      title="Segment ${esc(s.id)}, ${chainage(s.s0)} to ${chainage(s.s1)}: condition ${s.condition ?? "not scored"}, ${esc(s.rating)}"></div>`).join("");
  // place each defect at its segment's position (by distance from the segment's start line)
  const ticks = a.findings.filter((f) => kindOf(f.type) === "defect" && f.status !== "dismissed").map((f) => {
    const s = a.segments.find((x) => x.id === f.segment_id);
    if (!s) return "";
    const line = s.coords || [];
    let frac = 0.5;
    if (line.length > 1) {
      let best = 1e9, bi = 0;
      line.forEach((c, i) => { const d = (c[0] - f.lon) ** 2 + (c[1] - f.lat) ** 2; if (d < best) { best = d; bi = i; } });
      frac = bi / (line.length - 1);
    }
    const m = s.s0 + frac * s.length_m;
    return `<span class="strip-tick ${f.severity === "high" ? "high" : ""}" style="left:${((m / total) * 100).toFixed(3)}%" title="${esc(label(f.type))} ${esc(f.id)}"></span>`;
  }).join("");
  const marks = [0, total / 2, total].map((m, i) => `<span class="strip-ch${i === 0 ? " start" : i === 2 ? " end" : ""}" style="left:${((m / total) * 100).toFixed(2)}%">${chainage(m)}</span>`).join("");
  el.innerHTML = `${ticks}<div class="strip-bar">${segs}</div>${marks}`;
}
$("#strip").addEventListener("click", (e) => {
  const s = e.target.closest("[data-seg]");
  if (!s) return;
  const ids = state.analysis.findings.filter((f) => f.segment_id === s.dataset.seg && kindOf(f.type) === "defect").map((f) => f.id);
  setHighlight(ids, [s.dataset.seg]);
  mapApi.fit(ids.length ? ids : null);
});

function renderLegend() {
  if (!state.analysis) { $("#legend").innerHTML = ""; return; }
  const bands = ["#8e2a35", "#D94B4B", "#E99B37", "#e6c54f", "#8cc084", "#329B76"];
  $("#legend").innerHTML =
    `<div>Condition of each segment</div>
     <div class="legend-scale">${bands.map((c) => `<span style="background:${c}"></span>`).join("")}</div>
     <div class="legend-ticks"><span>0 failed</span><span>55 fair</span><span>100 good</span></div>
     <div class="legend-dots"><span><span class="dot" style="background:var(--high)"></span>High</span><span><span class="dot" style="background:var(--medium)"></span>Medium</span><span><span class="dot" style="background:var(--low)"></span>Low</span><span><span class="dot" style="background:var(--asset)"></span>Asset</span></div>`;
}

// ---------------------------------------------------------------- inventory
function filteredFindings() {
  const a = state.analysis;
  if (!a) return [];
  const q = $("#invSearch").value.trim().toLowerCase();
  const kind = $("#invKind").value, sev = $("#invSeverity").value, st = $("#invStatus").value;
  let rows = a.findings.filter((f) =>
    (!kind || kindOf(f.type) === kind) && (!sev || f.severity === sev) && (!st || f.status === st) &&
    (!q || `${f.id} ${f.type} ${label(f.type)} ${f.segment_id} ${f.evidence}`.toLowerCase().includes(q)));
  if (state.highlight.length) {
    const h = new Set(state.highlight);
    rows = rows.filter((f) => h.has(f.id));
  }
  const { key, dir } = state.sort;
  const val = (f) => (key === "severity" ? SEV_RANK[f.severity || ""] : key === "type" ? label(f.type) : key === "cost" ? -(f.cost?.materials_cost ?? -1) : f[key] ?? "");
  rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : a.id.localeCompare(b.id)) * dir);
  return rows;
}

function updateWoButton() {
  const b = $("#invMakeWo");
  b.disabled = state.selected.size === 0;
  b.textContent = state.selected.size ? `Create work order for ${state.selected.size}` : "Create work order";
}

function renderInventory() {
  const rows = filteredFindings();
  const t = $("#invTable");
  if (!state.analysis) { t.innerHTML = `<tbody><tr><td class="empty">Choose a processed survey to see its inventory.</td></tr></tbody>`; return; }
  const head = [["", ""], ["type", "Item"], ["severity", "Severity"], ["status", "Status"], ["cost", "Materials"], ["segment_id", "Segment"], ["", "Why it was flagged"], ["id", "ID"]];
  t.innerHTML = `<thead><tr>${head.map(([k, l]) => `<th ${k ? `data-sort="${k}"` : ""}>${l}${state.sort.key === k ? (state.sort.dir > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}</tr></thead>
  <tbody>${rows.length ? rows.map((f) => `<tr data-id="${esc(f.id)}" class="${state.selected.has(f.id) ? "sel" : ""}">
    <td><input type="checkbox" aria-label="Select ${esc(f.id)}" ${state.selected.has(f.id) ? "checked" : ""} ${kindOf(f.type) === "defect" ? "" : "disabled"}></td>
    <td>${esc(label(f.type))}</td><td>${sevTag(f.severity)}</td><td>${stateTag(f.status)}</td>
    <td class="num">${costChip(f.cost, `data-card="${esc(f.id)}"`)}${measuredTag(f.measured)}${scaledTag(f)}</td><td>${esc(f.segment_id || "")}</td><td class="ev">${esc(f.evidence)}</td><td class="id">${esc(f.id)}</td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">Nothing matches these filters.</td></tr>`}</tbody>`;
  updateWoButton();
}
$("#invTable").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]");
  if (th) {
    const k = th.dataset.sort;
    state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : 1 };
    return renderInventory();
  }
  const cc = e.target.closest("[data-card]");
  if (cc) return findingCard(cc.dataset.card);
  const tr = e.target.closest("tr[data-id]");
  if (!tr) return;
  if (e.target.matches("input[type=checkbox]")) {
    e.target.checked ? state.selected.add(tr.dataset.id) : state.selected.delete(tr.dataset.id);
    tr.classList.toggle("sel", e.target.checked);
    return updateWoButton();
  }
  openDrawer(tr.dataset.id);
});
for (const id of ["#invSearch", "#invKind", "#invSeverity", "#invStatus"]) $(id).addEventListener("input", renderInventory);
$("#invMakeWo").addEventListener("click", () => createWorkOrder([...state.selected]));

// ---------------------------------------------------------------- job card
function showCard(ref) {
  openJobCard(ref, {
    toast, canEdit: state.user?.role === "admin",
    onChanged: () => { loadPins(); if (state.analysis && ref.kind === "finding" && ref.survey === state.sid) refreshAnalysis().catch(() => {}); },
    onAction: async (a, c) => {
      if (a === "ask") {
        const b = c.cost.available ? `${c.cost.area_m2} m², ${Math.round(c.cost.depth_m * 100)} cm deep` : "size not measured";
        const road = c.timing.road ? ` on a ${c.timing.road.replace(/_/g, " ")} road` : "";
        const app = $(".app");
        if (matchMedia("(max-width: 1100px)").matches) app.classList.add("chat-open"); else app.classList.remove("chat-hidden");
        $("#chatToggle")?.setAttribute("aria-pressed", "true");
        $("#chatInput").value = `Civil Helper, how should we repair a ${c.label.toLowerCase()} (${b})${road}? Proposed method: ${c.plan.method || "not set"}.`;
        $("#chatInput").focus();
        return;
      }
      if (c.kind === "pin") {
        const p = state.pins.find((x) => x.id === c.id);
        if (a === "send" && p) shareInChat({ kind: "pin", pin: { id: p.id, label: p.label, severity: p.severity, note: p.note, lat: p.lat, lon: p.lon } });
        if (a === "map") { setView("map"); openPin(c.id); }
        return;
      }
      const f = findById(c.id);
      if (!f) return;
      if (a === "wo") createWorkOrder([f.id]);
      if (a === "send") shareInChat({ kind: "finding", finding: { id: f.id, label: label(f.type), severity: f.severity, evidence: f.evidence, lat: f.lat, lon: f.lon } });
      if (a === "map") { setView("map"); mapApi.flyTo(f); mapApi.highlight([f.id]); }
    },
  });
}
const findingCard = (id) => showCard({ kind: "finding", project: state.project.id, survey: state.sid, id });
const pinCard = (id) => showCard({ kind: "pin", id });

// ---------------------------------------------------------------- drawer
function findById(id) { return state.analysis?.findings.find((f) => f.id === id); }

function openDrawer(id) {
  const f = findById(id);
  if (!f) return;
  const d = $("#drawer");
  const metrics = Object.entries(f.metrics || {}).filter(([k]) => METRIC_LABEL[k] && !(k === "diameter_m" && f.metrics.width_m)).map(([k, v]) => {
    const [l, u] = METRIC_LABEL[k];
    if (v === null || v === undefined) return k === "depth_max_m" ? `<dt>${esc(l)}</dt><dd>not measurable (water or reflection?)</dd>` : "";
    return `<dt>${esc(l)}</dt><dd>${fmtNum(v)}${u ? " " + u : ""}</dd>`;
  }).join("");
  const isDefect = kindOf(f.type) === "defect";
  const src = { geometry: "Measured in 3D", manual: "Tagged by hand", decoder: "From the 3D decoder", detector: "Video detector only", "detector+geometry": "Video detector, measured in 3D" }[f.source] || f.source;
  d.innerHTML = `
    <button class="btn icon quiet drawer-close" aria-label="Close" type="button">✕</button>
    <h3>${esc(label(f.type))}</h3>
    <div class="sub">${sevTag(f.severity)}${stateTag(f.status)}<span>Segment ${esc(f.segment_id || "none")}</span><span>${esc(src)}</span></div>
    ${isDefect ? `<div class="row">${f.cost ? costChip(f.cost, 'data-act="card"') : ""}<button class="btn small" data-act="card" type="button">Full details</button></div>` : ""}
    <p class="ev">${esc(f.evidence)}</p>
    ${f.measured ? `<p class="ev meas">${esc(measuredText(f.measured))}${f.measured.by ? ` <span class="muted small">@${esc(f.measured.by)}</span>` : ""}</p>` : ""}
    ${f.scaled_by ? `<p class="ev scl ${f.scaled_by.startsWith("Scaled by") ? "scene" : "guess"}">${esc(f.scaled_by)}</p>` : ""}
    ${f.verification ? `<p class="ev">${stateTag(f.verification.status)}: ${esc(f.verification.evidence)}</p>` : ""}
    <dl class="meta">${metrics}<dt>Location</dt><dd>${f.lat.toFixed(6)}, ${f.lon.toFixed(6)}</dd><dt>ID</dt><dd>${esc(f.id)}</dd></dl>
    ${isDefect ? `<section class="chk" id="drawerCheck" aria-label="3D check"></section>` : ""}
    <div class="row">
      <button class="btn small" data-act="map" type="button">Show on map</button>
      <button class="btn small" data-act="scan" type="button">Show in 3D</button>
      ${isDefect && ["open", "not_fixed"].includes(f.status) ? `<button class="btn small primary" data-act="wo" type="button">Add to a work order</button>` : ""}
    </div>
    <div class="row">
      <a class="btn small quiet" href="${mapsUrl(f.lat, f.lon)}" target="_blank" rel="noopener noreferrer">Google Maps traffic</a>
      <button class="btn small quiet" data-act="send" type="button">Send to an engineer</button>
    </div>
    <div class="row">
      ${isDefect ? `<label class="field inline"><span>Severity</span><select class="input" data-act="sev">${["low", "medium", "high"].map((s) => `<option value="${s}" ${s === f.severity ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select></label>` : ""}
      ${f.status !== "dismissed" ? `<button class="btn small quiet" data-act="dismiss" type="button">Dismiss</button>` : `<button class="btn small quiet" data-act="reopen" type="button">Reopen</button>`}
    </div>`;
  d.hidden = false;
  d.dataset.id = id;
  viewer.highlight([id]);
  if (isDefect) mountCheck($("#drawerCheck"), { project: state.project.id, survey: state.sid, id }, { toast });
}
function closeDrawer() { const d = $("#drawer"); d.hidden = true; d.innerHTML = ""; viewer.highlight(state.highlight); }
$("#drawer").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act], .drawer-close");
  if (!b) return;
  if (b.classList.contains("drawer-close")) return closeDrawer();
  const id = $("#drawer").dataset.id;
  const f = findById(id);
  const act = b.dataset.act;
  if (act === "card") return findingCard(id);
  if (act === "map") { setView("map"); mapApi.flyTo(f); mapApi.highlight([id]); }
  if (act === "scan") { setView("scan"); await ensurePoints(); viewer.focus(f); }
  if (act === "wo") createWorkOrder([id]);
  if (act === "send") shareInChat({ kind: "finding", finding: { id: f.id, label: label(f.type), severity: f.severity, evidence: f.evidence, lat: f.lat, lon: f.lon } });
  if (act === "dismiss" || act === "reopen") await patchFinding(id, { status: act === "dismiss" ? "dismissed" : "open" });
});
$("#drawer").addEventListener("change", async (e) => {
  if (e.target.dataset.act === "sev") await patchFinding($("#drawer").dataset.id, { severity: e.target.value });
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });

async function patchFinding(id, body) {
  try {
    await api(`/api/projects/${state.project.id}/surveys/${state.sid}/findings/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    await refreshAnalysis();
    openDrawer(id);
  } catch (e) { toast(e.message, true); }
}
async function refreshAnalysis() {
  state.analysis = await api(`/api/projects/${state.project.id}/surveys/${state.sid}/analysis`);
  state.planTotal = null;
  mapApi.setData(state.analysis, state.catalog, false);
  mapApi.highlight(state.highlight, state.highlightSegs);
  renderAll();
}

// ---------------------------------------------------------------- 3D
async function ensurePoints() {
  const sv = state.surveys.find((s) => s.id === state.sid);
  const ok = sv && sv.status === "done" && !isVideoJob(sv);
  $("#viewerEmpty").hidden = !!ok || !!viewer.unavailable;
  if (!ok || state.pointsFor === state.sid || viewer.unavailable) return;
  state.pointsFor = state.sid;
  $("#viewerHint").textContent = "Loading the point cloud…";
  try {
    const r = await api(`/api/projects/${state.project.id}/surveys/${state.sid}/points.bin?max_points=1500000`);
    const n = +r.headers.get("X-Point-Count");
    const traj = JSON.parse(r.headers.get("X-Trajectory") || "[]");
    const labelled = r.headers.get("X-Labels") === "detector";
    const marked = +(r.headers.get("X-Detector-Points") || 0);
    const buf = await r.arrayBuffer();
    if (state.pointsFor !== sv.id) return;
    await viewer.load(buf, n, traj, labelled);
    const detBtn = $('[data-color="detector"]');
    detBtn.disabled = !labelled;
    detBtn.title = labelled ? "Points inside the pothole detector's boxes, as LingBot-Map placed them in 3D" : "This survey has no detector boxes (not from a drive video)";
    if (!labelled && detBtn.getAttribute("aria-pressed") === "true") $('[data-color="rgb"]').click();
    $("#detLegend").hidden = !labelled || detBtn.getAttribute("aria-pressed") !== "true";
    $("#detLegend").querySelector("b").textContent = marked.toLocaleString();
    if (state.analysis) viewer.setFindings(state.analysis.findings, state.catalog);
    viewer.highlight(state.highlight);
    $("#viewerHint").textContent = `${n.toLocaleString()} points`;
  } catch (e) { state.pointsFor = null; toast(e.message, true); }
}
for (const b of $$("[data-color]")) b.addEventListener("click", () => {
  for (const x of $$("[data-color]")) x.setAttribute("aria-pressed", x === b);
  $("#detLegend").hidden = b.dataset.color !== "detector";
  viewer.setColorMode(b.dataset.color);
});
$("#resetCamBtn").addEventListener("click", () => viewer.resetCamera());
$("#tagModeBtn").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", on);
  viewer.setTagging(on);
  $("#viewerHint").textContent = on ? "Click the spot you want to tag" : "Drag to orbit, right-drag to pan, scroll to zoom";
});

function tagAt(p) {
  const d = $("#drawer");
  const opts = state.meta.catalog.map((t) => `<option value="${esc(t.code)}">${esc(t.label)}${t.kind === "asset" ? " (asset)" : ""}</option>`).join("");
  d.innerHTML = `<button class="btn icon quiet drawer-close" aria-label="Close" type="button">✕</button>
    <h3>Tag an issue here</h3>
    <form id="tagForm" style="display:grid;gap:10px">
      <label class="field"><span>What is it?</span><select class="input" name="type">${opts}</select></label>
      <div class="grid2">
        <label class="field"><span>Severity</span><select class="input" name="severity"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option></select></label>
        <label class="field"><span>Size (m)</span><input class="input num" name="size" type="number" value="0.6" step="0.1" min="0.1" max="20"></label>
      </div>
      <label class="field"><span>Note</span><input class="input" name="note" maxlength="500" placeholder="Optional"></label>
      <button class="btn primary small" type="submit">Save tag</button>
    </form>`;
  d.hidden = false;
  $("#tagForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const f = await api(`/api/projects/${state.project.id}/surveys/${state.sid}/findings`, {
        method: "POST",
        body: JSON.stringify({ type: fd.get("type"), severity: fd.get("severity"), x: p.x, y: p.y, z: p.z, size_m: +fd.get("size"), note: fd.get("note") }),
      });
      toast(`Saved ${label(f.type).toLowerCase()} as ${f.id}`);
      await refreshAnalysis();
      openDrawer(f.id);
    } catch (err) { toast(err.message, true); }
  });
}

// ---------------------------------------------------------------- repairs & work orders
for (const b of $$("[data-plan]")) b.addEventListener("click", () => {
  for (const x of $$("[data-plan]")) x.setAttribute("aria-pressed", x === b);
  state.planMode = b.dataset.plan;
  loadPlan();
});
let budgetTimer = 0;
$("#planBudget").addEventListener("input", () => { clearTimeout(budgetTimer); budgetTimer = setTimeout(loadPlan, 250); });

async function loadPriority() {
  const q = state.sid && state.analysis ? `?project=${state.project.id}&survey=${state.sid}` : "";
  const r = await api(`/api/priority${q}`);
  $("#planMakeWo").hidden = true;
  $("#planDeferred").textContent = "";
  $("#planTotal").innerHTML = `${r.items.length}<small>potholes and defects, most urgent first</small>`;
  const notes = state.analysis?.traffic_notes || [];
  $("#planNote").innerHTML = `Priority = severity × safety × traffic${r.items.some((i) => i.kind === "pin") ? " (× confirmations for shared pins)" : ""}. ${esc(notes.join(". "))}
    <button class="btn small" id="trafficBtn" type="button">Update traffic</button>`;
  const roadLabel = (i) => (i.road ? esc(i.road.replace(/_/g, " ")) : "unknown");
  $("#planTable").innerHTML = `<thead><tr><th class="num">#</th><th>Item</th><th>Severity</th><th>Road, traffic</th><th class="num">Priority</th><th class="num">Materials</th><th>Where</th></tr></thead><tbody>${
    r.items.map((i) => `<tr ${i.kind === "pin" ? `data-pin="${esc(i.id)}"` : `data-id="${esc(i.id)}"`}><td class="num">${i.rank}</td>
      <td>${esc(i.label)}<br><span class="muted small">${i.kind === "pin" ? `Pinned by ${esc(i.reporter || "")}${i.confirmations ? `, ${i.confirmations} confirmed` : ""}` : `Survey · ${esc(i.segment_id || "")}`}</span></td>
      <td>${sevTag(i.severity)}</td><td>${roadLabel(i)} <span class="muted">×${i.traffic_factor}</span></td><td class="num"><b>${i.priority}</b></td>
      <td class="num">${i.materials ? costChip(i.materials, `data-card-${i.kind}="${esc(i.id)}"`) : `<button class="cost-chip none" type="button" data-card-${i.kind}="${esc(i.id)}">${i.kind === "pin" ? "Add size" : "Details"}</button>`}</td>
      <td><a href="${esc(i.maps_url)}" target="_blank" rel="noopener noreferrer" title="Open in Google Maps with live traffic" aria-label="Open in Google Maps">Map</a></td></tr>`).join("")
    || `<tr><td colspan="7" class="empty">Nothing to rank yet. Pin a pothole on the map or process a survey.</td></tr>`}</tbody>`;
  $("#trafficBtn").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      if (state.sid && state.analysis) {
        const t = await api(`/api/projects/${state.project.id}/surveys/${state.sid}/traffic`, { method: "POST", body: "{}" });
        state.analysis.traffic_notes = t.notes;
      }
      await api("/api/pins/traffic", { method: "POST", body: "{}" });
      await refreshAnalysis().catch(() => {});
      await loadPriority();
      toast("Traffic updated");
    } catch (err) { toast(err.message, true); }
  });
}

async function loadPlan() {
  if (state.planMode === "priority") return loadPriority();
  if (!state.sid || !state.analysis) {
    $("#planTable").innerHTML = `<tbody><tr><td class="empty">Choose a processed survey to plan repairs.</td></tr></tbody>`;
    $("#planTotal").textContent = "";
    return;
  }
  const b = $("#planBudget").value;
  const q = new URLSearchParams({ mode: state.planMode, ...(b ? { budget: b } : {}) });
  const p = await api(`/api/projects/${state.project.id}/surveys/${state.sid}/plan?${q}`);
  state.plan = p;
  $("#planTotal").innerHTML = `${esc(money(p.total, p.currency))}<small>for ${p.items.length} ${p.mode === "spot" ? (p.items.length === 1 ? "repair" : "repairs") : "segments"}</small>`;
  $("#planNote").textContent = "Prices are placeholders until you enter your own rates in config/unit_costs.json.";
  $("#planDeferred").textContent = p.deferred.length ? `${p.deferred.length} more ${p.deferred.length === 1 ? "item doesn't" : "items don't"} fit the budget.` : "";
  $("#planMakeWo").hidden = p.mode !== "spot";
  if (p.mode === "spot") {
    $("#planTable").innerHTML = `<thead><tr><th>Defect</th><th>Severity</th><th>Work</th><th class="num">Quantity</th><th class="num">Cost</th><th>Segment</th></tr></thead><tbody>${
      p.items.map((i) => `<tr data-id="${esc(i.finding_id)}"><td>${esc(i.label)}</td><td>${sevTag(i.severity)}</td><td>${esc(i.action_label)}</td><td class="num">${i.quantity} ${esc(i.unit === "m2" ? "m²" : i.unit)}</td><td class="num">${Math.round(i.cost).toLocaleString()}</td><td>${esc(i.segment_id || "")}</td></tr>`).join("")
      || `<tr><td colspan="6" class="empty">There are no open defects to repair.</td></tr>`}</tbody>`;
  } else {
    $("#planTable").innerHTML = `<thead><tr><th>Segment</th><th class="num">Condition</th><th>Treatment</th><th class="num">Area</th><th class="num">Cost</th></tr></thead><tbody>${
      p.items.map((i) => `<tr data-seg="${esc(i.segment_id)}"><td>${esc(i.segment_id)}</td><td class="num">${i.condition}</td><td>${esc(i.label)}</td><td class="num">${i.area_m2} m²</td><td class="num">${Math.round(i.cost).toLocaleString()}</td></tr>`).join("")
      || `<tr><td colspan="5" class="empty">No segment has a condition score yet.</td></tr>`}</tbody>`;
  }
}
$("#planTable").addEventListener("click", (e) => {
  const cf = e.target.closest("[data-card-finding]");
  if (cf) return findingCard(cf.dataset.cardFinding);
  const cp = e.target.closest("[data-card-pin]");
  if (cp) return pinCard(cp.dataset.cardPin);
  if (e.target.closest("a, button")) return;
  const tr = e.target.closest("tr[data-id]");
  if (tr) openDrawer(tr.dataset.id);
  const pr = e.target.closest("tr[data-pin]");
  if (pr) { setView("map"); openPin(pr.dataset.pin); }
});
$("#planMakeWo").addEventListener("click", () => {
  if (!state.plan?.items.length) return toast("There is nothing in the plan to put in a work order.", true);
  createWorkOrder(state.plan.items.map((i) => i.finding_id), $("#planBudget").value ? `Within ${money($("#planBudget").value)}` : "");
});

async function createWorkOrder(ids, title = "") {
  try {
    const wo = await api(`/api/projects/${state.project.id}/workorders`, { method: "POST", body: JSON.stringify({ survey_id: state.sid, finding_ids: ids, title }) });
    toast(`Created work order ${wo.id} for ${wo.items.length} repairs, ${money(wo.total, wo.currency)}`);
    state.selected.clear();
    state.workorders = await api(`/api/projects/${state.project.id}/workorders`);
    await refreshAnalysis();
  } catch (e) { toast(e.message, true); }
}

function renderWorkorders() {
  const el = $("#woList");
  if (!state.workorders.length) { el.innerHTML = `<p class="empty">No work orders yet. Create one from the plan or from selected defects in the inventory.</p>`; return; }
  const next = { open: ["scheduled", "cancelled"], scheduled: ["completed", "cancelled"], completed: [], partially_verified: ["completed"] };
  const btnLabel = { scheduled: "Schedule", completed: "Mark completed", cancelled: "Cancel" };
  el.innerHTML = state.workorders.slice().reverse().map((w) => `<div class="wo" data-id="${esc(w.id)}">
    <div class="wo-top"><b>${esc(w.id)}</b>${stateTag(w.status)}<span class="spacer"></span><span>${esc(money(w.total, w.currency))}</span></div>
    <p class="muted small">${esc(w.title)}. ${w.items.length} ${w.items.length === 1 ? "repair" : "repairs"}${w.verification ? `, ${w.verification.verified} of ${w.verification.total} verified` : ""}.</p>
    <div class="wo-actions">${(next[w.status] || []).map((s) => `<button class="btn small ${s === "completed" ? "primary" : s === "cancelled" ? "quiet" : ""}" data-status="${s}" type="button">${btnLabel[s]}</button>`).join("")}
      <button class="btn small quiet" data-show type="button">Show on map</button>${["completed", "partially_verified"].includes(w.status) ? `<button class="btn small" data-verify type="button">Verify the repairs</button>` : ""}</div></div>`).join("");
}
$("#woList").addEventListener("click", async (e) => {
  const card = e.target.closest(".wo");
  if (!card) return;
  const w = state.workorders.find((x) => x.id === card.dataset.id);
  if (e.target.dataset.status) {
    try {
      await api(`/api/projects/${state.project.id}/workorders/${w.id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.dataset.status }) });
      state.workorders = await api(`/api/projects/${state.project.id}/workorders`);
      await refreshAnalysis();
    } catch (err) { toast(err.message, true); }
  } else if (e.target.hasAttribute("data-show")) {
    setHighlight(w.items.map((i) => i.finding_id), []);
    setView("map");
    mapApi.fit(state.highlight);
  } else if (e.target.hasAttribute("data-verify")) {
    setView("verify");
    $("#verWo").value = w.id;
  }
});

// ---------------------------------------------------------------- verification
function renderVerifyControls() {
  const done = state.surveys.filter((s) => s.status === "done" && !isVideoJob(s));
  const opts = done.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
  const b = $("#verBefore"), a = $("#verAfter"), w = $("#verWo");
  const pb = b.value, pa = a.value, pw = w.value;
  b.innerHTML = opts; a.innerHTML = opts;
  b.value = pb || state.project?.baseline || done[0]?.id || "";
  a.value = pa || done.find((s) => s.id !== b.value)?.id || "";
  w.innerHTML = `<option value="">All defects</option>` + state.workorders.map((x) => `<option value="${esc(x.id)}">${esc(x.id)}, ${esc(x.title)}</option>`).join("");
  w.value = pw;
  renderVerifyResults();
}
function renderVerifyResults() {
  const v = state.verification;
  const t = $("#verTable");
  if (!v) {
    $("#verCounts").textContent = "";
    t.innerHTML = `<tbody><tr><td class="empty">Choose the original survey as Before and a drive recorded after the repairs as After, then compare them.</td></tr></tbody>`;
    return;
  }
  const c = v.counts;
  $("#verCounts").innerHTML = `<b>${c.verified}</b> ${c.verified === 1 ? "repair is" : "repairs are"} confirmed by the new scan. <b>${c.not_fixed}</b> ${c.not_fixed === 1 ? "defect is" : "defects are"} still there${c.not_covered ? `, and <b>${c.not_covered}</b> weren't covered by the new drive` : ""}.`;
  t.innerHTML = `<thead><tr><th>Defect</th><th>Severity</th><th>Result</th><th class="num">Surface now</th><th>Evidence</th><th>ID</th></tr></thead><tbody>${
    v.results.map((r) => `<tr data-id="${esc(r.finding_id)}"><td>${esc(label(r.type))}</td><td>${sevTag(r.severity)}</td><td>${stateTag(r.status)}</td><td class="num">${r.surface_delta_m == null ? "" : (r.surface_delta_m * 100).toFixed(1) + " cm"}</td><td class="ev">${esc(r.evidence)}</td><td class="id">${esc(r.finding_id)}</td></tr>`).join("")}</tbody>`;
}
$("#verTable").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr && findById(tr.dataset.id)) openDrawer(tr.dataset.id); });
$("#verRun").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const before = $("#verBefore").value, after = $("#verAfter").value;
  if (!before || !after || before === after) return toast("Choose two different processed surveys.", true);
  btn.disabled = true;
  try {
    state.verification = await api(`/api/projects/${state.project.id}/verify`, { method: "POST", body: JSON.stringify({ before, after, workorder_id: $("#verWo").value || null }) });
    state.workorders = await api(`/api/projects/${state.project.id}/workorders`);
    if (state.sid === before) await refreshAnalysis();
    renderVerifyResults();
  } catch (err) { toast(err.message, true); }
  btn.disabled = false;
});

// ---------------------------------------------------------------- scale of 3D clips (static/scene_scale.js)
// "Scale: camera height guess" / "Scale: 3 scene references ±4%" on a clip
const scaleTag = (sc) => `<span class="scale-tag ${esc(sc.method)}" title="${esc(sc.label || "How the size of this 3D clip was set")}">Scale: ${esc(sc.text)}</span>`;
async function fixScale(sid, title = "") {
  try {
    await openSceneScale({
      project: state.project.id, survey: sid, title, toast,
      onApplied: async () => {
        const proj = await api(`/api/projects/${state.project.id}`);
        state.project = proj; state.surveys = proj.survey_list;
        if (state.sid === sid) {
          await refreshAnalysis();
          state.pointsFor = null;
          viewer.clear();
          if (state.view === "scan") ensurePoints();
        }
        renderScaleTools();
        if (state.view === "video") renderVideo();
      },
    });
  } catch (err) { toast(err.message, true); }
}
let scaleToken = 0;
async function renderScaleTools() {
  const tag = $("#scaleTag"), btn = $("#sceneScaleBtn");
  const sv = state.surveys.find((s) => s.id === state.sid);
  tag.hidden = btn.hidden = true;
  if (!sv || sv.status !== "done" || sv.decoder !== "lingbot_clip") return;
  const t = ++scaleToken;
  try {
    const sc = await api(`/api/projects/${state.project.id}/surveys/${sv.id}/scale`);
    if (t !== scaleToken) return;
    tag.outerHTML = scaleTag(sc).replace("<span ", '<span id="scaleTag" ');
    $("#sceneScaleBtn").hidden = !sc.available;
    $("#sceneScaleBtn").title = sc.available ? "Tap objects of known size in the clip's frames to set the real-world scale" : sc.why;
  } catch { /* no scale info: leave the tools hidden */ }
}
$("#sceneScaleBtn").addEventListener("click", () => {
  const sv = state.surveys.find((s) => s.id === state.sid);
  if (sv) fixScale(sv.id, sv.name);
});

// ---------------------------------------------------------------- video jobs
let videoRenderToken = 0;
async function renderVideo() {
  const body = $("#videoBody");
  const jobs = state.surveys.filter(isVideoJob);
  if (!state.project || !jobs.length) {
    body.innerHTML = !state.project
      ? `<p class="empty">No project yet. <button class="btn small primary inline-cta" type="button" data-open-wizard>Create project</button></p>`
      : `<p class="empty">No drive videos yet. Choose Add survey, then the video source, and upload the drive with its gps.csv.</p>`;
    return;
  }
  const token = ++videoRenderToken;
  state.videoRecs = {};
  const parts = [];
  for (const j of jobs.slice().reverse()) {
    let v = null;
    try { v = await api(`/api/projects/${state.project.id}/surveys/${j.id}/video`); } catch { /* not started yet */ }
    if (v) state.videoRecs[j.id] = v;
    parts.push(renderJob(j, v));
  }
  if (token === videoRenderToken) body.innerHTML = parts.join("");
}
function renderJob(j, v) {
  const base = `/api/projects/${state.project.id}/surveys/${j.id}/video/image/`;
  if (!v) return `<section class="job"><div class="job-head"><h2>${esc(j.name)}</h2>${stateTag(j.status)}<span class="muted">${esc(j.stage || j.error || "")}</span></div></section>`;
  const dur = v.info.duration || 1;
  const pct = (t) => `${((t / dur) * 100).toFixed(3)}%`;
  const tl = `<div class="timeline" aria-label="Detections along the video">
      <div class="tl-track"></div>
      ${v.windows.map((w) => `<div class="tl-win" style="left:${pct(w.start)};width:${pct(w.end - w.start)}" title="Clip ${w.index + 1}: ${mmss(w.start)} to ${mmss(w.end)}"></div>`).join("")}
      ${v.detections.map((d) => `<span class="tl-hit" style="left:${pct(d.t)}" title="Pothole at ${mmss(d.t)}, confidence ${(d.conf * 100).toFixed(0)}%"></span>`).join("")}
      <span class="tl-t start" style="left:0">0:00</span><span class="tl-t end" style="left:100%">${mmss(dur)}</span></div>`;
  const dets = v.detections.slice(0, 24).map((d, k) => `<figure class="det">
      <div class="det-imgs"><img loading="lazy" src="${base}${esc(d.image)}" alt="Video frame at ${mmss(d.t)} with the detection box"><img loading="lazy" src="${base}${esc(d.bev_image)}" alt="Top-down view of the same frame"></div>
      <figcaption class="det-body"><b>${mmss(d.t)}</b><span>Confidence ${(d.conf * 100).toFixed(0)}%. ${d.bev_valid && d.calibrated ? `About ${d.bev_width_m} m wide and ${d.distance_ahead_m} m ahead.` : d.calibrated ? "This box falls outside the calibrated road area, so it has no size estimate." : "Calibrate the camera to get a size estimate from this view."}</span>
        <button class="btn small" type="button" data-measure="${esc(j.id)}:${k}">Measure</button></figcaption></figure>`).join("");
  const clips = v.children.map((c) => {
    const s = c.survey || {};
    const w = v.windows[c.window];
    const act = s.status === "error" ? `<button class="btn small" data-retry="${esc(c.survey_id)}" type="button">Try again</button>`
      : s.status === "done" ? `<button class="btn small" data-scale="${esc(c.survey_id)}" data-title="Clip ${c.window + 1}" type="button">Fix scale with scene objects</button>
        <button class="btn small primary" data-open="${esc(c.survey_id)}" type="button">Open in map and 3D</button>` : "";
    return `<div class="clip-row"><b>Clip ${c.window + 1}</b><span>${mmss(w.start)} to ${mmss(w.end)}, ${c.frames} frames</span>${stateTag(s.status || "queued")}
      <span class="muted small">${esc(s.status === "error" ? s.error : s.status === "done" ? `${s.stats.findings} findings` : s.stage || "")}</span>
      ${s.status === "done" && c.scale ? scaleTag(c.scale) : ""}<span class="spacer"></span>${act}</div>`;
  }).join("");
  const summary = v.detections.length
    ? `${v.detections.length} pothole ${v.detections.length === 1 ? "detection" : "detections"} in ${mmss(dur)} of video, grouped into ${v.windows.length} ${v.windows.length === 1 ? "clip" : "clips"} for 3D.`
    : `No potholes found in ${mmss(dur)} of video (${v.samples} frames checked).`;
  return `<section class="job"><div class="job-head"><h2>${esc(j.name)}</h2>${stateTag(j.status)}<span class="muted">${esc(j.status === "running" ? j.stage : summary)}</span></div>
    ${tl}${dets ? `<div class="det-grid">${dets}</div>` : ""}${clips ? `<div>${clips}</div>` : ""}</section>`;
}
async function measureDetection(jid, k) {
  const pid = state.project.id, v = state.videoRecs?.[jid], d = v?.detections[k];
  if (!d) return;
  const child = v.children.find((c) => c.window === d.window);
  let targets = [];
  if (child?.survey?.status === "done") {
    try {
      const an = await api(`/api/projects/${pid}/surveys/${child.survey_id}/analysis`);
      targets = an.findings.filter((f) => f.type === "pothole" || f.type === "depression").map((f) => ({
        target: { kind: "finding", project: pid, survey: child.survey_id, id: f.id },
        label: `${f.id} · ${label(f.type)}${f.metrics?.area_m2 ? ` · ${f.metrics.area_m2} m²` : ""}`,
      }));
    } catch { /* no analysis: preview only */ }
  }
  const base = `/api/projects/${pid}/surveys/${jid}/video/image/`;
  openMeasure({
    image: base + d.image, imageRef: { kind: "detection", survey: jid, file: d.image, t: d.t }, box: d.box, targets,
    title: `${mmss(d.t)}`, toast,
    onSaved: () => { if (child && state.sid === child.survey_id) refreshAnalysis().catch(() => {}); },
  }).catch((err) => toast(err.message, true));
}
$("#videoBody").addEventListener("click", async (e) => {
  const r = e.target.closest("[data-retry]"), o = e.target.closest("[data-open]"), mb = e.target.closest("[data-measure]");
  const sc = e.target.closest("[data-scale]");
  if (sc) return fixScale(sc.dataset.scale, sc.dataset.title);
  if (mb) {
    const [jid, k] = mb.dataset.measure.split(":");
    return measureDetection(jid, Number(k));
  }
  if (r) {
    try {
      await api(`/api/projects/${state.project.id}/surveys/${r.dataset.retry}/retry`, { method: "POST" });
      await selectProject(state.project.id);
      setView("video");
    } catch (err) { toast(err.message, true); }
  } else if (o) {
    await selectSurvey(o.dataset.open);
    setView("map");
  }
});

// ---------------------------------------------------------------- highlight & layers
function setHighlight(ids, segs) {
  state.highlight = ids || [];
  state.highlightSegs = segs || [];
  mapApi.highlight(state.highlight, state.highlightSegs);
  viewer.highlight(state.highlight);
  $("#clearHighlight").hidden = !state.highlight.length && !state.highlightSegs.length;
  renderStrip();
  renderInventory();
}
$("#clearHighlight").addEventListener("click", () => setHighlight([], []));
for (const b of $$("[data-layer]")) b.addEventListener("change", () => mapApi.setVisible(b.dataset.layer, b.checked));

// ---------------------------------------------------------------- questions panel
const SUGGEST = ["Where are the stop signs?", "How many high severity potholes are there?", "Which 3 segments are worst?", "What will it cost to fix the potholes?", "Plan repairs with a budget of 2k", "What has been verified?"];
$("#chatChips").innerHTML = SUGGEST.map((s) => `<button class="chip" type="button">${esc(s)}</button>`).join("");
$("#chatChips").addEventListener("click", (e) => { if (e.target.matches(".chip")) ask(e.target.textContent); });
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#chatInput").value.trim(); if (v) ask(v); });

function addMsg(cls, html) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  $("#chatLog").appendChild(el);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  return el;
}
const addBot = (text) => addMsg("bot", md(text));

function renderSources(el, r) {
  if (r.by !== "helper") return;
  const src = (r.sources || []).map((s) => `<li><b>[${s.n}]</b> ${esc(s.title)}${s.page ? `, page ${s.page}` : ""}</li>`).join("");
  const box = document.createElement("div");
  box.className = "sources";
  box.innerHTML = `${src ? `<p class="small muted">Sources</p><ul>${src}</ul>` : `<p class="small muted">No matching documents in your library.</p>`}
    <p class="small muted">Civil Helper, ${esc(r.model || "")}, ${r.seconds ?? "?"} s</p>`;
  el.appendChild(box);
}

async function ask(text) {
  addMsg("user", esc(text));
  $("#chatInput").value = "";
  const wait = addMsg("bot pending", "<p>Working on it…</p>");
  try {
    let r;
    if (state.project) {
      r = await api(`/api/projects/${state.project.id}/chat`, { method: "POST", body: JSON.stringify({ message: text, survey_id: state.sid }) });
    } else {
      const f = await api("/api/helper/ask", { method: "POST", body: JSON.stringify({ question: text }) });
      r = { reply: f.answer, highlight: [], segments: [], by: "helper", sources: f.sources, model: f.model, seconds: f.seconds };
    }
    wait.remove();
    const el = addBot(r.reply);
    renderSources(el, r);
    if (r.highlight.length || r.segments.length) {
      setHighlight(r.highlight, r.segments);
      if (state.view !== "scan") setView("map");
      mapApi.fit(r.highlight.length ? r.highlight : null);
    }
    if (r.plan && r.plan.mode === "spot" && r.plan.items.length) {
      const b = document.createElement("button");
      b.className = "btn small act";
      b.type = "button";
      b.textContent = `Create a work order for these ${r.plan.items.length}`;
      b.addEventListener("click", () => createWorkOrder(r.plan.items.map((i) => i.finding_id), text.slice(0, 80)), { once: true });
      el.appendChild(b);
    }
  } catch (e) { wait.remove(); addBot(`That didn't work: ${e.message}`); }
}

$("#chatToggle").addEventListener("click", (e) => {
  const app = $(".app");
  const small = matchMedia("(max-width: 1100px)").matches;
  const cls = small ? "chat-open" : "chat-hidden";
  app.classList.toggle(cls);
  const visible = small ? app.classList.contains("chat-open") : !app.classList.contains("chat-hidden");
  e.currentTarget.setAttribute("aria-pressed", visible);
  requestAnimationFrame(() => mapApi.resize());
});

// ---------------------------------------------------------------- dialogs
function fillDecoders() {
  const sel = $("#decoderSelect");
  const decs = state.meta.decoders.filter((d) => !d.internal);
  sel.innerHTML = decs.map((d) => `<option value="${esc(d.name)}" ${d.available ? "" : "disabled"}>${esc(d.label)}${d.available ? "" : " (not set up)"}</option>`).join("");
  const firstOk = decs.find((d) => d.available);
  if (firstOk) sel.value = firstOk.name;
  const help = () => {
    const d = decs.find((x) => x.name === sel.value);
    $("#decoderHelp").textContent = d ? d.description + (d.available ? "" : ` Not available: ${d.unavailable_reason}`) : "";
  };
  sel.onchange = help;
  help();
}
$("#newSurveyBtn").addEventListener("click", async () => {
  if (!state.project) { toast("Create a project first."); return setView("create"); }
  state.meta = await api("/api/meta");
  fillDecoders();
  $("#uploadProgress").hidden = true;
  $("#surveyDialog").showModal();
});
$("#surveyForm").addEventListener("submit", (e) => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const f = e.target;
  const params = {};
  if (f.camera_height_m.value) params.camera_height_m = +f.camera_height_m.value;
  if (f.heading_deg.value) params.heading_deg = +f.heading_deg.value;
  if (f.up_axis.value) params.up_axis = f.up_axis.value;
  if (f.metric.checked) params.metric = true;
  const fd = new FormData();
  fd.append("name", f.name.value);
  fd.append("decoder", f.decoder.value);
  fd.append("params", JSON.stringify(params));
  for (const file of $("#surveyFiles").files) fd.append("files", file, file.name);
  const xhr = new XMLHttpRequest();
  const bar = $("#uploadProgress");
  bar.hidden = false;
  $("#surveySubmit").disabled = true;
  xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) bar.firstElementChild.style.width = `${(100 * ev.loaded) / ev.total}%`; };
  xhr.onload = async () => {
    $("#surveySubmit").disabled = false;
    if (xhr.status >= 300) { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch { /* keep */ } return toast(m, true); }
    $("#surveyDialog").close();
    const sv = JSON.parse(xhr.responseText);
    toast(`Uploaded ${sv.name}. Processing has started.`);
    state.sid = sv.id;
    await selectProject(state.project.id);
  };
  xhr.onerror = () => { $("#surveySubmit").disabled = false; toast("The upload failed. Check the connection and try again.", true); };
  xhr.open("POST", `/api/projects/${state.project.id}/surveys`);
  xhr.setRequestHeader("X-Civil-Scan", "1");
  xhr.send(fd);
});
$("#newProjectBtn").addEventListener("click", () => setView("create"));

// ---------------------------------------------------------------- shared pins
async function loadPins() {
  try {
    const r = await api("/api/pins?status=open");
    state.pins = r.pins;
    mapApi.setPins(state.pins);
  } catch { /* offline for a moment */ }
}
let pinTimer = 0;
function pollPins() { clearInterval(pinTimer); pinTimer = setInterval(loadPins, 15000); }

function setPinMode(on) {
  state.pinMode = on;
  $("#pinBtn").setAttribute("aria-pressed", on);
  $("#pinBtn").textContent = on ? "Click the map where the pothole is" : "Pin a pothole";
  mapApi.setPinMode(on);
}
$("#pinBtn").addEventListener("click", () => setPinMode(!state.pinMode));
// ---------------------------------------------------------------- my location (opt-in)
loc.onChange((f) => {
  mapApi.setMe(f);
  $("#locateBtn").setAttribute("aria-pressed", String(!!f));
});
$("#locateBtn").addEventListener("click", async () => {
  try {
    if (!(await loc.ensure("The map can show where you are."))) return;
    const f = loc.fix();
    if (f) { mapApi.ensureView(f.lat, f.lon); mapApi.flyTo(f); } else toast("Finding your position…");
    const off = loc.onChange((g) => { if (g && !g.stale) { off(); mapApi.ensureView(g.lat, g.lon); mapApi.flyTo(g); } });
    setTimeout(off, 20000);
  } catch (err) { toast(err.message, true); }
});

/* Pin where I am: wait for a fix of 10 m or better (or let the person use the best so far). */
$("#pinHereBtn").addEventListener("click", async () => {
  try { if (!(await loc.ensure("Pinning where you stand uses your GPS position."))) return; }
  catch (err) { return toast(err.message, true); }
  setPinMode(false);
  const d = $("#drawer");
  d.innerHTML = `<button class="btn icon quiet drawer-close" aria-label="Close" type="button">✕</button>
    <h3>Pin where I am</h3>
    <div class="fixing"><span class="fix-ring" aria-hidden="true"></span>
      <div><b id="fixAcc">Finding your position…</b><p class="muted small" id="fixNote">Stand next to the pothole. iScale waits for a position within 10 m.</p></div></div>
    <div class="row"><button class="btn small primary" id="fixUse" type="button" disabled>Use this position</button><button class="btn small quiet" id="fixCancel" type="button">Cancel</button></div>`;
  d.hidden = false;
  delete d.dataset.pin;
  let answer;
  const until = new Promise((r) => { answer = r; });
  $("#fixUse").onclick = () => answer("use");
  $("#fixCancel").onclick = () => { answer("cancel"); closeDrawer(); };
  d.querySelector(".drawer-close").onclick = () => answer("cancel");
  try {
    const f = await loc.preciseFix({ target: 10, until, onProgress: (g) => {
      if (!$("#fixAcc")) return answer("cancel"); // the drawer moved on to something else
      $("#fixAcc").textContent = `±${Math.round(g.acc)} m`;
      $("#fixNote").textContent = g.acc <= 10 ? "Good enough." : "Waiting for a better position. Open sky helps; you can also use this one.";
      $("#fixUse").disabled = false;
      mapApi.ensureView(g.lat, g.lon);
      mapApi.flyTo(g);
    } });
    if (!$("#fixAcc")) return; // closed while waiting: don't open a pin form over something else
    placePin(f.lat, f.lon, { source: "device", accuracy_m: f.acc });
  } catch (err) { if (err.message !== "cancelled") toast(err.message, true); }
});

$("#recordBtn").addEventListener("click", async () => {
  state.meta = await api("/api/meta");
  const dec = state.meta.decoders.find((x) => x.name === "pothole_video");
  openRecorder({ project: state.project, toast, available: !!dec?.available,
    onUploaded: async (sv) => { toast(`Uploaded ${sv.name}. Processing has started.`); state.sid = sv.id; await selectProject(state.project.id); } });
});

function placePin(lat, lon, gps = null) {
  setPinMode(false);
  const d = $("#drawer");
  d.innerHTML = `<button class="btn icon quiet drawer-close" aria-label="Close" type="button">✕</button>
    <h3>Pin a pothole</h3>
    <p class="muted small">Everyone on this server will see this pin on their map.</p>
    <form id="pinForm" style="display:grid;gap:10px">
      <div class="grid2">
        <label class="field"><span>What is it?</span><select class="input" name="type">
          ${state.meta.catalog.filter((t) => t.kind === "defect").map((t) => `<option value="${esc(t.code)}" ${t.code === "pothole" ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></label>
        <label class="field"><span>Severity</span><select class="input" name="severity"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option></select></label>
      </div>
      <label class="field"><span>Note</span><input class="input" name="note" maxlength="500" placeholder="For example: in the left lane, near the bus stop"></label>
      <details class="adv"><summary>Size, for the materials cost (optional)</summary>
        <div class="jc-size">
          <label class="field"><span>Width (cm)</span><input class="input num" name="width_cm" type="number" inputmode="decimal" min="1" max="5000"></label>
          <label class="field"><span>Length (cm)</span><input class="input num" name="length_cm" type="number" inputmode="decimal" min="1" max="5000"></label>
          <label class="field"><span>Depth (cm)</span><input class="input num" name="depth_cm" type="number" inputmode="decimal" min="0.5" max="200" step="0.5"></label>
        </div></details>
      <p class="muted small">${lat.toFixed(6)}, ${lon.toFixed(6)}${gps ? `, your GPS position (±${Math.round(gps.accuracy_m)} m)` : ""}</p>
      <button class="btn primary small" type="submit">Pin it</button>
    </form>`;
  d.hidden = false;
  $("#pinForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const dims = ["width_cm", "length_cm", "depth_cm"].map((k) => Number(f.get(k)));
      const size = dims.every((v) => v > 0) ? { width_cm: dims[0], length_cm: dims[1], depth_cm: dims[2] } : null;
      if (!size && dims.some((v) => v > 0)) return toast("Fill in width, length and depth, or leave all three empty.", true);
      const pin = await api("/api/pins", { method: "POST", body: JSON.stringify({ lat, lon, type: f.get("type"), severity: f.get("severity"), note: f.get("note"), size, ...(gps || {}) }) });
      toast(pin.merged ? "Someone already pinned this spot; your report was added as a confirmation." : "Pinned. Everyone can see it now.");
      await loadPins();
      openPin(pin.id);
    } catch (err) { toast(err.message, true); }
  });
}

function openPin(id) {
  const p = state.pins.find((x) => x.id === id);
  if (!p) return;
  const d = $("#drawer");
  const mine = p.reporter === state.user.username;
  const t = p.traffic;
  d.innerHTML = `<button class="btn icon quiet drawer-close" aria-label="Close" type="button">✕</button>
    <h3>${esc(p.label)}</h3>
    <div class="sub">${sevTag(p.severity)}${stateTag(p.status)}<span>Shared pin</span></div>
    <div class="row">${p.cost ? costChip(p.cost, 'data-pin-act="card"') : `<button class="cost-chip none" type="button" data-pin-act="card">Add size for a cost</button>`}<button class="btn small" data-pin-act="card" type="button">Full details</button></div>
    ${p.note ? `<p class="ev">${esc(p.note)}</p>` : ""}
    ${p.measured ? `<p class="ev meas">${esc(measuredText(p.measured))}</p>` : ""}
    <div class="row">${p.photo ? `<button class="btn small" data-pin-act="measure" type="button">Measure on the photo</button>` : ""}<button class="btn small${p.photo ? " quiet" : ""}" data-pin-act="photo" type="button">${p.photo ? "New photo & measure" : "Add photo & measure"}</button></div>
    <dl class="meta">
      <dt>Pinned by</dt><dd>${esc(p.reporter_name)} (@${esc(p.reporter)}), ${esc(p.reporter_company || "")}</dd>
      <dt>When</dt><dd>${new Date(p.created * 1000).toLocaleString()}</dd>
      <dt>Confirmed by</dt><dd>${p.confirmations.length ? p.confirmations.map((u) => "@" + esc(u)).join(", ") : "nobody yet"}</dd>
      <dt>Road</dt><dd>${t ? `${esc((t.highway || "unknown").replace(/_/g, " "))}${t.road_name ? ", " + esc(t.road_name) : ""}; traffic ×${t.factor}` : "not assessed yet (Repairs, Fix first, Update traffic)"}</dd>
      <dt>Location</dt><dd>${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}${p.source === "device" ? `<br><span class="muted small">GPS where the reporter stood${p.accuracy_m != null ? `, ±${Math.round(p.accuracy_m)} m` : ""}</span>` : `<br><span class="muted small">Placed on the map</span>`}</dd>
    </dl>
    <div class="row">
      <a class="btn small" href="${esc(p.maps_url)}" target="_blank" rel="noopener noreferrer">Google Maps traffic</a>
      <button class="btn small" data-pin-act="send" type="button">Send to an engineer</button>
    </div>
    <div class="row">
      ${!mine && !p.confirmations.includes(state.user.username) ? `<button class="btn small primary" data-pin-act="confirm" type="button">I see it too</button>` : ""}
      ${p.status === "open" ? `<button class="btn small" data-pin-act="fixed" type="button">Mark fixed</button>` : ""}
      ${mine || state.user.role === "admin" ? `<button class="btn small quiet" data-pin-act="dismissed" type="button">Remove pin</button>` : ""}
    </div>`;
  d.hidden = false;
  d.dataset.pin = id;
  mapApi.highlight([id], []);
  mapApi.flyTo(p);
}
$("#drawer").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-pin-act]");
  if (!b) return;
  const id = $("#drawer").dataset.pin;
  const p = state.pins.find((x) => x.id === id);
  const a = b.dataset.pinAct;
  if (a === "card") return pinCard(id);
  if (a === "measure" || a === "photo") {
    return startMeasure({
      target: { kind: "pin", id }, photo: p.photo, newPhoto: a === "photo", title: `${p.label} ${p.id}`, toast,
      onSaved: async (out) => { await loadPins(); if (!out?.photoOnly) openPin(id); },
    });
  }
  try {
    if (a === "send") return shareInChat({ kind: "pin", pin: { id: p.id, label: p.label, severity: p.severity, note: p.note, lat: p.lat, lon: p.lon } });
    if (a === "confirm") await api(`/api/pins/${id}/confirm`, { method: "POST", body: "{}" });
    else await api(`/api/pins/${id}`, { method: "PATCH", body: JSON.stringify({ status: a }) });
    await loadPins();
    if (a === "confirm") openPin(id); else closeDrawer();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- messages
function shareInChat(payload) {
  state.pendingShare = payload;
  closeDrawer();
  setView("messages");
  toast("Choose who to send it to.");
}

function pickAttachment() {
  return new Promise((resolve) => {
    const defects = (state.analysis?.findings || []).filter((f) => kindOf(f.type) === "defect" && f.status !== "dismissed").slice(0, 60);
    const dlg = document.createElement("dialog");
    dlg.className = "dialog";
    dlg.innerHTML = `<form method="dialog"><h2>Share a pothole</h2>
      <div class="pick-list">
        ${state.pins.length ? `<p class="muted small">Shared pins</p>` + state.pins.map((p) => `<label class="check"><input type="radio" name="pick" value="pin:${esc(p.id)}"> ${esc(p.label)}, ${esc(p.severity)}${p.note ? `: ${esc(p.note.slice(0, 60))}` : ""}</label>`).join("") : ""}
        ${defects.length ? `<p class="muted small">From the open survey</p>` + defects.map((f) => `<label class="check"><input type="radio" name="pick" value="f:${esc(f.id)}"> ${esc(label(f.type))}, ${esc(f.severity || "")}, segment ${esc(f.segment_id || "")}</label>`).join("") : ""}
        ${!state.pins.length && !defects.length ? `<p class="muted">Nothing to share yet. Pin a pothole on the map first.</p>` : ""}
      </div>
      <div class="dialog-actions"><button class="btn quiet" value="cancel">Cancel</button><button class="btn primary" value="ok">Share</button></div></form>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("close", () => {
      const v = dlg.returnValue === "ok" ? dlg.querySelector("input[name=pick]:checked")?.value : null;
      dlg.remove();
      if (!v) return resolve(null);
      const [kind, id] = v.split(/:(.*)/s);
      if (kind === "pin") {
        const p = state.pins.find((x) => x.id === id);
        return resolve({ kind: "pin", pin: { id: p.id, label: p.label, severity: p.severity, note: p.note, lat: p.lat, lon: p.lon } });
      }
      const f = findById(id);
      resolve({ kind: "finding", finding: { id: f.id, label: label(f.type), severity: f.severity, evidence: f.evidence, lat: f.lat, lon: f.lon } });
    });
    dlg.showModal();
  });
}

async function startMessaging() {
  state.messenger = new Messenger(state.user, {
    onMessage: (peer, incoming) => {
      state.chatUi?.refresh(peer);
      if (incoming && !(state.view === "messages" && state.chatUi?.isOpen(peer)) && incoming.kind !== "notice") {
        toast(incoming.group ? `New message in ${incoming.conv_name}` : `New message from ${incoming.from_name || "@" + peer}`);
      }
    },
    onUnread: (n) => { const b = $("#unread"); b.hidden = !n; b.textContent = n; },
  });
  try {
    await state.messenger.start();
  } catch (e) {
    $("#view-messages").innerHTML = `<p class="empty">Encrypted chat couldn't start: ${esc(e.message)}. Browsers allow it only on HTTPS or localhost.</p>`;
    return;
  }
  state.chatUi = chatView($("#view-messages"), state.messenger, {
    toast,
    onShowOnMap: (lat, lon) => { setView("map"); mapApi.ensureView(lat, lon); mapApi.flyTo({ lat, lon }); },
    pickAttachment,
    takePending: () => { const p = state.pendingShare; state.pendingShare = null; return p; },
  });
}

function renderMe() {
  const u = state.user;
  $("#me").innerHTML = `${esc(u.display_name)} <span class="muted">@${esc(u.username)}, ${esc(u.company)}</span>`;
}
$("#signOut").addEventListener("click", async () => {
  state.messenger?.stop();
  await session.signOut();
  location.hash = "";
  location.reload();
});

async function helperStatus() {
  try {
    const st = await api("/api/helper/status");
    $("#helperStatus").textContent = st.reachable ? `Answers with ${st.model}, from ${st.documents} ${st.documents === 1 ? "document" : "documents"} in your library` : `Civil Helper's model isn't reachable: ${st.error}`;
  } catch { /* leave the default text */ }
}

// ---------------------------------------------------------------- boot
(async function boot() {
  try {
    const st = await session.state();
    state.user = st.user || (await session.showLogin($("#login"), st));
    $("#app").hidden = false;
    renderMe();
    state.meta = await api("/api/meta");
    state.catalog = Object.fromEntries(state.meta.catalog.map((t) => [t.code, t]));
    await loadProjects();
    setView(location.hash.slice(1) || "map");
    await loadPins();
    pollPins();
    helperStatus();
    startMessaging();
    // the location agreement comes first on entry; the welcome waits until it is answered
    loc.onEntry().finally(() => maybeWelcome(state.user, goTo));
    if (state.user.role === "admin") adminSteps(state.user.account).then(setupBadge).catch(() => {});
    if (!state.projects.length) addBot("Ask Civil Helper about repair methods and standards, or load the demo street to try the survey tools.");
  } catch (e) { toast(`Can't reach the server: ${e.message}`, true); }
})();
window.addEventListener("hashchange", () => setView(location.hash.slice(1)));

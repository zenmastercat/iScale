/* Step-by-step Create Project wizard (static/project_wizard.js).
 *
 * 1 Basics        name, road/route, client/agency, date, notes
 * 2 Location      interactive map (point or route polyline) + synced lat/lon + GPS
 * 3 Data sources  live decoder availability (pothole_video, ply_import, forge_slam, photos, demo)
 * 4 Scale & measure  measure_refs preset + interactive photo measure preview + scene_scale refs + placement
 * 5 Materials & report  DOH materials rates (admin inline edit) + units + preferred exports
 * 6 Review & confirm  summary with Edit links -> creates project + uploads surveys/photos + clears draft
 */

import { createMap } from "./map.js";
import { getLang } from "./i18n.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const DRAFT_STORAGE_KEY = "iscale-project-draft";
const MAX_PHOTO_MB = 15;
const MAX_PHOTOS = 20;

const STEPS = [
  { id: "basics", label: "Basics" },
  { id: "location", label: "Location" },
  { id: "sources", label: "Data sources" },
  { id: "scale", label: "Scale & measure" },
  { id: "materials", label: "Materials & report" },
  { id: "review", label: "Review" },
];

const SOURCE_DEFS = [
  {
    id: "pothole_video",
    decoder: "pothole_video",
    title: "Phone drive video",
    subtitle: "Scan a drive video for potholes and rebuild detection clips in 3D with LingBot-Map.",
    accept: ".mp4,.mov,.avi,.mkv,.webm,.m4v,.csv",
    defaultName: "Drive video",
    fileHint: "Select one drive video (.mp4, .mov, .webm) and optional gps.csv.",
    needsFiles: true,
  },
  {
    id: "ply_import",
    decoder: "ply_import",
    title: "3D point cloud (PLY)",
    subtitle: "Import an existing .ply scan with optional poses.json, gps.csv and labels.json.",
    accept: ".ply,.json,.txt,.csv",
    defaultName: "Point cloud import",
    fileHint: "Select a .ply file plus optional poses, gps.csv or labels.json.",
    needsFiles: true,
  },
  {
    id: "forge_slam",
    decoder: "forge_slam",
    title: "FORGE SLAM sensors",
    subtitle: "Multi-sensor LiDAR, IMU, RGB and radiometric thermal (°C) folder or ROS bag.",
    accept: ".pcd,.bin,.bag,.db3,.csv,.yaml,.yml,.json,.png,.jpg,.jpeg,.tif,.tiff",
    defaultName: "FORGE SLAM run",
    fileHint: "Select LiDAR scans, IMU/GPS CSVs, calibration file and optional RGB/thermal frames.",
    needsFiles: true,
  },
  {
    id: "photos",
    decoder: null,
    title: "Site & reference photos",
    subtitle: "Attach road or defect photos (up to 20 photos, 15 MB and 60 MP each) for on-site reference measuring.",
    accept: "image/*",
    defaultName: "",
    fileHint: "JPEG, PNG or WebP photos. EXIF metadata is stripped automatically on upload.",
    needsFiles: false,
  },
  {
    id: "demo",
    decoder: "demo",
    title: "Synthetic demo street",
    subtitle: "Generate a sample street with planted potholes and road assets — no files needed.",
    accept: "",
    defaultName: "Sample street drive",
    fileHint: "",
    needsFiles: false,
  },
];

const GROUP_LABELS = {
  road_markings: "Road markings",
  vehicles: "Vehicles",
  street_furniture: "Street furniture",
  custom: "Custom",
};

const CHECK_SVG = `<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function haversineM([lat1, lon1], [lat2, lon2]) {
  const R = 6371000;
  const r = (x) => (x * Math.PI) / 180;
  const dLat = r(lat2 - lat1), dLon = r(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function routeLengthM(route) {
  let total = 0;
  for (let i = 1; i < route.length; i++) total += haversineM(route[i - 1], route[i]);
  return total;
}

function fmtBytes(n) {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function defaultState(origin) {
  return {
    step: 0,
    name: "",
    road_name: "",
    client: "",
    survey_date: todayIso(),
    notes: "",
    origin_lat: origin[0],
    origin_lon: origin[1],
    loc_mode: "point",
    route: [],
    sources: [],
    source_names: {
      pothole_video: "Drive video",
      ply_import: "Point cloud import",
      forge_slam: "FORGE SLAM run",
      demo: "Sample street drive",
    },
    forge_params: {
      keyframe_dist_m: 1.0,
      voxel_size_m: 0.1,
      max_ram_bytes: 512 * 1024 * 1024,
      enable_dynamic_filter: true,
      enable_loop_closure: true,
      enable_thermal: true,
    },
    scale_setup: {
      measure_ref: "a4",
      ref_width_cm: null,
      ref_length_cm: null,
      scene_ref_ids: [],
      camera_height_m: 1.4,
      heading_deg: null,
      up_axis: "",
      metric: false,
      sample_measurement: null,
    },
    report_prefs: {
      units: "metric",
      materials_preset: "company",
      include_doh_materials: true,
      export_formats: ["csv", "geojson"],
    },
    had_files: false,
  };
}

export function createProjectWizard(root, ctx) {
  let S = null;
  let meta = null;
  let measureRefs = [];
  let sceneCatalog = [];
  let materialsData = null;
  let filesBySource = {};       // { pothole_video: File[], ply_import: File[], forge_slam: File[], photos: File[] }
  let photoUrls = new Map();    // File -> objectURL
  let pickMap = null;
  let draftLoaded = false;
  let draftStatus = "";         // "", "saving", "saved", "resumed"
  let saveTimer = 0;
  let submitting = false;
  let fieldError = "";
  let adminMatDraft = null;     // { key: { price, bag_kg } } if admin edits company prices

  const revokePhotoUrls = () => {
    for (const url of photoUrls.values()) URL.revokeObjectURL(url);
    photoUrls.clear();
  };

  const photoUrlFor = (file) => {
    if (!photoUrls.has(file)) photoUrls.set(file, URL.createObjectURL(file));
    return photoUrls.get(file);
  };

  function hasFiles() {
    return Object.values(filesBySource).some((arr) => arr && arr.length > 0);
  }

  function draftPayload() {
    return {
      step: S.step,
      name: S.name,
      road_name: S.road_name,
      client: S.client,
      survey_date: S.survey_date,
      notes: S.notes,
      origin_lat: Number.isFinite(Number(S.origin_lat)) ? Number(S.origin_lat) : null,
      origin_lon: Number.isFinite(Number(S.origin_lon)) ? Number(S.origin_lon) : null,
      loc_mode: S.loc_mode,
      route: S.route,
      sources: S.sources,
      source_names: S.source_names,
      forge_params: S.sources.includes("forge_slam") ? S.forge_params : {},
      scale_setup: S.scale_setup,
      report_prefs: S.report_prefs,
      had_files: hasFiles() || S.had_files,
    };
  }

  function saveLocal(p) {
    try { localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
  }

  function clearLocal() {
    try { localStorage.removeItem(DRAFT_STORAGE_KEY); } catch { /* ignore */ }
  }

  function setDraftBadge(mode) {
    draftStatus = mode;
    const b = root.querySelector("#wizDraftStatus");
    if (!b) return;
    if (mode === "saving") b.textContent = "Saving draft…";
    else if (mode === "saved") b.textContent = "Draft saved";
    else if (mode === "resumed") b.textContent = "Resumed from saved draft";
    else b.textContent = "";
    const disc = root.querySelector("#wizDiscardBtn");
    if (disc) disc.hidden = !mode;
  }

  function scheduleDraftSave(delay = 600) {
    if (!S || submitting) return;
    const payload = draftPayload();
    saveLocal(payload);
    clearTimeout(saveTimer);
    setDraftBadge("saving");
    saveTimer = setTimeout(async () => {
      try {
        await ctx.api("/api/project-draft", { method: "PUT", body: JSON.stringify(draftPayload()) });
        setDraftBadge("saved");
      } catch {
        setDraftBadge("saved"); // kept locally even if a transient field isn't valid yet
      }
    }, delay);
  }

  async function loadDependencies() {
    const [m, mr, sc, mats, dr] = await Promise.all([
      ctx.api("/api/meta"),
      ctx.api("/api/measure/refs").catch(() => ({ refs: [] })),
      ctx.api("/api/scene_scale/refs").catch(() => ({ objects: [] })),
      ctx.api("/api/settings/materials").catch(() => null),
      ctx.api("/api/project-draft").catch(() => ({ draft: null })),
    ]);
    meta = m;
    measureRefs = mr.refs || [];
    sceneCatalog = sc.objects || [];
    materialsData = mats;
    return dr?.draft || null;
  }

  function decoderInfo(name) {
    return (meta?.decoders || []).find((d) => d.name === name) || null;
  }

  function applyDraft(d, origin) {
    const base = defaultState(origin);
    if (!d) return base;
    return {
      ...base,
      ...d,
      origin_lat: d.origin_lat ?? origin[0],
      origin_lon: d.origin_lon ?? origin[1],
      source_names: { ...base.source_names, ...(d.source_names || {}) },
      forge_params: { ...base.forge_params, ...(d.forge_params || {}) },
      scale_setup: { ...base.scale_setup, ...(d.scale_setup || {}) },
      report_prefs: { ...base.report_prefs, ...(d.report_prefs || {}) },
    };
  }

  async function open() {
    root.innerHTML = `<div class="wiz-shell"><p class="muted">Loading project wizard…</p></div>`;
    let serverDraft = null;
    try {
      serverDraft = await loadDependencies();
    } catch (e) {
      root.innerHTML = `<div class="wiz-shell"><p class="ms-err" role="alert">Could not load wizard data: ${esc(e.message)}</p></div>`;
      return;
    }
    const origin = meta?.default_origin || [13.8196, 100.5137];
    if (!S) {
      let localDraft = null;
      try { localDraft = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || "null"); } catch { /* ignore */ }
      const chosen = serverDraft || localDraft;
      S = applyDraft(chosen, origin);
      // Drop unavailable decoders from resumed drafts
      S.sources = S.sources.filter((id) => {
        const def = SOURCE_DEFS.find((x) => x.id === id);
        if (!def) return false;
        if (!def.decoder) return true;
        return !!decoderInfo(def.decoder)?.available;
      });
      draftLoaded = !!chosen;
      draftStatus = chosen ? "resumed" : "";
    }
    fieldError = "";
    render(true);
  }

  function validateStep(stepIdx) {
    fieldError = "";
    if (stepIdx === 0) {
      if (!S.name.trim()) {
        fieldError = "Enter a project name to continue.";
        return false;
      }
      if (S.survey_date && !/^\d{4}-\d{2}-\d{2}$/.test(S.survey_date)) {
        fieldError = "Choose a valid survey date.";
        return false;
      }
    }
    if (stepIdx === 1) {
      const la = Number(S.origin_lat), lo = Number(S.origin_lon);
      if (!Number.isFinite(la) || la < -90 || la > 90 || !Number.isFinite(lo) || lo < -180 || lo > 180) {
        fieldError = "Latitude must be between −90 and 90, and longitude between −180 and 180.";
        return false;
      }
    }
    if (stepIdx === 3) {
      const ref = measureRefs.find((r) => r.id === S.scale_setup.measure_ref);
      if (ref?.kind === "line" && S.scale_setup.ref_length_cm != null) {
        const v = Number(S.scale_setup.ref_length_cm);
        if (!(v >= 1 && v <= 10000)) { fieldError = "Ruler length must be between 1 and 10,000 cm."; return false; }
      }
      if (ref?.custom && ref.kind === "rect") {
        const w = S.scale_setup.ref_width_cm, l = S.scale_setup.ref_length_cm;
        if ((w != null && !(w >= 0.5 && w <= 5000)) || (l != null && !(l >= 0.5 && l <= 5000))) {
          fieldError = "Custom rectangle width and length must be between 0.5 and 5,000 cm.";
          return false;
        }
      }
      if (S.scale_setup.camera_height_m != null && !(S.scale_setup.camera_height_m >= 0.2 && S.scale_setup.camera_height_m <= 10)) {
        fieldError = "Camera height must be between 0.2 and 10 m.";
        return false;
      }
      if (S.scale_setup.heading_deg != null && !(S.scale_setup.heading_deg >= 0 && S.scale_setup.heading_deg <= 360)) {
        fieldError = "Heading must be between 0 and 360 degrees.";
        return false;
      }
    }
    return true;
  }

  function goStep(next, focusHeading = true) {
    if (next > S.step && !validateStep(S.step)) {
      render(false);
      root.querySelector("#wizAlert")?.focus();
      return;
    }
    S.step = Math.max(0, Math.min(STEPS.length - 1, next));
    fieldError = "";
    scheduleDraftSave(100);
    render(focusHeading);
  }

  // ------------------------------------------------------------------ step renderers
  function renderStepper() {
    const pct = Math.round(((S.step + 1) / STEPS.length) * 100);
    return `
      <nav class="wiz-stepper" aria-label="Project setup steps">
        <div class="wiz-progress-mobile">
          <span>Step ${S.step + 1} of ${STEPS.length}: <b>${esc(STEPS[S.step].label)}</b></span>
          <div class="wiz-bar" role="progressbar" aria-valuemin="1" aria-valuemax="${STEPS.length}" aria-valuenow="${S.step + 1}" aria-label="Wizard progress"><span style="width:${pct}%"></span></div>
        </div>
        <ol class="wiz-steps">
          ${STEPS.map((st, i) => {
            const done = i < S.step;
            const cur = i === S.step;
            const disabled = i > 0 && !S.name.trim();
            return `<li><button type="button" class="wiz-step${cur ? " now" : done ? " done" : ""}" data-wiz-step="${i}" ${cur ? 'aria-current="step"' : ""} ${disabled ? "disabled" : ""}>
              <span class="wiz-step-n" aria-hidden="true">${done ? CHECK_SVG : i + 1}</span>
              <span class="wiz-step-l">${esc(st.label)}</span>
            </button></li>`;
          }).join("")}
        </ol>
      </nav>`;
  }

  function renderStep0() {
    return `
      <h2 id="wizStepTitle" tabindex="-1">Project basics</h2>
      <p class="muted">Identify the road corridor, client agency and survey date. Everything else can be updated later.</p>
      <div class="wiz-form">
        <label class="field">
          <span>Project name <abbr title="Required">*</abbr></span>
          <input class="input" id="wizName" name="name" required maxlength="120" value="${esc(S.name)}"
            placeholder="Highway 304 resurfacing inspection" aria-invalid="${fieldError && !S.name.trim() ? "true" : "false"}" />
        </label>
        <div class="grid2">
          <label class="field">
            <span>Road or route name</span>
            <input class="input" name="road_name" maxlength="160" value="${esc(S.road_name)}" placeholder="Route 304, km 12–15" />
          </label>
          <label class="field">
            <span>Client or agency</span>
            <input class="input" name="client" maxlength="160" value="${esc(S.client)}" placeholder="Department of Highways — District 4" />
          </label>
        </div>
        <div class="grid2">
          <label class="field">
            <span>Survey date</span>
            <input class="input" name="survey_date" type="date" value="${esc(S.survey_date)}" />
          </label>
          <div></div>
        </div>
        <label class="field">
          <span>Notes <span class="muted small">(${S.notes.length}/2000)</span></span>
          <textarea class="input wiz-textarea" name="notes" rows="4" maxlength="2000" placeholder="Lane closures, weather, crew or inspection scope">${esc(S.notes)}</textarea>
        </label>
      </div>`;
  }

  function renderStep1() {
    const lenM = routeLengthM(S.route);
    const lenTxt = lenM >= 1000 ? `${(lenM / 1000).toFixed(2)} km` : `${Math.round(lenM)} m`;
    return `
      <h2 id="wizStepTitle" tabindex="-1">Project location</h2>
      <p class="muted">Click the map to place the project reference origin, trace a route corridor, or type coordinates directly.</p>
      <div class="wiz-loc-bar">
        <div class="seg" role="group" aria-label="Map pick mode">
          <button type="button" class="seg-btn" data-loc-mode="point" aria-pressed="${S.loc_mode === "point"}">Single point</button>
          <button type="button" class="seg-btn" data-loc-mode="route" aria-pressed="${S.loc_mode === "route"}">Route polyline</button>
        </div>
        <button type="button" class="btn small" data-wiz="gps">Use my location</button>
        ${S.loc_mode === "route" ? `
          <button type="button" class="btn small quiet" data-wiz="route-undo" ${S.route.length ? "" : "disabled"}>Undo point</button>
          <button type="button" class="btn small quiet" data-wiz="route-clear" ${S.route.length ? "" : "disabled"}>Clear route</button>
        ` : ""}
      </div>
      <div class="wiz-map-wrap">
        <div id="wizMap" class="wiz-map" role="application" aria-label="Project location picker map"></div>
        <p class="wiz-map-hint" aria-live="polite">
          ${S.loc_mode === "route"
            ? (S.route.length ? `${S.route.length} waypoints · ${lenTxt}` : "Click along the road to add route waypoints")
            : "Click anywhere on the map to set the reference point"}
        </p>
      </div>
      <div class="grid2 wiz-coords">
        <label class="field">
          <span>Reference latitude</span>
          <input class="input num" name="origin_lat" type="number" step="any" min="-90" max="90" value="${esc(S.origin_lat)}" />
        </label>
        <label class="field">
          <span>Reference longitude</span>
          <input class="input num" name="origin_lon" type="number" step="any" min="-180" max="180" value="${esc(S.origin_lon)}" />
        </label>
      </div>
      <p class="muted small">All 3D distances and survey alignments are measured in metres from this reference point.</p>`;
  }

  function renderStep2() {
    const resumeBanner = S.had_files && !hasFiles()
      ? `<p class="wiz-banner" role="status">Your draft was restored, but local files are not kept after leaving the page. Re-attach any files you want to upload.</p>`
      : "";
    const cards = SOURCE_DEFS.map((def) => {
      const dec = def.decoder ? decoderInfo(def.decoder) : null;
      const available = def.decoder ? !!dec?.available : true;
      const checked = available && S.sources.includes(def.id);
      const files = filesBySource[def.id] || [];
      const totalBytes = files.reduce((t, f) => t + f.size, 0);
      const badPhotos = def.id === "photos" ? files.filter((f) => f.size > MAX_PHOTO_MB * 1024 * 1024).length : 0;
      return `
        <div class="wiz-source${checked ? " on" : ""}${available ? "" : " off"}">
          <label class="wiz-source-head">
            <input type="checkbox" data-source-toggle="${esc(def.id)}" ${checked ? "checked" : ""} ${available ? "" : "disabled"} />
            <span class="wiz-source-meta">
              <b>${esc(def.title)}</b>
              <span class="muted small">${esc(def.subtitle)}</span>
            </span>
            <span class="wiz-pill ${available ? "ok" : "off"}">${available ? "Available" : "Unavailable"}</span>
          </label>
          ${!available && dec?.unavailable_reason ? `<p class="wiz-unavail small">${esc(dec.unavailable_reason)}</p>` : ""}
          ${checked ? `
            <div class="wiz-source-body">
              ${def.id !== "photos" ? `
                <label class="field">
                  <span>Survey name</span>
                  <input class="input" data-source-name="${esc(def.id)}" maxlength="120" value="${esc(S.source_names[def.id] || def.defaultName)}" />
                </label>` : ""}
              ${def.accept ? `
                <label class="field">
                  <span>Files</span>
                  <input class="input" type="file" data-source-files="${esc(def.id)}" accept="${esc(def.accept)}" multiple />
                </label>
                <p class="muted small">${esc(def.fileHint)}</p>
                ${files.length ? `
                  <div class="wiz-files" data-no-i18n>
                    <p class="small"><b>${files.length}</b> ${files.length === 1 ? "file" : "files"} (${fmtBytes(totalBytes)})</p>
                    ${def.id === "photos" ? `<div class="wiz-thumbs">${files.map((f, idx) => `
                      <figure class="wiz-thumb">
                        <img src="${photoUrlFor(f)}" alt="${esc(f.name)}" />
                        <figcaption><span>${esc(f.name)}</span><button type="button" class="btn small quiet" data-rm-file="photos:${idx}" aria-label="Remove ${esc(f.name)}">✕</button></figcaption>
                      </figure>`).join("")}</div>`
                    : `<ul class="wiz-filelist">${files.map((f, idx) => `
                      <li><span>${esc(f.name)} <small class="muted">(${fmtBytes(f.size)})</small></span>
                      <button type="button" class="btn small quiet" data-rm-file="${esc(def.id)}:${idx}" aria-label="Remove ${esc(f.name)}">✕</button></li>`).join("")}</ul>`}
                    ${badPhotos ? `<p class="ms-err" role="alert">${badPhotos} photo(s) exceed the ${MAX_PHOTO_MB} MB upload cap and will be refused by the server.</p>` : ""}
                  </div>` : ""}
              ` : `<p class="muted small">Ready to generate a synthetic street on confirm.</p>`}
              ${def.id === "forge_slam" ? `
                <details class="adv">
                  <summary>FORGE SLAM parameters</summary>
                  <div class="grid2">
                    <label class="field"><span>Keyframe spacing (m, 0.2–10)</span>
                      <input class="input num" type="number" step="0.1" min="0.2" max="10" data-forge="keyframe_dist_m" value="${esc(S.forge_params.keyframe_dist_m)}" /></label>
                    <label class="field"><span>Voxel size (m, 0.02–1)</span>
                      <input class="input num" type="number" step="0.01" min="0.02" max="1" data-forge="voxel_size_m" value="${esc(S.forge_params.voxel_size_m)}" /></label>
                    <label class="field"><span>RAM tile budget (MB, 16–2048)</span>
                      <input class="input num" type="number" step="32" min="16" max="2048" data-forge="max_ram_mb" value="${Math.round((S.forge_params.max_ram_bytes || 512 * 1024 * 1024) / (1024 * 1024))}" /></label>
                    <div class="wiz-checks">
                      <label class="check"><input type="checkbox" data-forge="enable_dynamic_filter" ${S.forge_params.enable_dynamic_filter ? "checked" : ""} /> <span>Remove moving objects</span></label>
                      <label class="check"><input type="checkbox" data-forge="enable_loop_closure" ${S.forge_params.enable_loop_closure ? "checked" : ""} /> <span>Loop closure</span></label>
                      <label class="check"><input type="checkbox" data-forge="enable_thermal" ${S.forge_params.enable_thermal ? "checked" : ""} /> <span>Radiometric thermal (°C)</span></label>
                    </div>
                  </div>
                </details>` : ""}
            </div>` : ""}
        </div>`;
    }).join("");

    return `
      <h2 id="wizStepTitle" tabindex="-1">Data sources</h2>
      <p class="muted">Choose one or more inputs to upload when the project is created, or continue without files to add surveys later.</p>
      ${resumeBanner}
      <div class="wiz-sources">${cards}</div>`;
  }

  function renderStep3() {
    const ss = S.scale_setup;
    const chosenRef = measureRefs.find((r) => r.id === ss.measure_ref) || measureRefs[0];
    const photos = filesBySource.photos || [];
    const grouped = {};
    for (const o of sceneCatalog) {
      if (o.custom) continue;
      (grouped[o.group || "other"] ||= []).push(o);
    }
    const lang = getLang();
    return `
      <h2 id="wizStepTitle" tabindex="-1">Scale & measurement setup</h2>
      <p class="muted">Pick your field reference object for photo measuring and standard road objects for 3D scene-scale calibration.</p>

      <section class="wiz-sub">
        <h3>Reference object for photo measurement</h3>
        <div class="ms-refs" role="radiogroup" aria-label="Default reference object">
          ${measureRefs.map((r) => {
            const dims = r.kind === "rect" && !r.custom ? `${(r.width_m * 100).toFixed(1)} × ${(r.length_m * 100).toFixed(1)} cm` : "";
            const on = ss.measure_ref === r.id;
            return `<label class="ms-ref${on ? " on" : ""}">
              <input type="radio" name="wiz-mref" value="${esc(r.id)}" ${on ? "checked" : ""} />
              <span><b>${esc(r.label)}</b>${dims ? `<small>${esc(dims)}</small>` : ""}</span>
            </label>`;
          }).join("")}
        </div>
        ${chosenRef?.custom && chosenRef.kind === "rect" ? `
          <div class="grid2">
            <label class="field"><span>Reference width (cm)</span><input class="input num" type="number" step="0.1" min="0.5" max="5000" data-scale="ref_width_cm" value="${esc(ss.ref_width_cm ?? "")}" /></label>
            <label class="field"><span>Reference length (cm)</span><input class="input num" type="number" step="0.1" min="0.5" max="5000" data-scale="ref_length_cm" value="${esc(ss.ref_length_cm ?? "")}" /></label>
          </div>` : ""}
        ${chosenRef?.kind === "line" ? `
          <label class="field"><span>Ruler or tape length (cm)</span><input class="input num" type="number" step="0.1" min="1" max="10000" data-scale="ref_length_cm" value="${esc(ss.ref_length_cm ?? "")}" /></label>` : ""}

        <div class="wiz-measure-box">
          <div>
            <b>Interactive photo measurement</b>
            <p class="muted small">Open the full homography measuring sheet on a site photo to verify reference calibration before creating the project.</p>
          </div>
          <div class="wiz-measure-acts">
            ${photos.length ? `<button type="button" class="btn small" data-wiz="test-measure">Test measure on attached photo</button>` : ""}
            <label class="btn small quiet wiz-file-btn"><span>Pick a photo to measure</span><input type="file" accept="image/*" id="wizTestPhoto" hidden /></label>
          </div>
        </div>
        ${ss.sample_measurement ? `
          <p class="wiz-banner ok" role="status">
            Sample measurement: <b>${ss.sample_measurement.area_m2.toFixed(2)} m²</b>
            (${(ss.sample_measurement.width_m * 100).toFixed(0)} × ${(ss.sample_measurement.length_m * 100).toFixed(0)} cm,
            ${esc(ss.sample_measurement.ref_label)}${ss.sample_measurement.pct_area != null ? ` ±${Math.round(ss.sample_measurement.pct_area)}%` : ""})
            <button type="button" class="btn small quiet" data-wiz="clear-sample">Clear</button>
          </p>` : ""}
      </section>

      <section class="wiz-sub">
        <h3>Scene-scale calibration objects</h3>
        <p class="muted small">Select road objects your crew expects to see in 3D video clips. Frame-tapping calibration runs via <b>Fix scale with scene objects</b> once clips finish processing.</p>
        <div class="wiz-scene-groups">
          ${Object.entries(grouped).map(([g, objs]) => `
            <div class="wiz-scene-group">
              <p class="ss-gh">${esc(GROUP_LABELS[g] || g)}</p>
              <div class="wiz-scene-list">
                ${objs.map((o) => {
                  const on = ss.scene_ref_ids.includes(o.id);
                  const lbl = lang === "th" && o.label_th ? o.label_th : o.label;
                  const sizeTxt = o.size_m >= 1 ? `${o.size_m.toFixed(2)} m` : `${Math.round(o.size_m * 100)} cm`;
                  return `<label class="wiz-chip-check${on ? " on" : ""}">
                    <input type="checkbox" data-scene-ref="${esc(o.id)}" ${on ? "checked" : ""} />
                    <span><b>${esc(lbl)}</b> <small class="muted">${esc(sizeTxt)}</small></span>
                  </label>`;
                }).join("")}
              </div>
            </div>`).join("")}
        </div>
      </section>

      <section class="wiz-sub">
        <h3>Default camera & placement fallback</h3>
        <p class="muted small">Used when a survey has no GPS track or is not already metric.</p>
        <div class="grid2">
          <label class="field"><span>Camera height above road (m)</span>
            <input class="input num" type="number" step="0.05" min="0.2" max="10" data-scale="camera_height_m" value="${esc(ss.camera_height_m ?? "")}" placeholder="1.4" /></label>
          <label class="field"><span>Heading at start (degrees)</span>
            <input class="input num" type="number" step="1" min="0" max="360" data-scale="heading_deg" value="${esc(ss.heading_deg ?? "")}" placeholder="0 is north" /></label>
          <label class="field"><span>Up axis</span>
            <select class="input" data-scale="up_axis">
              ${[["", "Detect"], ["z", "z"], ["y", "y"], ["-y", "-y"]].map(([v, l]) => `<option value="${v}" ${ss.up_axis === v ? "selected" : ""}>${l}</option>`).join("")}
            </select></label>
          <label class="check wiz-align-end"><input type="checkbox" data-scale="metric" ${ss.metric ? "checked" : ""} /> <span>Coordinates are already in metres</span></label>
        </div>
      </section>`;
  }

  function renderStep4() {
    const rp = S.report_prefs;
    const mats = materialsData;
    const sym = mats?.symbol || "฿";
    return `
      <h2 id="wizStepTitle" tabindex="-1">Materials & report preferences</h2>
      <p class="muted">Configure DOH repair material estimates, display units and default export formats for this project.</p>

      <section class="wiz-sub">
        <h3>Units & exports</h3>
        <div class="wiz-prefs-row">
          <div>
            <p class="field-lbl">Measurement units</p>
            <div class="seg" role="group" aria-label="Measurement units">
              <button type="button" class="seg-btn" data-units="metric" aria-pressed="${rp.units === "metric"}">Metric (m, cm, kg)</button>
              <button type="button" class="seg-btn" data-units="imperial" aria-pressed="${rp.units === "imperial"}">Imperial (ft, in)</button>
            </div>
            <p class="muted small">3D point clouds and GeoJSON coordinates are always stored in SI metres / WGS84.</p>
          </div>
          <div>
            <p class="field-lbl">Preferred export formats</p>
            <div class="wiz-checks-inline">
              ${[["csv", "CSV spreadsheet"], ["geojson", "GeoJSON map"], ["ply", "3D point cloud (.ply)"]].map(([id, lbl]) => `
                <label class="check"><input type="checkbox" data-export-fmt="${id}" ${rp.export_formats.includes(id) ? "checked" : ""} /> <span>${lbl}</span></label>
              `).join("")}
            </div>
          </div>
        </div>
      </section>

      <section class="wiz-sub">
        <h3>DOH pothole repair materials</h3>
        <label class="check">
          <input type="checkbox" data-pref="include_doh_materials" ${rp.include_doh_materials ? "checked" : ""} />
          <span>Include DOH Road Maintenance Manual (2006) materials bill in job cards and reports</span>
        </label>
        <div class="seg" role="group" aria-label="Material rate source">
          <button type="button" class="seg-btn" data-mat-preset="company" aria-pressed="${rp.materials_preset === "company"}">Company DOH rates</button>
          <button type="button" class="seg-btn" data-mat-preset="doh_defaults" aria-pressed="${rp.materials_preset === "doh_defaults"}">Standard DOH defaults</button>
        </div>
        ${mats ? `
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>Material</th><th>Unit</th><th class="num">Price (${esc(sym)})</th></tr></thead>
              <tbody>
                ${Object.entries(mats.materials).map(([k, m]) => {
                  const curPrice = adminMatDraft?.[k]?.price ?? m.price;
                  const curBag = adminMatDraft?.[k]?.bag_kg ?? m.bag_kg;
                  return `<tr>
                    <td><b>${esc(m.label)}</b>${m.label_th ? `<br><span class="muted small" data-no-i18n>${esc(m.label_th)}</span>` : ""}</td>
                    <td>${k === "cold_mix"
                      ? (mats.editable
                        ? `bag of <input class="input num tiny" type="number" min="1" max="100" step="any" data-adm-mat="${k}.bag_kg" value="${esc(curBag)}" aria-label="Bag weight in kg"> kg`
                        : `bag of ${esc(m.bag_kg)} kg`)
                      : esc(m.unit)}</td>
                    <td class="num">${mats.editable
                      ? `<input class="input num" type="number" min="0" step="any" data-adm-mat="${k}.price" value="${esc(curPrice)}" aria-label="${esc(m.label)} price">`
                      : (m.price ? Number(m.price).toLocaleString() : "Not set")}</td>
                  </tr>`;
                }).join("")}
              </tbody>
            </table>
          </div>
          <p class="muted small">${mats.editable
            ? "As admin, changes to these prices will also update your company's material rates when you create the project."
            : "Company prices are managed by an admin in Settings."}</p>
        ` : `<p class="muted small">Material rates could not be loaded right now; server defaults will be used.</p>`}
      </section>`;
  }

  function renderStep5() {
    const ss = S.scale_setup;
    const rp = S.report_prefs;
    const refObj = measureRefs.find((r) => r.id === ss.measure_ref);
    const lenM = routeLengthM(S.route);
    const missingFiles = S.sources.filter((id) => {
      const def = SOURCE_DEFS.find((x) => x.id === id);
      return def?.needsFiles && !(filesBySource[id]?.length);
    });

    return `
      <h2 id="wizStepTitle" tabindex="-1">Review & create</h2>
      <p class="muted">Check every detail before creating the project. Use Edit on any section to make changes.</p>

      ${missingFiles.length ? `
        <p class="wiz-banner warn" role="alert">
          These selected sources have no files attached yet and will be skipped unless you attach files:
          <b>${missingFiles.map((id) => esc(SOURCE_DEFS.find((x) => x.id === id)?.title || id)).join(", ")}</b>.
          <button type="button" class="btn small quiet" data-wiz-step="2">Attach files</button>
        </p>` : ""}

      <div class="wiz-review">
        <section class="wiz-rev-card">
          <div class="wiz-rev-head"><h3>Basics</h3><button type="button" class="btn small quiet" data-wiz-step="0">Edit</button></div>
          <dl class="wiz-dl">
            <dt>Project name</dt><dd data-no-i18n>${esc(S.name)}</dd>
            ${S.road_name ? `<dt>Road / route</dt><dd data-no-i18n>${esc(S.road_name)}</dd>` : ""}
            ${S.client ? `<dt>Client / agency</dt><dd data-no-i18n>${esc(S.client)}</dd>` : ""}
            ${S.survey_date ? `<dt>Survey date</dt><dd data-no-i18n>${esc(S.survey_date)}</dd>` : ""}
            ${S.notes ? `<dt>Notes</dt><dd data-no-i18n>${esc(S.notes)}</dd>` : ""}
          </dl>
        </section>

        <section class="wiz-rev-card">
          <div class="wiz-rev-head"><h3>Location</h3><button type="button" class="btn small quiet" data-wiz-step="1">Edit</button></div>
          <dl class="wiz-dl">
            <dt>Reference origin</dt><dd data-no-i18n>${Number(S.origin_lat).toFixed(6)}, ${Number(S.origin_lon).toFixed(6)}</dd>
            <dt>Route</dt><dd>${S.route.length >= 2
              ? `${S.route.length} waypoints (${lenM >= 1000 ? `${(lenM / 1000).toFixed(2)} km` : `${Math.round(lenM)} m`})`
              : "Single origin point"}</dd>
          </dl>
        </section>

        <section class="wiz-rev-card">
          <div class="wiz-rev-head"><h3>Data sources</h3><button type="button" class="btn small quiet" data-wiz-step="2">Edit</button></div>
          ${S.sources.length ? `<ul class="wiz-rev-list">${S.sources.map((id) => {
            const def = SOURCE_DEFS.find((x) => x.id === id);
            const files = filesBySource[id] || [];
            const bytes = files.reduce((t, f) => t + f.size, 0);
            return `<li><b>${esc(def?.title || id)}</b>${def?.needsFiles
              ? ` — ${files.length ? `<span>${files.length} ${files.length === 1 ? "file" : "files"} (${fmtBytes(bytes)})</span>` : `<span class="muted">No files attached</span>`}`
              : id === "photos"
                ? ` — <span>${files.length} ${files.length === 1 ? "photo" : "photos"}</span>`
                : ` — <span>Synthetic sample data</span>`}</li>`;
          }).join("")}</ul>` : `<p class="muted small">No initial uploads — creates the project ready for surveys later.</p>`}
        </section>

        <section class="wiz-rev-card">
          <div class="wiz-rev-head"><h3>Scale & measurement</h3><button type="button" class="btn small quiet" data-wiz-step="3">Edit</button></div>
          <dl class="wiz-dl">
            <dt>Reference object</dt><dd>${esc(refObj?.label || "None")}</dd>
            <dt>Scene-scale objects</dt><dd>${ss.scene_ref_ids.length ? `${ss.scene_ref_ids.length} selected` : "None selected"}</dd>
            <dt>Camera height</dt><dd data-no-i18n>${ss.camera_height_m != null ? `${ss.camera_height_m} m` : "Default (1.4 m)"}</dd>
            ${ss.sample_measurement ? `<dt>Sample test</dt><dd data-no-i18n>${ss.sample_measurement.area_m2.toFixed(2)} m² (${esc(ss.sample_measurement.ref_label)})</dd>` : ""}
          </dl>
        </section>

        <section class="wiz-rev-card">
          <div class="wiz-rev-head"><h3>Materials & report</h3><button type="button" class="btn small quiet" data-wiz-step="4">Edit</button></div>
          <dl class="wiz-dl">
            <dt>Units</dt><dd>${rp.units === "imperial" ? "Imperial display" : "Metric (m, cm, kg)"}</dd>
            <dt>DOH materials</dt><dd>${rp.include_doh_materials ? (rp.materials_preset === "doh_defaults" ? "Standard DOH defaults" : "Company DOH rates") : "Excluded"}</dd>
            <dt>Export formats</dt><dd data-no-i18n>${rp.export_formats.length ? rp.export_formats.map((x) => x.toUpperCase()).join(", ") : "None"}</dd>
          </dl>
        </section>
      </div>

      <div class="wiz-submit-log" id="wizSubmitLog" role="status" aria-live="polite" hidden></div>`;
  }

  function render(focusHeading = false) {
    pickMap = null;
    const stepBody = [renderStep0, renderStep1, renderStep2, renderStep3, renderStep4, renderStep5][S.step]();
    const isLast = S.step === STEPS.length - 1;
    const willProcess = S.sources.some((id) => {
      const def = SOURCE_DEFS.find((x) => x.id === id);
      return id === "demo" || (def?.needsFiles && (filesBySource[id]?.length || 0) > 0) || (id === "photos" && (filesBySource.photos?.length || 0) > 0);
    });

    root.innerHTML = `
      <div class="wiz-shell">
        <header class="wiz-head">
          <div>
            <h1>Create project</h1>
            <p class="muted small" id="wizDraftStatus" role="status" aria-live="polite"></p>
          </div>
          <div class="wiz-head-acts">
            <button type="button" class="btn small quiet" id="wizDiscardBtn" data-wiz="discard" hidden>Discard draft</button>
            <button type="button" class="btn small quiet" data-wiz="cancel">Back to workspace</button>
          </div>
        </header>
        ${renderStepper()}
        ${fieldError ? `<p class="ms-err" id="wizAlert" role="alert" tabindex="-1">${esc(fieldError)}</p>` : ""}
        <section class="panel wiz-card" aria-labelledby="wizStepTitle">
          ${stepBody}
        </section>
        <footer class="wiz-foot">
          <button type="button" class="btn" data-wiz="prev" ${S.step === 0 || submitting ? "disabled" : ""}>Back</button>
          <div class="spacer"></div>
          <button type="button" class="btn quiet" data-wiz="save-draft" ${submitting ? "disabled" : ""}>Save draft</button>
          ${isLast
            ? `<button type="button" class="btn primary" id="wizConfirmBtn" data-wiz="confirm" ${submitting ? "disabled" : ""}>${willProcess ? "Create project & start" : "Create project"}</button>`
            : `<button type="button" class="btn primary" data-wiz="next">Next</button>`}
        </footer>
      </div>`;

    setDraftBadge(draftStatus);

    if (S.step === 1) mountLocationMap();
    if (focusHeading) root.querySelector("#wizStepTitle")?.focus({ preventScroll: true });
  }

  function mountLocationMap() {
    const el = root.querySelector("#wizMap");
    if (!el) return;
    const lat = Number(S.origin_lat) || 13.8196;
    const lon = Number(S.origin_lon) || 100.5137;
    pickMap = createMap(el, {
      center: [lon, lat],
      onMapClick: (clickLat, clickLon) => {
        const la = Number(clickLat.toFixed(6));
        const lo = Number(clickLon.toFixed(6));
        if (S.loc_mode === "route") {
          if (S.route.length >= 200) return ctx.toast("Maximum of 200 route waypoints reached.", true);
          S.route = [...S.route, [la, lo]];
          if (S.route.length === 1) {
            S.origin_lat = la;
            S.origin_lon = lo;
          }
        } else {
          S.origin_lat = la;
          S.origin_lon = lo;
        }
        syncLocationInputs();
        updatePickOverlay();
        scheduleDraftSave();
      },
    });
    pickMap.setPinMode(true);
    pickMap.ensureView(lat, lon);
    updatePickOverlay();
    requestAnimationFrame(() => pickMap?.resize());
  }

  function updatePickOverlay() {
    if (!pickMap) return;
    const la = Number(S.origin_lat), lo = Number(S.origin_lon);
    const origin = Number.isFinite(la) && Number.isFinite(lo) ? { lat: la, lon: lo } : null;
    pickMap.setPick(origin, S.loc_mode === "route" ? S.route : []);
    const hint = root.querySelector(".wiz-map-hint");
    if (hint) {
      if (S.loc_mode === "route") {
        const lenM = routeLengthM(S.route);
        const lenTxt = lenM >= 1000 ? `${(lenM / 1000).toFixed(2)} km` : `${Math.round(lenM)} m`;
        hint.textContent = S.route.length ? `${S.route.length} waypoints · ${lenTxt}` : "Click along the road to add route waypoints";
      } else {
        hint.textContent = origin ? `Selected ${origin.lat.toFixed(5)}, ${origin.lon.toFixed(5)}` : "Click anywhere on the map to set the reference point";
      }
    }
    const undoBtn = root.querySelector('[data-wiz="route-undo"]');
    const clearBtn = root.querySelector('[data-wiz="route-clear"]');
    if (undoBtn) undoBtn.disabled = !S.route.length;
    if (clearBtn) clearBtn.disabled = !S.route.length;
  }

  function syncLocationInputs() {
    const laEl = root.querySelector('input[name="origin_lat"]');
    const loEl = root.querySelector('input[name="origin_lon"]');
    if (laEl) laEl.value = S.origin_lat;
    if (loEl) loEl.value = S.origin_lon;
  }

  // ------------------------------------------------------------------ submit flow
  function uploadSurveyWithProgress(pid, fd, onPct) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable && onPct) onPct(Math.round((100 * ev.loaded) / ev.total)); };
      xhr.onload = () => {
        if (xhr.status >= 300) {
          let msg = xhr.statusText;
          try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* keep */ }
          return reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
        }
        resolve(JSON.parse(xhr.responseText));
      };
      xhr.onerror = () => reject(new Error("Upload failed. Check the connection and try again."));
      xhr.open("POST", `/api/projects/${pid}/surveys`);
      xhr.setRequestHeader("X-Civil-Scan", "1");
      xhr.send(fd);
    });
  }

  async function submitWizard() {
    if (submitting) return;
    if (!validateStep(0)) { goStep(0); return; }
    if (!validateStep(1)) { goStep(1); return; }
    if (!validateStep(3)) { goStep(3); return; }

    submitting = true;
    const btn = root.querySelector("#wizConfirmBtn");
    const log = root.querySelector("#wizSubmitLog");
    if (btn) { btn.disabled = true; btn.textContent = "Creating…"; }
    if (log) { log.hidden = false; log.textContent = "Creating project…"; }

    let createdProj = null;
    let firstVideo = false;
    const failures = [];

    try {
      // 1. Optional admin company material price update
      if (materialsData?.editable && adminMatDraft && Object.keys(adminMatDraft).length) {
        if (log) log.textContent = "Saving company material rates…";
        await ctx.api("/api/settings/materials", { method: "PUT", body: JSON.stringify({ materials: adminMatDraft }) });
      }

      // 2. Create the project with validated metadata
      const body = {
        name: S.name.trim(),
        origin_lat: Number(S.origin_lat),
        origin_lon: Number(S.origin_lon),
        road_name: S.road_name.trim(),
        client: S.client.trim(),
        survey_date: S.survey_date || "",
        notes: S.notes.trim(),
        route: S.loc_mode === "route" ? S.route : [],
        scale_setup: S.scale_setup,
        report_prefs: S.report_prefs,
      };
      createdProj = await ctx.api("/api/projects", { method: "POST", body: JSON.stringify(body) });
      const pid = createdProj.id;

      // 3. Upload selected survey sources using existing /api/projects/{pid}/surveys
      const baseSurveyParams = {};
      if (S.scale_setup.camera_height_m != null) baseSurveyParams.camera_height_m = Number(S.scale_setup.camera_height_m);
      if (S.scale_setup.heading_deg != null) baseSurveyParams.heading_deg = Number(S.scale_setup.heading_deg);
      if (S.scale_setup.up_axis) baseSurveyParams.up_axis = S.scale_setup.up_axis;
      if (S.scale_setup.metric) baseSurveyParams.metric = true;

      for (const srcId of S.sources) {
        if (srcId === "photos") continue;
        const def = SOURCE_DEFS.find((x) => x.id === srcId);
        if (!def) continue;
        const files = filesBySource[srcId] || [];
        if (def.needsFiles && !files.length) continue;

        const svName = (S.source_names[srcId] || def.defaultName || def.title).trim();
        const prm = { ...baseSurveyParams };
        if (srcId === "forge_slam") prm.forge = S.forge_params;
        const fd = new FormData();
        fd.append("name", svName);
        fd.append("decoder", def.decoder);
        fd.append("params", JSON.stringify(prm));
        for (const f of files) fd.append("files", f, f.name);

        if (log) log.textContent = `Uploading ${svName}…`;
        try {
          await uploadSurveyWithProgress(pid, fd, (pct) => {
            if (log) log.textContent = `Uploading ${svName} (${pct}%)…`;
          });
          if (srcId === "pothole_video") firstVideo = true;
        } catch (err) {
          failures.push(`${svName}: ${err.message}`);
        }
      }

      // 4. Upload attached site photos using /api/projects/{pid}/photos (15 MB + 60 MP guard)
      if (S.sources.includes("photos")) {
        const photos = filesBySource.photos || [];
        for (let i = 0; i < photos.length; i++) {
          if (log) log.textContent = `Uploading photo ${i + 1} of ${photos.length}…`;
          const fd = new FormData();
          fd.append("file", photos[i], photos[i].name);
          try {
            await ctx.api(`/api/projects/${pid}/photos`, { method: "POST", body: fd });
          } catch (err) {
            failures.push(`${photos[i].name}: ${err.message}`);
          }
        }
      }

      // 5. Clear draft & reset local wizard state
      await ctx.api("/api/project-draft", { method: "DELETE" }).catch(() => {});
      clearLocal();
      revokePhotoUrls();
      S = null;
      filesBySource = {};
      adminMatDraft = null;
      draftStatus = "";
      submitting = false;

      if (failures.length) {
        ctx.toast(`Project created, but some uploads failed: ${failures.join("; ")}`, true);
      } else {
        ctx.toast(`Created project ${createdProj.name}.`);
      }
      await ctx.onCreated(createdProj.id, { openVideo: firstVideo });
    } catch (err) {
      submitting = false;
      if (btn) { btn.disabled = false; btn.textContent = "Create project"; }
      if (log) log.hidden = true;
      fieldError = err.message;
      render(false);
      root.querySelector("#wizAlert")?.focus();
    }
  }

  // ------------------------------------------------------------------ interactive photo measure
  function launchPhotoMeasure(file) {
    if (!file) return;
    const url = photoUrlFor(file);
    const ss = S.scale_setup;
    ctx.openMeasure({
      image: url,
      title: file.name,
      toast: ctx.toast,
      initialRef: ss.measure_ref || "a4",
      initialCustomW: ss.ref_width_cm != null ? String(ss.ref_width_cm) : "",
      initialCustomL: ss.ref_length_cm != null ? String(ss.ref_length_cm) : "",
      initialRulerL: ss.ref_length_cm != null ? String(ss.ref_length_cm) : "",
      onSelect: (res) => {
        const r = res?.result;
        if (!r) return;
        S.scale_setup.measure_ref = r.ref.type;
        S.scale_setup.sample_measurement = {
          ref_label: r.ref.label,
          area_m2: Number(r.area_m2),
          width_m: Number(r.width_m),
          length_m: Number(r.length_m),
          pct_area: r.pct?.area_m2 != null ? Number(r.pct.area_m2) : null,
        };
        scheduleDraftSave(100);
        render(false);
        ctx.toast(`Saved sample measurement (${r.area_m2.toFixed(2)} m²) to project setup.`);
      },
    }).catch((e) => ctx.toast(e.message, true));
  }

  // ------------------------------------------------------------------ delegated event handling
  root.addEventListener("click", async (e) => {
    if (!S || submitting) return;
    const stepBtn = e.target.closest("[data-wiz-step]");
    if (stepBtn && !stepBtn.disabled) {
      return goStep(Number(stepBtn.dataset.wizStep));
    }
    const locBtn = e.target.closest("[data-loc-mode]");
    if (locBtn) {
      S.loc_mode = locBtn.dataset.locMode;
      scheduleDraftSave();
      render(false);
      return;
    }
    const unitsBtn = e.target.closest("[data-units]");
    if (unitsBtn) {
      S.report_prefs.units = unitsBtn.dataset.units;
      scheduleDraftSave();
      render(false);
      return;
    }
    const matBtn = e.target.closest("[data-mat-preset]");
    if (matBtn) {
      S.report_prefs.materials_preset = matBtn.dataset.matPreset;
      scheduleDraftSave();
      render(false);
      return;
    }
    const rmBtn = e.target.closest("[data-rm-file]");
    if (rmBtn) {
      const [srcId, idxStr] = rmBtn.dataset.rmFile.split(":");
      const arr = filesBySource[srcId] || [];
      arr.splice(Number(idxStr), 1);
      filesBySource[srcId] = arr;
      scheduleDraftSave();
      render(false);
      return;
    }
    const act = e.target.closest("[data-wiz]")?.dataset.wiz;
    if (!act) return;
    if (act === "next") return goStep(S.step + 1);
    if (act === "prev") return goStep(S.step - 1);
    if (act === "confirm") return submitWizard();
    if (act === "cancel") return ctx.onCancel();
    if (act === "save-draft") {
      scheduleDraftSave(0);
      ctx.toast("Draft saved.");
      return;
    }
    if (act === "discard") {
      clearTimeout(saveTimer);
      await ctx.api("/api/project-draft", { method: "DELETE" }).catch(() => {});
      clearLocal();
      revokePhotoUrls();
      filesBySource = {};
      adminMatDraft = null;
      S = defaultState(meta?.default_origin || [13.8196, 100.5137]);
      draftStatus = "";
      fieldError = "";
      render(true);
      ctx.toast("Draft cleared.");
      return;
    }
    if (act === "route-undo") {
      S.route = S.route.slice(0, -1);
      if (S.route.length) { S.origin_lat = S.route[0][0]; S.origin_lon = S.route[0][1]; syncLocationInputs(); }
      updatePickOverlay();
      scheduleDraftSave();
      return;
    }
    if (act === "route-clear") {
      S.route = [];
      updatePickOverlay();
      scheduleDraftSave();
      return;
    }
    if (act === "gps") {
      try {
        if (!(await ctx.loc.ensure("Use your device GPS to set the project location."))) return;
        const fix = ctx.loc.fix();
        if (fix) {
          S.origin_lat = Number(fix.lat.toFixed(6));
          S.origin_lon = Number(fix.lon.toFixed(6));
          if (S.loc_mode === "route" && !S.route.length) S.route = [[S.origin_lat, S.origin_lon]];
          syncLocationInputs();
          pickMap?.flyTo({ lat: S.origin_lat, lon: S.origin_lon });
          updatePickOverlay();
          scheduleDraftSave();
        } else {
          ctx.toast("Finding your position…");
          const off = ctx.loc.onChange((g) => {
            if (g && !g.stale) {
              off();
              S.origin_lat = Number(g.lat.toFixed(6));
              S.origin_lon = Number(g.lon.toFixed(6));
              syncLocationInputs();
              pickMap?.flyTo({ lat: S.origin_lat, lon: S.origin_lon });
              updatePickOverlay();
              scheduleDraftSave();
            }
          });
          setTimeout(off, 15000);
        }
      } catch (err) { ctx.toast(err.message, true); }
      return;
    }
    if (act === "test-measure") {
      const f = (filesBySource.photos || [])[0];
      if (f) launchPhotoMeasure(f);
      return;
    }
    if (act === "clear-sample") {
      S.scale_setup.sample_measurement = null;
      scheduleDraftSave();
      render(false);
    }
  });

  root.addEventListener("input", (e) => {
    if (!S || submitting) return;
    const t = e.target;
    if (t.name === "name" || t.name === "road_name" || t.name === "client" || t.name === "survey_date" || t.name === "notes") {
      S[t.name] = t.value;
      if (t.name === "notes") {
        const span = t.closest(".field")?.querySelector("span .muted");
        if (span) span.textContent = `(${S.notes.length}/2000)`;
      }
      if (t.name === "name" && fieldError) {
        fieldError = "";
        root.querySelector("#wizAlert")?.remove();
        t.setAttribute("aria-invalid", "false");
        root.querySelectorAll(".wiz-step").forEach((b, i) => { if (i > 0) b.disabled = !S.name.trim(); });
      }
      scheduleDraftSave();
      return;
    }
    if (t.name === "origin_lat" || t.name === "origin_lon") {
      S[t.name] = t.value === "" ? "" : Number(t.value);
      const la = Number(S.origin_lat), lo = Number(S.origin_lon);
      if (Number.isFinite(la) && Number.isFinite(lo) && la >= -90 && la <= 90 && lo >= -180 && lo <= 180) {
        pickMap?.flyTo({ lat: la, lon: lo });
        updatePickOverlay();
      }
      scheduleDraftSave();
      return;
    }
    if (t.dataset.sourceName) {
      S.source_names[t.dataset.sourceName] = t.value;
      scheduleDraftSave();
      return;
    }
    if (t.dataset.forge) {
      const k = t.dataset.forge;
      if (k === "max_ram_mb") S.forge_params.max_ram_bytes = Math.round(Number(t.value) * 1024 * 1024);
      else if (t.type === "checkbox") S.forge_params[k] = t.checked;
      else S.forge_params[k] = Number(t.value);
      scheduleDraftSave();
      return;
    }
    if (t.dataset.scale) {
      const k = t.dataset.scale;
      if (t.type === "checkbox") S.scale_setup[k] = t.checked;
      else if (t.tagName === "SELECT") S.scale_setup[k] = t.value;
      else S.scale_setup[k] = t.value === "" ? null : Number(t.value);
      scheduleDraftSave();
      return;
    }
    if (t.dataset.admMat) {
      const [matKey, field] = t.dataset.admMat.split(".");
      adminMatDraft ||= {};
      adminMatDraft[matKey] ||= {};
      if (t.value !== "") adminMatDraft[matKey][field] = Number(t.value);
    }
  });

  root.addEventListener("change", (e) => {
    if (!S || submitting) return;
    const t = e.target;
    if (t.dataset.sourceToggle) {
      const id = t.dataset.sourceToggle;
      if (t.checked) { if (!S.sources.includes(id)) S.sources = [...S.sources, id]; }
      else { S.sources = S.sources.filter((x) => x !== id); }
      scheduleDraftSave();
      render(false);
      return;
    }
    if (t.dataset.sourceFiles) {
      const id = t.dataset.sourceFiles;
      let list = [...(t.files || [])];
      if (id === "photos" && list.length > MAX_PHOTOS) {
        ctx.toast(`Kept the first ${MAX_PHOTOS} photos (project photo limit).`, true);
        list = list.slice(0, MAX_PHOTOS);
      }
      filesBySource[id] = list;
      S.had_files = hasFiles();
      scheduleDraftSave();
      render(false);
      return;
    }
    if (t.id === "wizTestPhoto") {
      const f = t.files?.[0];
      t.value = "";
      if (f) launchPhotoMeasure(f);
      return;
    }
    if (t.name === "wiz-mref") {
      S.scale_setup.measure_ref = t.value;
      scheduleDraftSave();
      render(false);
      return;
    }
    if (t.dataset.sceneRef) {
      const id = t.dataset.sceneRef;
      const cur = new Set(S.scale_setup.scene_ref_ids || []);
      if (t.checked) {
        if (cur.size >= 10) { t.checked = false; return ctx.toast("Select at most 10 scene-scale objects.", true); }
        cur.add(id);
      } else {
        cur.delete(id);
      }
      S.scale_setup.scene_ref_ids = [...cur];
      t.closest(".wiz-chip-check")?.classList.toggle("on", t.checked);
      scheduleDraftSave();
      return;
    }
    if (t.dataset.pref === "include_doh_materials") {
      S.report_prefs.include_doh_materials = t.checked;
      scheduleDraftSave();
      return;
    }
    if (t.dataset.exportFmt) {
      const cur = new Set(S.report_prefs.export_formats || []);
      if (t.checked) cur.add(t.dataset.exportFmt); else cur.delete(t.dataset.exportFmt);
      S.report_prefs.export_formats = [...cur];
      scheduleDraftSave();
    }
  });

  window.addEventListener("iscale:lang", () => {
    if (S && S.step === 3 && root.hasAttribute("data-active")) render(false);
  });

  return { open };
}

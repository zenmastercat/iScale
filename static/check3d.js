/* 3D check for one finding: the point cloud behind it, so a person can judge whether the two models
   got it right. The pothole detector marks boxes on the video; LingBot-Map rebuilds the clip in 3D
   and the points from inside those boxes are labelled (magenta). The analysis measures the dip in
   the road (outline). Three server-rendered views: from above, height against the road, a
   cross-section; then the verdict and a Correct / Wrong / Unsure answer that is saved on the finding. */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HDR = { "X-Civil-Scan": "1", "Content-Type": "application/json" };
const cm = (m) => (m == null ? "not measurable" : `${(m * 100).toFixed(1)} cm`);
const REVIEW = { correct: "Correct", wrong: "Wrong", unsure: "Unsure" };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: HDR });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

function html(c) {
  const v = c.verdict;
  const rv = c.review;
  return `
    <div class="chk-head">
      <h4>3D check</h4>
      <span class="chk-badge ${esc(v.code)}">${{ both: "Detector + 3D agree", detector_only: "Detector only", geometry_only: "3D only", manual: "Tagged by hand" }[v.code] || esc(v.code)}</span>
    </div>
    <p class="chk-verdict">${esc(v.text)}</p>
    ${v.warnings.length ? `<ul class="chk-warn">${v.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <div class="chk-grid">
      <figure><img src="${esc(c.images.top)}" alt="Point cloud from above, ${esc(c.view_m)} m across" loading="lazy" decoding="async">
        <figcaption>From above, ${esc(c.view_m)} m across. <i class="dot det"></i>detector's points, <i class="ring ${esc(c.severity)}"></i>measured outline.</figcaption></figure>
      <figure><img src="${esc(c.images.height)}" alt="Height against the road around the finding" loading="lazy" decoding="async">
        <figcaption>Height against a road surface fitted around it: red is below the road, blue above.</figcaption></figure>
      <figure class="wide"><img src="${esc(c.images.section)}" alt="Cross-section through the finding" loading="lazy" decoding="async">
        <figcaption>Cross-section west to east along the black line. Grey dots: 3D points; black: the average surface. LingBot-Map often stacks the road in thin layers.</figcaption></figure>
    </div>
    <dl class="chk-nums">
      <dt>Detector points nearby</dt><dd>${c.detector_points.toLocaleString()} (${c.detector_points_inside.toLocaleString()} inside the outline)</dd>
      <dt>Measured depth</dt><dd>${cm(c.measured_depth_m)}</dd>
      <dt>Re-measured here</dt><dd>${cm(c.lowest_below_plane_m)}</dd>
      <dt>Road roughness around it</dt><dd>±${(c.road_noise_m * 100).toFixed(1)} cm</dd>
    </dl>
    <div class="chk-review" role="group" aria-label="Is this finding right?">
      <span class="chk-q">Is this right?</span>
      ${Object.entries(REVIEW).map(([k, l]) => `<button type="button" class="btn small chk-btn" data-chk="${k}" aria-pressed="${rv?.verdict === k}">${l}</button>`).join("")}
    </div>
    <p class="muted small chk-who">${rv ? `Marked ${esc(REVIEW[rv.verdict].toLowerCase())} by ${esc(rv.by_name || "")} (@${esc(rv.by || "")}), ${new Date(rv.at * 1000).toLocaleString()}${rv.note ? `: "${esc(rv.note)}"` : ""}.`
      : "Your answer is saved on the finding, with your name, so wrong results can be counted and fixed."}</p>`;
}

/** Load and show the check for {project, survey, id} inside `el`. */
export async function mountCheck(el, ref, { toast } = {}) {
  if (!el) return;
  const base = `/api/projects/${ref.project}/surveys/${ref.survey}/findings/${encodeURIComponent(ref.id)}`;
  el.innerHTML = `<div class="chk-head"><h4>3D check</h4></div><p class="muted small">Loading the point cloud around it…</p>`;
  let c;
  try { c = await api(`${base}/check`); } catch (e) {
    el.innerHTML = `<div class="chk-head"><h4>3D check</h4></div><p class="muted small">No 3D check: ${esc(e.message)}.</p>`;
    return;
  }
  const paint = () => {
    el.innerHTML = html(c);
    for (const img of el.querySelectorAll("img")) img.addEventListener("error", () => img.closest("figure").classList.add("broken"), { once: true });
  };
  paint();
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-chk]");
    if (!b) return;
    let note = "";
    if (b.dataset.chk === "wrong") {
      note = prompt("What is wrong? (optional: for example 'a shadow', 'a manhole cover', 'already patched')") ?? null;
      if (note === null) return;
    }
    try {
      c = await api(`${base}/review`, { method: "POST", body: JSON.stringify({ verdict: b.dataset.chk, note }) });
      paint();
      toast?.("Saved your answer");
    } catch (err) { toast?.(err.message, true); }
  });
}

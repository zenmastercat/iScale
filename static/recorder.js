/* Record a drive: the phone's rear camera and, when location is on, its GPS track at the same time.
   The upload goes to the pothole-video pipeline; the track becomes gps.csv, which gives the
   LingBot-Map 3D survey its real position and scale. Without location, the camera height sets
   the scale, as for an uploaded video. */
import * as loc from "./location.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const MIMES = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
const MAX_MIN = 15;

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const mb = (b) => `${(b / 1e6).toFixed(b < 1e7 ? 1 : 0)} MB`;

export async function openRecorder({ project, toast, available, onUploaded }) {
  if (!project) return toast("Create or choose a project first.", true);
  if (!available) return toast("Pothole detection isn't set up on this server, so drives can't be processed yet.", true);
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("This browser can't record video. Use Add survey to upload one.", true);

  const d = document.createElement("dialog");
  d.className = "recorder";
  d.setAttribute("aria-label", "Record a drive");
  d.innerHTML = `
    <video class="rec-view" playsinline muted autoplay></video>
    <div class="rec-top">
      <button class="btn icon rec-close" type="button" aria-label="Close">✕</button>
      <div class="rec-chips"><span class="rec-chip" id="recGps"></span><span class="rec-chip" id="recTime" hidden></span></div>
    </div>
    <div class="rec-bottom">
      <p class="rec-hint" id="recHint">Mount the phone on the dashboard, facing the road, then start.</p>
      <div class="rec-controls">
        <button class="rec-btn" type="button" id="recBtn" aria-label="Start recording"><span></span></button>
      </div>
      <form class="rec-done" id="recDone" hidden>
        <label class="field"><span>Name</span><input class="input" name="name" required maxlength="120"></label>
        <label class="field"><span>Camera height above the road (m)</span><input class="input num" name="h" type="number" inputmode="decimal" step="0.05" min="0.3" max="5" value="1.3"></label>
        <p class="muted small" id="recSummary"></p>
        <div class="progress" id="recProgress" hidden><div></div></div>
        <div class="dialog-actions"><button class="btn quiet" type="button" id="recDiscard">Discard</button><button class="btn primary" type="submit" id="recUpload">Upload and process</button></div>
      </form>
    </div>`;
  document.body.appendChild(d);
  const $ = (s) => d.querySelector(s);
  let stream = null, rec = null, chunks = [], t0 = 0, timer = 0, track = null, wake = null, blob = null, rows = [], mime = "";

  const gpsChip = () => {
    const f = loc.fix();
    const el = $("#recGps");
    if (!loc.isOn()) { el.innerHTML = `GPS off <button type="button" class="link" id="recLocOn">Turn on</button>`; el.dataset.q = "off";
      $("#recLocOn").onclick = async () => { try { await loc.ensure("A recorded drive uses it for real position and size."); } catch (e) { toast(e.message, true); } gpsChip(); }; return; }
    if (loc.isBlocked()) { el.textContent = "GPS blocked by the browser"; el.dataset.q = "off"; return; }
    if (!f || f.stale) { el.textContent = "GPS: waiting…"; el.dataset.q = "wait"; return; }
    el.textContent = `GPS ±${Math.round(f.acc)} m`;
    el.dataset.q = f.acc <= 10 ? "good" : f.acc <= 30 ? "ok" : "poor";
  };
  const offFix = loc.onChange(gpsChip);
  gpsChip();

  async function cleanup() {
    clearInterval(timer);
    offFix();
    track?.stop();
    try { await wake?.release(); } catch { /* already released */ }
    stream?.getTracks().forEach((t) => t.stop());
  }
  d.addEventListener("close", () => { cleanup(); d.remove(); });
  d.addEventListener("cancel", (e) => { if (rec?.state === "recording") e.preventDefault(); });
  $(".rec-close").onclick = () => {
    if (rec?.state === "recording" && !confirm("Stop and throw away this recording?")) return;
    if (blob && !confirm("Throw away this recording?")) return;
    if (rec?.state === "recording") { rec.onstop = null; rec.stop(); }
    d.close();
  };
  d.showModal();

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: false,
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } } });
  } catch (err) {
    $("#recHint").textContent = `The camera isn't available: ${err.message}. Allow camera access for this site, on HTTPS.`;
    $("#recBtn").disabled = true;
    return;
  }
  $(".rec-view").srcObject = stream;

  $("#recBtn").onclick = async () => {
    if (rec?.state === "recording") return rec.stop();
    mime = MIMES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
    rec = new MediaRecorder(stream, { ...(mime ? { mimeType: mime } : {}), videoBitsPerSecond: 5_000_000 });
    chunks = [];
    track = loc.isOn() ? loc.recordTrack() : null;
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstart = () => {
      t0 = Date.now();
      track?.begin(t0);
      d.dataset.rec = "on";
      $("#recBtn").setAttribute("aria-label", "Stop recording");
      $("#recTime").hidden = false;
      $("#recHint").textContent = track ? "Recording with GPS. Keep iScale open on screen." : "Recording without GPS: sizes will come from the camera height.";
      timer = setInterval(() => {
        const s = (Date.now() - t0) / 1000;
        const size = chunks.reduce((a, c) => a + c.size, 0);
        $("#recTime").textContent = `● ${mmss(s)}  ${mb(size)}`;
        if (s >= MAX_MIN * 60) rec.stop();
      }, 500);
    };
    rec.onstop = () => {
      clearInterval(timer);
      d.dataset.rec = "done";
      wake?.release().catch(() => {});
      rows = track ? track.stop() : [];
      track = null;
      blob = new Blob(chunks, { type: (mime || "video/webm").split(";")[0] });
      const secs = (Date.now() - t0) / 1000;
      $(".rec-view").srcObject = null;
      $(".rec-view").src = URL.createObjectURL(blob);
      $(".rec-view").controls = true;
      stream.getTracks().forEach((t) => t.stop());
      $(".rec-controls").hidden = true;
      $("#recHint").hidden = true;
      $("#recDone").hidden = false;
      $("#recDone").name.value = `Drive ${new Date(t0).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
      const accs = rows.map((r) => r[3]).sort((a, b) => a - b);
      $("#recSummary").textContent = `${mmss(secs)}, ${mb(blob.size)}. ` + (rows.length >= 2
        ? `GPS track: ${rows.length} positions, typical accuracy ±${Math.round(accs[Math.floor(accs.length / 2)])} m. It gives the survey real position and scale.`
        : "No GPS track: the camera height sets the scale.");
    };
    try { wake = await navigator.wakeLock?.request("screen"); } catch { /* not allowed: the screen may sleep */ }
    rec.start(1000);
  };

  $("#recDiscard").onclick = () => { if (confirm("Throw away this recording?")) { blob = null; d.close(); } };
  $("#recDone").onsubmit = (e) => {
    e.preventDefault();
    const f = e.target;
    const fd = new FormData();
    fd.append("name", f.name.value);
    fd.append("decoder", "pothole_video");
    fd.append("params", JSON.stringify(f.h.value ? { camera_height_m: +f.h.value } : {}));
    fd.append("recorded", "true");
    if (rows.length >= 2) fd.append("device_track", JSON.stringify(rows));
    fd.append("files", blob, `drive.${blob.type.includes("mp4") ? "mp4" : "webm"}`);
    const xhr = new XMLHttpRequest();
    const bar = $("#recProgress");
    bar.hidden = false;
    $("#recUpload").disabled = true;
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) bar.firstElementChild.style.width = `${(100 * ev.loaded) / ev.total}%`; };
    xhr.onload = () => {
      $("#recUpload").disabled = false;
      if (xhr.status >= 300) { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch { /* keep */ } return toast(m, true); }
      const sv = JSON.parse(xhr.responseText);
      blob = null;
      d.close();
      onUploaded?.(sv);
    };
    xhr.onerror = () => { $("#recUpload").disabled = false; toast("The upload failed. Check the connection and try again; the recording is kept until you close this.", true); };
    xhr.open("POST", `/api/projects/${project.id}/surveys`);
    xhr.setRequestHeader("X-Civil-Scan", "1");
    xhr.send(fd);
  };
}

/* Settings: team (admin), Civil Helper provider and library, traffic sources, network mode. */
import { renderSettingsPanel as locationPanel } from "./location.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HDR = { "X-Civil-Scan": "1", "Content-Type": "application/json" };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: opts.body instanceof FormData ? { "X-Civil-Scan": "1" } : HDR });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

const PROVIDERS = [
  ["ollama", "Ollama on this server"],
  ["openai", "OpenAI or OpenAI-compatible"],
  ["anthropic", "Anthropic"],
  ["google", "Google Gemini"],
];
const MODE_HELP = {
  internet: "Reachable from anywhere. Needs the public host name and HTTPS, either certificate files or a reverse proxy in front.",
  lan: "Reachable from devices on the office network. A self-signed HTTPS certificate is created; each device accepts it once.",
  local: "Only this computer can use the app.",
};

export async function renderSettings(root, me, toast) {
  const admin = me.role === "admin";
  const [team, lib, status, cfg, mats, comp] = await Promise.all([
    api("/api/team"), api("/api/library"), api("/api/helper/status").catch((e) => ({ reachable: false, error: e.message })),
    admin ? api("/api/settings") : Promise.resolve(null),
    api("/api/settings/materials").catch(() => null),
    api("/api/company").catch(() => null),
  ]);
  const solo = comp?.kind === "individual";
  root.innerHTML = `
    <div class="page-head"><h1>Settings</h1><p class="muted">${esc(me.display_name)} (@${esc(me.username)}), ${esc(me.company)}${admin ? ", admin" : ""}</p></div>

    <section class="panel set" id="locPanel" aria-label="Location"></section>

    ${comp ? `<section class="panel set">
      <div class="panel-head"><h2>${solo ? "Your account" : "Company"}</h2><span class="muted small">${solo ? "Individual account" : `${comp.members} ${comp.members === 1 ? "person" : "people"}`}</span></div>
      <div class="set-body">
        ${solo ? `<p class="muted small">A personal workspace: your projects, prices and Civil Helper library are yours alone. Shared pothole pins and chat by username work the same as for companies.</p>
          <form class="inline-form" id="upgradeForm">
            <input class="input" name="name" required minlength="2" maxlength="80" placeholder="Company or department name" aria-label="Company name">
            <button class="btn primary small" type="submit">Turn into a company</button></form>
          <p class="muted small">You become its admin, keep your projects, and can add engineers or share a join code. This can't be undone.</p>`
        : `${admin ? `<form class="inline-form" id="companyForm">
            <input class="input" name="name" required minlength="2" maxlength="80" value="${esc(comp.name)}" aria-label="Company name">
            <button class="btn small" type="submit">Rename</button></form>
          <div class="join-code">
            <div><span class="muted small">Join code</span>
              ${comp.join_code ? `<b class="code">${esc(comp.join_code)}</b>` : `<b class="muted">Off</b>`}</div>
            <div class="row-actions">
              ${comp.join_code ? `<button class="btn small" type="button" data-co="copy">Copy</button>` : ""}
              <button class="btn small" type="button" data-co="new">${comp.join_code ? "New code" : "Create a code"}</button>
              ${comp.join_code ? `<button class="btn small quiet" type="button" data-co="off">Turn off</button>` : ""}
            </div>
          </div>
          <p class="muted small">Anyone with this code can create an account in ${esc(comp.name)} as an engineer (Create account, For a company, Join with a code). A new code stops the old one.</p>`
          : `<p>${esc(comp.name)}</p>`}`}
        ${comp.signup ? `<form class="grid-form" id="signupForm">
          <h3>Sign-up on this server</h3>
          <label class="check"><input type="checkbox" name="company" ${comp.signup.company ? "checked" : ""}> People can create a company account, or join one with its code</label>
          <label class="check"><input type="checkbox" name="individual" ${comp.signup.individual ? "checked" : ""}> People can create an individual account</label>
          <div class="form-actions"><button class="btn primary small" type="submit">Save sign-up settings</button><span class="muted small">With both off, only admins add people.</span></div>
        </form>` : ""}
      </div>
    </section>` : ""}

${solo ? "" : `    <section class="panel set">
      <div class="panel-head"><h2>Team</h2></div>
      <div class="set-body">
        <table class="table"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Device</th>${admin ? "<th></th>" : ""}</tr></thead><tbody>
        ${team.map((u) => `<tr><td>${esc(u.display_name)}</td><td>@${esc(u.username)}</td><td>${esc(u.role)}</td>
          <td>${u.disabled ? "Disabled" : u.device_bound ? "Signed in" : "Not signed in yet"}</td>
          ${admin ? `<td class="row-actions">${u.username === me.username ? "" : `
            <button class="btn small quiet" data-act="reset" data-u="${esc(u.username)}" type="button">Reset device</button>
            <button class="btn small quiet" data-act="${u.disabled ? "enable" : "disable"}" data-u="${esc(u.username)}" type="button">${u.disabled ? "Enable" : "Disable"}</button>`}</td>` : ""}</tr>`).join("")}
        </tbody></table>
        ${admin && !solo ? `<form class="inline-form" id="addMember">
          <input class="input" name="username" placeholder="username" required maxlength="32" autocapitalize="none" aria-label="Username">
          <input class="input" name="display_name" placeholder="Name" required maxlength="80" aria-label="Name">
          <select class="input" name="role" aria-label="Role"><option value="engineer">Engineer</option><option value="admin">Admin</option></select>
          <button class="btn primary small" type="submit">Add engineer</button></form>
          <p class="muted small">Engineers sign in with just their username. Their first sign-in links the username to that device; use Reset device when someone changes phone or laptop.</p>` : ""}
      </div>
    </section>`}

    <section class="panel set">
      <div class="panel-head"><h2>Civil Helper</h2><span class="muted small">${status.reachable ? `Using ${esc(status.type)}: ${esc(status.model)}` : `Not reachable: ${esc(status.error || "")}`}</span></div>
      <div class="set-body">
        ${admin ? `<form class="grid-form" id="helperForm">
          <label class="field"><span>Provider</span><select class="input" name="type">${PROVIDERS.map(([v, l]) => `<option value="${v}" ${cfg.helper.type === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="field"><span>Endpoint (optional)</span><input class="input" name="base_url" value="${esc(cfg.helper.base_url)}" placeholder="Provider's own API"></label>
          <label class="field"><span>Model</span><input class="input" name="model" value="${esc(cfg.helper.model)}" required></label>
          <label class="field"><span>Embedding model (for library search)</span><input class="input" name="embed_model" value="${esc(cfg.helper.embed_model || "")}" placeholder="none: keyword search only"></label>
          <label class="field"><span>API key ${cfg.helper.has_key ? "(saved; leave empty to keep)" : ""}</span><input class="input" name="api_key" type="password" autocomplete="off" placeholder="${cfg.helper.type === "ollama" ? "not needed for Ollama" : ""}"></label>
          <div class="form-actions"><button class="btn primary small" type="submit">Save Civil Helper settings</button></div>
        </form>
        <p class="muted small">"auto:smallest-qwen" picks the smallest Qwen model in Ollama. Questions go only to the provider you choose here; chat messages never do.</p>` : ""}
        <h3>Library</h3>
        <p class="muted small">Civil Helper answers from these documents and cites them. Add your standards, manuals and specifications (PDF, .txt or .md).</p>
        <form class="inline-form" id="libForm">
          <input class="input" name="title" placeholder="Title (optional)" maxlength="200" aria-label="Title">
          <input class="input" name="file" type="file" accept=".pdf,.txt,.md" required aria-label="Document">
          <button class="btn primary small" type="submit">Add document</button>
          ${admin ? `<button class="btn small quiet" id="reindex" type="button">Rebuild search index</button>` : ""}
        </form>
        <table class="table"><thead><tr><th>Document</th><th class="num">Passages</th><th>Search</th><th>Added by</th><th></th></tr></thead><tbody>
        ${lib.length ? lib.map((d) => `<tr><td>${esc(d.title)}</td><td class="num">${d.chunks}</td><td>${d.embedded ? "meaning + keywords" : "keywords"}</td><td>@${esc(d.uploader)}</td>
          <td>${admin || d.uploader === me.username ? `<button class="btn small quiet" data-act="deldoc" data-id="${esc(d.id)}" type="button">Remove</button>` : ""}</td></tr>`).join("")
          : `<tr><td colspan="5" class="empty">No documents yet.</td></tr>`}
        </tbody></table>
      </div>
    </section>

    ${mats ? `
    <section class="panel set">
      <div class="panel-head"><h2>Material prices</h2><span class="muted small">For the materials-only pothole cost (no labour)</span></div>
      <form class="set-body" id="matForm">
        <table class="table"><thead><tr><th>Material</th><th>Unit</th><th class="num">Price (${esc(mats.symbol)})</th><th>Source</th></tr></thead><tbody>
        ${Object.entries(mats.materials).map(([k, m]) => `<tr><td>${esc(m.label)}<br><span class="muted small">${esc(m.label_th || "")}</span></td>
          <td>${k === "cold_mix" ? (mats.editable ? `bag of <input class="input num tiny" name="${k}.bag_kg" type="number" inputmode="decimal" min="1" max="100" step="any" value="${m.bag_kg}" aria-label="Bag weight in kg"> kg` : `bag of ${m.bag_kg} kg`) : esc(m.unit)}</td>
          <td class="num">${mats.editable ? `<input class="input num" name="${k}.price" type="number" inputmode="decimal" min="0" step="any" value="${m.price}" aria-label="${esc(m.label)} price">` : (m.price ? m.price.toLocaleString() : "not set")}</td>
          <td class="muted small">${esc(m.source)}</td></tr>`).join("")}
        </tbody></table>
        ${mats.editable ? `<p class="muted small">Prices exclude VAT and transport. Factor F is not applied: it multiplies the full direct cost including labour, so it does not apply to a materials-only figure.</p>
        <div class="form-actions"><button class="btn primary small" type="submit">Save prices</button></div>` : `<p class="muted small">Only an admin can change prices.</p>`}
      </form>
    </section>` : ""}

    ${admin ? `
    <section class="panel set">
      <div class="panel-head"><h2>Traffic</h2></div>
      <form class="set-body grid-form" id="trafficForm">
        <label class="check"><input type="checkbox" name="osm" ${cfg.traffic.osm ? "checked" : ""}> Road class from OpenStreetMap (sends the map area to overpass-api.de)</label>
        <label class="check"><input type="checkbox" name="google" ${cfg.traffic.google ? "checked" : ""}> Live congestion from Google Maps (sends road points to Google)</label>
        <label class="field"><span>Google Maps API key ${cfg.traffic.has_google_key ? "(saved; leave empty to keep)" : ""}</span><input class="input" name="google_key" type="password" autocomplete="off" placeholder="Routes API enabled"></label>
        <div class="form-actions"><button class="btn primary small" type="submit">Save traffic settings</button></div>
      </form>
    </section>

    <section class="panel set">
      <div class="panel-head"><h2>Network</h2>${cfg.network.editable ? "" : `<span class="muted small">Set by the server's host company</span>`}</div>
      <form class="set-body grid-form" id="netForm">
        <fieldset class="modes" ${cfg.network.editable ? "" : "disabled"}>
          ${["internet", "lan", "local"].map((m) => `<label class="check"><input type="radio" name="mode" value="${m}" ${cfg.network.mode === m ? "checked" : ""}>
            <span><b>${{ internet: "Internet", lan: "Office network (LAN)", local: "This computer only" }[m]}</b>${m === "internet" ? " (default)" : ""}<br><span class="muted small">${MODE_HELP[m]}</span></span></label>`).join("")}
        </fieldset>
        <label class="field"><span>Public host name (internet)</span><input class="input" name="public_host" value="${esc(cfg.network.public_host)}" placeholder="scan.yourcompany.co.th" ${cfg.network.editable ? "" : "disabled"}></label>
        <label class="field"><span>HTTPS</span><select class="input" name="tls" ${cfg.network.editable ? "" : "disabled"}>
          ${[["proxy", "Reverse proxy handles HTTPS"], ["files", "Certificate files on this server"], ["self-signed", "Self-signed (LAN)"]].map(([v, l]) => `<option value="${v}" ${cfg.network.tls === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="field"><span>Certificate file</span><input class="input" name="cert_file" value="${esc(cfg.network.cert_file)}" ${cfg.network.editable ? "" : "disabled"}></label>
        <label class="field"><span>Key file</span><input class="input" name="key_file" value="${esc(cfg.network.key_file)}" ${cfg.network.editable ? "" : "disabled"}></label>
        <label class="field"><span>Port</span><input class="input num" name="port" type="number" value="${cfg.network.port}" ${cfg.network.editable ? "" : "disabled"}></label>
        ${cfg.network.editable ? `<div class="form-actions"><button class="btn primary small" type="submit">Save network settings</button><span class="muted small">Takes effect when the server restarts.</span></div>` : ""}
      </form>
    </section>` : ""}`;

  locationPanel(root.querySelector("#locPanel"), toast).catch((e) => { root.querySelector("#locPanel").textContent = `Location settings didn't load: ${e.message}`; });
  const reload = () => renderSettings(root, me, toast).then(() => root.dispatchEvent(new CustomEvent("settings:rendered")));
  const on = (sel, fn) => root.querySelector(sel)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await fn(new FormData(e.target)); toast("Saved"); await reload(); } catch (err) { toast(err.message, true); }
  });
  on("#addMember", (f) => api("/api/team", { method: "POST", body: JSON.stringify({ username: f.get("username"), display_name: f.get("display_name"), role: f.get("role") }) }));
  on("#helperForm", (f) => {
    const body = { type: f.get("type"), base_url: f.get("base_url"), model: f.get("model"), embed_model: f.get("embed_model") };
    if (f.get("api_key")) body.api_key = f.get("api_key");
    return api("/api/settings/helper", { method: "PUT", body: JSON.stringify(body) });
  });
  on("#libForm", (f) => {
    toast("Reading the document. Large PDFs take a minute.");
    return api("/api/library", { method: "POST", body: f });
  });
  on("#trafficForm", (f) => {
    const body = { osm: f.get("osm") === "on", google: f.get("google") === "on" };
    if (f.get("google_key")) body.google_key = f.get("google_key");
    return api("/api/settings/traffic", { method: "PUT", body: JSON.stringify(body) });
  });
  on("#matForm", (f) => {
    const materials = {};
    for (const [k, v] of f.entries()) {
      if (!k.includes(".") || v === "") continue;
      const [m, field] = k.split(".");
      (materials[m] ||= {})[field] = Number(v);
    }
    return api("/api/settings/materials", { method: "PUT", body: JSON.stringify({ materials }) });
  });
  on("#companyForm", (f) => api("/api/company", { method: "PATCH", body: JSON.stringify({ name: f.get("name") }) }));
  on("#upgradeForm", (f) => {
    if (!confirm(`Turn your account into the company "${f.get("name")}"? This can't be undone.`)) throw new Error("Cancelled");
    return api("/api/company", { method: "PATCH", body: JSON.stringify({ name: f.get("name"), kind: "company" }) })
      .then(() => setTimeout(() => location.reload(), 600));
  });
  on("#signupForm", (f) => api("/api/auth/signup", { method: "PUT", body: JSON.stringify({ company: f.get("company") === "on", individual: f.get("individual") === "on" }) }));
  root.querySelectorAll("[data-co]").forEach((b) => b.addEventListener("click", async () => {
    try {
      if (b.dataset.co === "copy") { await navigator.clipboard.writeText(comp.join_code); return toast("Join code copied"); }
      if (b.dataset.co === "new" && comp.join_code && !confirm("Make a new join code? The current one stops working.")) return;
      await api(`/api/company/join-code${b.dataset.co === "off" ? "?off=true" : ""}`, { method: "POST", body: "{}" });
      toast(b.dataset.co === "off" ? "Joining by code is off" : "New join code ready");
      await reload();
    } catch (err) { toast(err.message, true); }
  }));
  on("#netForm", (f) => api("/api/settings/network", { method: "PUT", body: JSON.stringify({
    mode: f.get("mode"), public_host: f.get("public_host") || "", tls: f.get("tls"), cert_file: f.get("cert_file") || "",
    key_file: f.get("key_file") || "", port: +f.get("port") || 8765 }) }));

  root.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
    const a = b.dataset.act;
    try {
      if (a === "reset" && !confirm(`Reset @${b.dataset.u}'s device? They sign in again on their new device, and their contacts see a security-code change.`)) return;
      if (a === "deldoc" && !confirm("Remove this document from Civil Helper's library?")) return;
      if (a === "deldoc") await api(`/api/library/${b.dataset.id}`, { method: "DELETE" });
      else await api(`/api/team/${b.dataset.u}/${a === "reset" ? "reset-device" : a}`, { method: "POST", body: "{}" });
      toast("Done");
      await reload();
    } catch (err) { toast(err.message, true); }
  }));
  root.querySelector("#reindex")?.addEventListener("click", async () => {
    try { const r = await api("/api/library/reindex", { method: "POST", body: "{}" }); toast(`Indexed ${r.chunks} passages`); await reload(); }
    catch (err) { toast(err.message, true); }
  });
}

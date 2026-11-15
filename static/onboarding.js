/* First-run welcome for everyone, and the admin's "Get started" checklist.
   The checklist is computed from what the server already knows, so it never goes stale. */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const get = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(r.statusText); return r.json(); };
const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

const CHECK = `<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

/* Each step: what to do, whether it's done, and where the button goes (a view, plus an element to focus). */
export async function adminSteps(account = "company") {
  const [team, lib, cfg, groups, projects] = await Promise.all([
    get("/api/team").catch(() => []), get("/api/library").catch(() => []), get("/api/settings").catch(() => null),
    get("/api/groups").catch(() => []), get("/api/projects").catch(() => []),
  ]);
  const others = team.filter((u) => !u.disabled).length - 1;
  const signedIn = team.filter((u) => !u.disabled && u.device_bound).length - 1;
  const surveys = projects.reduce((n, p) => n + (p.surveys?.length || 0), 0);
  const solo = account === "individual";
  return [
    ...(solo ? [] : [{ id: "team", title: "Add your engineers", done: others > 0, view: "settings", focus: "#addMember input[name=username]",
      detail: others > 0 ? `${plural(others, "engineer", "engineers")} added, ${signedIn} signed in` : "Add them by username, or share your join code (Settings, Company)" }]),
    { id: "survey", title: "Bring in a street survey", done: surveys > 0, view: "video",
      detail: surveys > 0 ? `${plural(surveys, "survey", "surveys")} so far` : "Upload a drive video, or press Load demo street to look around" },
    { id: "library", title: "Give Civil Helper your manuals", done: lib.length > 0, view: "settings", focus: "#libForm input[name=file]",
      detail: lib.length ? `${plural(lib.length, "document", "documents")} in the library` : "Standards and specs it can quote, with sources" },
    ...(solo ? [] : [{ id: "group", title: "Start a crew group", done: groups.length > 0, view: "messages", focus: "#newGroup",
      detail: groups.length ? `${plural(groups.length, "group", "groups")}` : "One encrypted chat for a crew or a job" }]),
    { id: "traffic", title: "Turn on live traffic", optional: true, done: !!cfg?.traffic?.has_google_key, view: "settings", focus: "input[name=google_key]",
      detail: cfg?.traffic?.has_google_key ? "Google congestion is used in the fix-first list" : "Road class from OpenStreetMap already works without it" },
    ...(cfg?.network?.editable ? [{ id: "network", title: "Choose who can reach the app", done: !!cfg.network.saved, view: "settings", focus: "input[name=mode]",
      detail: cfg.network.saved ? `Set to ${{ internet: "internet", lan: "office network", local: "this computer" }[cfg.network.mode]}` : "Internet is the default; office network or this computer only" }] : []),
  ];
}

export function progress(steps) {
  const required = steps.filter((s) => !s.optional);
  return { done: required.filter((s) => s.done).length, total: required.length };
}

export function getStartedHtml(steps) {
  const p = progress(steps);
  if (p.done === p.total && steps.every((s) => s.done || s.optional)) return "";
  return `<section class="panel getstarted" aria-labelledby="gsTitle">
    <div class="gs-head">
      <div><h2 id="gsTitle">${steps.some((s) => s.id === "team") ? "Get your team going" : "Get started"}</h2><p class="muted small">${p.done} of ${p.total} done. Each step takes a minute or two.</p></div>
      <div class="gs-meter" role="progressbar" aria-valuemin="0" aria-valuemax="${p.total}" aria-valuenow="${p.done}" aria-label="Setup progress"><span style="--p:${p.total ? p.done / p.total : 1}"></span></div>
    </div>
    <ol class="gs-steps">${steps.map((s) => `<li class="gs-step${s.done ? " done" : ""}">
      <span class="gs-mark" aria-hidden="true">${s.done ? CHECK : ""}</span>
      <span class="gs-text"><b>${esc(s.title)}${s.optional ? ` <span class="tag">optional</span>` : ""}</b><span class="muted small">${esc(s.detail)}</span></span>
      ${s.done ? `<span class="sr-only">Done</span>` : `<button class="btn small" type="button" data-gs="${esc(s.id)}">${s.id === "survey" ? "Open" : "Do it"}</button>`}</li>`).join("")}</ol>
  </section>`;
}

/* Wire the step buttons: switch view, then focus the field that does the step. */
export function wireGetStarted(root, steps, go) {
  root.querySelectorAll("[data-gs]").forEach((b) => b.addEventListener("click", () => {
    const s = steps.find((x) => x.id === b.dataset.gs);
    if (s) go(s.view, s.focus);
  }));
}

/* Once per person per device, right after their first sign-in here. */
export function maybeWelcome(user, go) {
  const key = `civil-scan-welcomed:${user.username}`;
  try { if (localStorage.getItem(key)) return; localStorage.setItem(key, String(Date.now())); } catch { return; }
  const solo = user.account === "individual";
  const admin = user.role === "admin" && !solo;
  const first = esc(user.display_name.split(/\s+/)[0] || user.display_name);
  const items = [
    ["map", "See the shared map", "Every pothole anyone pins shows up here. Pin one with Pin a pothole, or confirm someone else's."],
    ["plan", "Fix the right one first", "Repairs > Fix first ranks defects by severity, safety and how busy the road is."],
    ["messages", solo ? "Message other engineers" : "Message your crew", "Find a colleague by username. Chats are end-to-end encrypted and stay on your device."],
    ["helper", "Ask Civil Helper", `Ask a civil-engineering question in the side panel. It answers from ${solo ? "the manuals you add" : "your company's manuals"} and names the source.`],
  ];
  const d = document.createElement("dialog");
  d.className = "dialog welcome";
  d.innerHTML = `<form method="dialog">
    <div class="welcome-strip" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>
    <h2>Welcome, ${first}</h2>
    <p class="muted">${solo ? "Your personal account is ready. Here's what you can do on your own:"
      : admin ? `You run iScale for ${esc(user.company)}. Four things your engineers will use every day:` : `You've joined ${esc(user.company)}. Here's what you can do:`}</p>
    <ul class="welcome-list">${items.map(([id, t, s]) => `<li><b>${t}</b><span class="muted small">${s}</span></li>`).join("")}</ul>
    <div class="dialog-actions">
      ${admin ? `<button class="btn" value="later">Look around first</button><button class="btn primary" value="setup">Set up my team</button>`
        : `<button class="btn primary" value="ok">Start</button>`}
    </div></form>`;
  document.body.appendChild(d);
  d.addEventListener("close", () => { const v = d.returnValue; d.remove(); if (v === "setup") go("settings"); });
  d.showModal();
}

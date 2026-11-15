/* Sign-in with a username only. The device proves it is the device that first used the
   username by signing a server nonce with an ECDSA P-256 key that never leaves this browser
   (WebCrypto, non-extractable, kept in IndexedDB). */
import { openDb } from "./idb.js";

const HDR = { "X-Civil-Scan": "1", "Content-Type": "application/json" };
let dbp = null;
const keysDb = () => (dbp ||= openDb("civil-scan-device", { auth: {} }));

const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: HDR, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

export async function state() {
  return (await fetch("/api/auth/state")).json();
}

export async function signIn(username) {
  username = username.trim().toLowerCase().replace(/^@/, "");
  const ch = await post("/api/auth/challenge", { username });
  const db = await keysDb();
  let pair = await db.get("auth", username);
  if (!pair) {
    if (!ch.claim) throw new Error("This username is already linked to another device. Ask your company admin to reset it.");
    pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  }
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, pair.privateKey, new TextEncoder().encode(ch.message));
  const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
  const res = await post("/api/auth/login", { username, nonce: ch.nonce, signature: b64(sig), public_key: b64(spki) });
  await db.put("auth", pair, username); // keep the key only once the server accepted it
  return res.user;
}

/* Create an account and bind this device's key in the same step, then sign in with it.
   kind: "company" (new company, you are its admin), "join" (with a join code) or "individual". */
export async function register({ kind, username, displayName, company = "", joinCode = "" }) {
  username = username.trim().toLowerCase().replace(/^@/, "");
  const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
  await post("/api/auth/register", { kind, username, display_name: displayName, public_key: b64(spki), company, join_code: joinCode });
  await (await keysDb()).put("auth", pair, username);
  return signIn(username);
}

export async function setup(company, username, displayName) {
  await post("/api/auth/setup", { company, username, display_name: displayName });
  return signIn(username);
}

export async function signOut() {
  await post("/api/auth/logout", {});
}

/* The sign-in screen. Resolves with the signed-in user. */
const PITCH = [
  ["Video in, measured potholes out", "A detector finds potholes in your drive video; only the 20 seconds around each one are rebuilt in 3D, so depth and size are measured, not guessed."],
  ["One shared pothole map", "Pin a pothole once and every engineer on the server sees it. Colleagues confirm it, and it moves up the list."],
  ["Fix first where traffic is heaviest", "Severity times safety times traffic, from the road's class and live congestion when your admin adds a Google key."],
  ["Crew chat and Civil Helper", "Encrypted 1:1 and group chats, and Civil Helper, which answers engineering questions from your own manuals and names the page."],
];

const USERNAME_HELP = "3-32 characters: letters, digits, dot, dash or underscore. People find you by it.";

function signInForm() {
  return `<form id="loginForm" class="login-form" data-mode="signin">
      <label class="field"><span>Username</span><input class="input" name="username" required maxlength="33" autocomplete="username" autocapitalize="none" spellcheck="false" autofocus placeholder="e.g. somchai.k"></label>
      <button class="btn primary big" type="submit">Sign in</button>
    </form>
    <p class="muted small login-help">Just your username. The first time, this device becomes yours; after that nobody can use your username from another device.</p>`;
}

function createForm(signup) {
  const both = signup.company && signup.individual;
  const first = signup.company ? "company" : "individual";
  return `<form id="loginForm" class="login-form" data-mode="create">
      ${both ? `<fieldset class="acct-kind" aria-label="Account type">
        <label class="acct-opt"><input type="radio" name="who" value="company" checked><span><b>For a company</b><small>A team with an admin, shared projects and group chats</small></span></label>
        <label class="acct-opt"><input type="radio" name="who" value="individual"><span><b>Just me</b><small>A personal workspace. You can turn it into a company later</small></span></label>
      </fieldset>` : `<input type="hidden" name="who" value="${first}">`}
      <div class="acct-company" ${first === "company" ? "" : "hidden"}>
        <div class="acct-seg" role="radiogroup" aria-label="New or existing company">
          <label><input type="radio" name="co" value="new" checked><span>New company</span></label>
          <label><input type="radio" name="co" value="join"><span>Join with a code</span></label>
        </div>
        <label class="field co-new"><span>Company or department</span><input class="input" name="company" maxlength="80" autocomplete="organization" placeholder="e.g. Bang Sue District Works"></label>
        <label class="field co-join" hidden><span>Join code from your admin</span><input class="input" name="join_code" maxlength="12" autocapitalize="characters" autocomplete="off" spellcheck="false" placeholder="ABCD-2345"></label>
      </div>
      <label class="field"><span>Your name</span><input class="input" name="display" required maxlength="80" autocomplete="name"></label>
      <label class="field"><span>Choose a username</span><input class="input" name="username" required maxlength="32" autocomplete="username" autocapitalize="none" spellcheck="false" pattern="[A-Za-z0-9][A-Za-z0-9._\\-]{2,31}" title="${USERNAME_HELP}"><small class="muted">${USERNAME_HELP}</small></label>
      <button class="btn primary big" type="submit" id="createBtn">Create company account</button>
      <p class="muted small login-help" id="createHelp"></p>
    </form>`;
}

const CREATE_HELP = {
  new: ["Create company account", "You'll be the company's admin. Then add your engineers by username, or share the join code from Settings."],
  join: ["Join company", "Your admin finds the join code in Settings, under Company. You join as an engineer."],
  individual: ["Create my account", "No password: this device becomes yours. Shared pothole pins and chat by username work the same."],
};

export function showLogin(root, st) {
  return new Promise((resolve) => {
    const setupMode = st.setup_needed;
    const signup = st.signup || { company: false, individual: false };
    const canCreate = !setupMode && (signup.company || signup.individual);
    root.innerHTML = `
      <div class="login-wrap">
        <section class="login-pitch" aria-labelledby="pitchTitle">
          <div class="login-brand">
            <svg viewBox="0 0 28 20" width="28" height="20" aria-hidden="true">
              <rect x="0" y="8" width="7" height="4" fill="#3f9b6e"/><rect x="7" y="8" width="7" height="4" fill="#c9a100"/>
              <rect x="14" y="8" width="7" height="4" fill="#d9730d"/><rect x="21" y="8" width="7" height="4" fill="#3f9b6e"/>
              <path d="M10 4v12M24 4v12" stroke="currentColor" stroke-width="1.6"/></svg>
            iScale</div>
          <h1 id="pitchTitle">Find every pothole.<br>Fix the right one first.</h1>
          <p class="login-lede">Road inspection for city engineering teams and independent engineers: survey, rank, repair and prove it, on a server your organisation runs.</p>
          <div class="pitch-strip" aria-hidden="true"><i style="--c:var(--ok)"></i><i style="--c:var(--low)"></i><i style="--c:var(--ok)"></i><i style="--c:var(--high)"></i><i style="--c:var(--medium)"></i><i style="--c:var(--ok)"></i><i style="--c:var(--ok)"></i><i style="--c:var(--low)"></i></div>
          <ul class="pitch-list">${PITCH.map(([t, d]) => `<li><b>${t}</b><span>${d}</span></li>`).join("")}</ul>
        </section>
        <div class="login-card">
          ${setupMode
            ? `<h2>Set up iScale for your team</h2>
               <p class="muted small">You'll be the admin. Next you'll add engineers by username; they sign in with no password.</p>
               <form id="loginForm" class="login-form" data-mode="setup">
                 <label class="field"><span>Company or department</span><input class="input" name="company" required maxlength="80" autocomplete="organization" placeholder="e.g. Bang Sue District Works"></label>
                 <label class="field"><span>Your name</span><input class="input" name="display" required maxlength="80" autocomplete="name"></label>
                 <label class="field"><span>Your username</span><input class="input" name="username" required maxlength="32" autocomplete="username" autocapitalize="none" spellcheck="false"></label>
                 <button class="btn primary big" type="submit">Set up and sign in</button>
               </form>`
            : `${canCreate ? `<div class="login-tabs" role="tablist">
                  <button type="button" role="tab" data-tab="signin" aria-selected="true">Sign in</button>
                  <button type="button" role="tab" data-tab="create" aria-selected="false">Create account</button></div>` : `<h2>Sign in</h2>`}
               <div id="loginPane">${signInForm()}</div>
               ${canCreate ? "" : `<p class="muted small">No account yet? Ask your company admin to add your username.</p>`}`}
          <p class="login-error" id="loginError" role="alert"></p>
        </div>
      </div>`;
    root.hidden = false;
    const pane = root.querySelector("#loginPane");
    const err = root.querySelector("#loginError");

    const syncCreate = () => {
      const form = root.querySelector('#loginForm[data-mode="create"]');
      if (!form) return;
      const who = form.querySelector('[name="who"]:checked, [name="who"][type=hidden]').value;
      const co = form.querySelector('[name="co"]:checked').value;
      const key = who === "individual" ? "individual" : co;
      form.querySelector(".acct-company").hidden = who !== "company";
      form.querySelector(".co-new").hidden = key !== "new";
      form.querySelector(".co-join").hidden = key !== "join";
      form.querySelector('[name="company"]').required = key === "new";
      form.querySelector('[name="join_code"]').required = key === "join";
      form.querySelector("#createBtn").textContent = CREATE_HELP[key][0];
      form.querySelector("#createHelp").textContent = CREATE_HELP[key][1];
    };
    const showTab = (tab) => {
      for (const b of root.querySelectorAll("[data-tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
      pane.innerHTML = tab === "create" ? createForm(signup) : signInForm();
      err.textContent = "";
      syncCreate();
      pane.querySelector("input:not([type=radio]):not([type=hidden])")?.focus({ preventScroll: true });
    };
    root.querySelector(".login-tabs")?.addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
    root.addEventListener("change", (e) => { if (e.target.matches('[name="who"], [name="co"]')) syncCreate(); });

    root.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      err.textContent = "";
      try {
        const f = new FormData(form);
        let user;
        if (form.dataset.mode === "setup") user = await setup(f.get("company"), f.get("username"), f.get("display"));
        else if (form.dataset.mode === "signin") user = await signIn(f.get("username"));
        else {
          const kind = f.get("who") === "individual" ? "individual" : (f.get("co") === "join" ? "join" : "company");
          user = await register({ kind, username: f.get("username"), displayName: f.get("display"), company: f.get("company") || "", joinCode: f.get("join_code") || "" });
          user.firstRun = true;
        }
        root.hidden = true;
        root.innerHTML = "";
        resolve(user);
      } catch (ex) {
        err.textContent = ex.message;
        btn.disabled = false;
      }
    });
  });
}

#!/usr/bin/env node
/*
 * Pitch rehearsal: runs the whole demo story in a real browser and fails loudly if anything is off.
 *
 *   pnpm rehearse            # uses the existing out/ (run `pnpm build` first)
 *   pnpm rehearse --build    # builds first
 *   pnpm rehearse --headed   # watch it
 *
 * It starts its OWN throwaway backend (:8790, temp data dir) and static server (:3190), so it never touches
 * your real backend (:8765) or a running `pnpm dev`. Screenshots + report land in web/rehearsal/.
 * Exit code 0 = every step passed.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(WEB, "..");
const OUT = path.join(WEB, "rehearsal");
const API_PORT = Number(process.env.REHEARSE_API_PORT ?? 8790);
const WEB_PORT = Number(process.env.REHEARSE_WEB_PORT ?? 3190);
const BASE = `http://127.0.0.1:${WEB_PORT}`;
const args = new Set(process.argv.slice(2));

const results = [];
let failed = 0;
const step = (ok, name, detail = "") => {
  results.push(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  console.log(`${ok ? "\x1b[32mPASS\x1b[0m" : "\x1b[31mFAIL\x1b[0m"}  ${name}${detail ? `  \x1b[2m${detail}\x1b[0m` : ""}`);
  if (!ok) failed++;
};

const children = [];
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "iscale-rehearse-"));
function cleanup() {
  for (const c of children) {
    try {
      process.kill(-c.pid, "SIGTERM");
    } catch {}
  }
  fs.rmSync(dataDir, { recursive: true, force: true });
}
process.on("SIGINT", () => {
  cleanup();
  process.exit(130);
});

async function waitFor(url, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return true;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function start(cmd, argv, opts) {
  const c = spawn(cmd, argv, { ...opts, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  const log = fs.createWriteStream(path.join(OUT, `${path.basename(cmd)}-${children.length}.log`));
  c.stdout.pipe(log);
  c.stderr.pipe(log);
  children.push(c);
  return c;
}

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

try {
  if (args.has("--build")) {
    console.log("building…");
    const b = spawnSync("pnpm", ["build"], { cwd: WEB, stdio: "inherit" });
    if (b.status !== 0) throw new Error("pnpm build failed");
  }
  if (!fs.existsSync(path.join(WEB, "out", "index.html"))) throw new Error("no out/: run `pnpm build` or pass --build");

  start("uv", ["run", "civil", "serve", "--port", String(API_PORT)], { cwd: REPO, env: { ...process.env, CIVIL_DATA_DIR: dataDir } });
  start("node", ["scripts/serve.mjs"], {
    cwd: WEB,
    env: { ...process.env, PORT: String(WEB_PORT), CIVIL_API: `http://127.0.0.1:${API_PORT}` },
  });
  step(await waitFor(`http://127.0.0.1:${API_PORT}/api/auth/state`), "backend up", `:${API_PORT}`);
  step(await waitFor(`${BASE}/login`), "web up", BASE);

  const browser = await chromium.launch({ headless: !args.has("--headed") });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  let where = "";
  page.on("pageerror", (e) => errors.push(`${where}: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && errors.push(`${where}: ${m.text()}`));
  page.on("response", (r) => {
    if (r.status() >= 500) errors.push(`${where}: HTTP ${r.status()} ${r.url()}`);
  });
  const settle = async (extra = 600) => {
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(extra);
  };
  const shot = (name, full = true) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full });
  const j = (p) => page.evaluate(async (u) => (await fetch(u)).json(), p);

  // 1. first-run setup
  where = "login";
  await page.goto(`${BASE}/login`);
  await settle();
  await page.getByLabel("Company or department").fill("Bang Sue District Works");
  await page.getByLabel("Your name").fill("Pitch Presenter");
  await page.getByLabel("Your username").fill("presenter");
  await shot("01-setup");
  await page.getByRole("button", { name: "Set up and sign in" }).click();
  step(await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 }).then(() => true, () => false), "first-run setup signs in");

  // 2. demo
  where = "demo";
  await settle();
  await page.getByRole("button", { name: /load demo/i }).first().click();
  let pid, before;
  const t0 = Date.now();
  for (;;) {
    const ps = await j("/api/projects").catch(() => []);
    if (ps.length) {
      const p = await j(`/api/projects/${ps[0].id}`);
      if (p.survey_list.length >= 2 && p.survey_list.every((s) => s.status === "done")) {
        pid = p.id;
        before = p.baseline;
        break;
      }
      if (p.survey_list.some((s) => s.status === "error")) break;
    }
    if (Date.now() - t0 > 120000) break;
    await page.waitForTimeout(1500);
  }
  step(!!pid, "demo loads and processes", pid ? `${Math.round((Date.now() - t0) / 1000)} s` : "timed out or failed");
  if (!pid) throw new Error("no demo project");
  const sel = `project=${pid}&survey=${before}`;
  const an = await j(`/api/projects/${pid}/surveys/${before}/analysis`);
  const high = an.findings.find((f) => f.severity === "high");

  // 3. every page at both widths: renders, no sideways scroll
  const pages = [
    ["/", /condition along the route/i],
    ["/findings", /finding/i],
    ["/map", null],
    [`/map?finding=${high.id}`, new RegExp(high.id)],
    ["/fix-first", /fix first/i],
    ["/plan", /repair plan/i],
    ["/verification", /verification/i],
    ["/surveys", /surveys/i],
    ["/report", /report/i],
    ["/team", /team/i],
    [`/job?finding=${high.id}`, /job card/i],
  ];
  for (const [w, h] of [
    [1440, 900],
    [390, 844],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    for (const [r, expect] of pages) {
      where = `${r} @${w}`;
      await page.goto(`${BASE}${r}${r.includes("?") ? "&" : "?"}${sel}`);
      await settle(r.startsWith("/map") ? 2500 : 800);
      const text = await page.locator("body").innerText();
      const ok = (!expect || expect.test(text)) && !/something went wrong|application error/i.test(text);
      const ov = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      step(ok && ov <= 1, `${r} renders @${w}`, ov > 1 ? `sideways scroll ${ov}px` : ok ? "" : "expected content missing");
      await shot(`page-${w}-${r.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "overview"}`, !r.startsWith("/map"));
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  // 4. the story
  where = "overview";
  await page.goto(`${BASE}/?${sel}`);
  await settle();
  const ovText = await page.locator("main").innerText();
  step(/242\s*m/.test(ovText) && /89/.test(ovText) && /10\s+open defects/i.test(ovText), "Overview headline: 242 m, 89/100, 10 open defects");

  where = "map";
  await page.goto(`${BASE}/map?${sel}`);
  await settle(2500);
  const marker = page.locator("button[aria-label*='severity']").first();
  step((await marker.count()) > 0, "map shows defect markers");
  await marker.click();
  await settle();
  step(/finding=/.test(page.url()), "clicking a marker opens the finding drawer");
  await shot("story-map-drawer", false);

  where = "plan";
  await page.goto(`${BASE}/plan?${sel}`);
  await settle();
  const planBefore = await page.locator("main").innerText();
  const slider = page.getByRole("slider").first();
  await slider.focus();
  for (let i = 0; i < 15; i++) await page.keyboard.press("ArrowLeft");
  await settle(1200);
  step((await page.locator("main").innerText()) !== planBefore, "budget slider re-plans");
  await shot("story-plan-budget");
  // back to no limit, then create the work order for everything
  for (let i = 0; i < 40; i++) await page.keyboard.press("ArrowRight");
  await settle(1200);
  await page.getByRole("button", { name: /create work order/i }).first().click();
  await page.waitForTimeout(800);
  const dlg = page.getByRole("dialog");
  if (await dlg.count()) await dlg.getByRole("button", { name: /create/i }).last().click();
  await settle(1500);
  const wos = await j(`/api/projects/${pid}/workorders`);
  step(wos.length === 1 && wos[0].items.length === 10, "work order created", wos.map((w) => `${w.id}: ${w.items.length} repairs`).join(", "));

  where = "job";
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE}/job?finding=${high.id}&${sel}`);
  await settle();
  step(/navigate/i.test(await page.locator("body").innerText()), "phone job card shows Navigate");
  await shot("story-job-card");
  await page.setViewportSize({ width: 1440, height: 900 });

  where = "verification";
  await page.goto(`${BASE}/verification?${sel}`);
  await settle();
  for (const name of [/mark scheduled/i, /mark completed/i]) {
    const b = page.getByRole("button", { name });
    if (await b.count()) {
      await b.first().click();
      await page.waitForTimeout(600);
      const d = page.getByRole("alertdialog").or(page.getByRole("dialog"));
      if (await d.count()) await d.getByRole("button").last().click();
      await settle(1000);
    }
  }
  const wo = (await j(`/api/projects/${pid}/workorders`))[0];
  step(wo?.status === "completed", "work order marked completed", wo?.status);
  await page.getByRole("button", { name: /run verification/i }).first().click();
  await settle(4000);
  const v = await j(`/api/projects/${pid}/verification`);
  step(v?.counts?.verified === 6 && v?.counts?.not_fixed === 4, "verification: 6 verified, 4 still present", JSON.stringify(v?.counts));
  await shot("story-verification");

  where = "report";
  await page.goto(`${BASE}/report?${sel}`);
  await settle();
  await page.emulateMedia({ media: "print" });
  await page.pdf?.({ path: path.join(OUT, "report.pdf"), format: "A4", printBackground: true }).catch(() => {});
  await page.emulateMedia({ media: "screen" });
  step(fs.existsSync(path.join(OUT, "report.pdf")), "report prints to PDF", "rehearsal/report.pdf");

  where = "team + phone";
  await page.goto(`${BASE}/team?${sel}`);
  await settle();
  await page.getByLabel(/^name$/i).fill("Somchai K.");
  await page.getByLabel(/^username$/i).fill("crew.somchai");
  await page.getByRole("button", { name: /^add$/i }).click();
  await settle(1000);
  const team = await j("/api/team");
  step(team.some((u) => u.username === "crew.somchai"), "Team: admin adds a crew member");
  await shot("story-team");
  // a second browser = the crew phone: its own device key
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const pp = await phone.newPage();
  pp.on("pageerror", (e) => errors.push(`phone: ${e.message}`));
  await pp.goto(`${BASE}/job?finding=${high.id}&${sel}`);
  await pp.waitForURL(/\/login/, { timeout: 15000 }).catch(() => {});
  await pp.getByLabel("Username").fill("crew.somchai");
  await pp.getByRole("button", { name: "Sign in" }).click();
  const back = await pp.waitForURL(/\/job/, { timeout: 15000 }).then(() => true, () => false);
  await pp.waitForLoadState("networkidle").catch(() => {});
  await pp.waitForTimeout(800);
  step(back && /navigate/i.test(await pp.locator("body").innerText()), "crew phone signs in and lands on the job card");
  await pp.screenshot({ path: path.join(OUT, "story-phone-job-card.png"), fullPage: true });
  await phone.close();

  where = "thai";
  await page.goto(`${BASE}/?${sel}`);
  await settle();
  await page.getByRole("button", { name: "เปลี่ยนเป็นภาษาไทย" }).click();
  await settle(400);
  const thText = await page.locator("body").innerText();
  step(/ภาพรวม/.test(thText) && /ข้อบกพร่อง/.test(thText), "Thai switch translates the Overview");
  await shot("story-overview-thai");
  await page.getByRole("button", { name: "Switch to English" }).click();
  await settle(300);

  where = "sign out";
  await page.goto(`${BASE}/?${sel}`);
  await settle();
  await page.getByRole("button", { name: /sign out|ออกจากระบบ/i }).first().click();
  step(await page.waitForURL(/\/login/, { timeout: 10000 }).then(() => true, () => false), "sign out");
  await page.getByLabel("Username").fill("presenter");
  await page.getByRole("button", { name: "Sign in" }).click();
  step(await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 }).then(() => true, () => false), "sign back in with the same device key");

  const real = errors.filter((e) => !/GL Driver|WebGL|GPU stall/i.test(e));
  step(real.length === 0, "no console errors or 5xx", real.slice(0, 5).join(" | "));
  await browser.close();
} catch (e) {
  step(false, "rehearsal aborted", e.message);
} finally {
  cleanup();
  fs.writeFileSync(path.join(OUT, "report.txt"), results.join("\n") + "\n");
  console.log(`\n${failed ? `\x1b[31m${failed} FAILED\x1b[0m` : "\x1b[32mALL PASSED\x1b[0m"}  · screenshots in ${path.relative(process.cwd(), OUT) || OUT}/`);
  process.exit(failed ? 1 : 0);
}

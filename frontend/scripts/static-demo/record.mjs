#!/usr/bin/env node
/**
 * Record qPilot's read-only online demo from the real server, check it, and assemble site/.
 *
 *   npm run build:demo
 *   QPILOT_PYTHON=…/.venv/bin/python QPILOT_DEMO_SEED=…/ui-seed/studies \
 *     nice -n 10 node scripts/static-demo/record.mjs
 *
 * 1. Copies the seeded store (a real Studio walk of the demo study and its audit) to a scratch
 *    folder and starts a real `qpilot app` on it (a fixed key, no model).
 * 2. Serves the BUILT demo page (dist-demo/) on that server's origin in Chromium, recording:
 *    every read the page makes goes to the server carrying the key the page computed for it
 *    (src/demo/install.ts), and the answer is kept under that key (the last answer wins). The
 *    walk (walk.mjs) visits every section, every gene, every tab, the palette and the drawers,
 *    and makes the default interactions. Writes are refused in the page and never sent.
 * 3. Asks the server again for any answer that was still loading, then writes site/demo-api/
 *    (one file per answer + index.json) and copies the page into site/.
 * 4. Serves site/ as Vercel will (serve.mjs, the headers of site/vercel.json) and walks it again:
 *    fails on any request without a recording, any request leaving the site, any console error.
 *
 * Options: --port N (the server, default 7960) · --verify (step 4 only) · --keep (keep the
 * scratch store) · --no-curves (skip the 25,000 well curves) · --only a,b (walk only these steps,
 * for development; nothing is written unless --write is given).
 */
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir, userInfo } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { chromium } from "@playwright/test";
import { serveSite, siteHeaders } from "./serve.mjs";
import { walk } from "./walk.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, "../..");
const REPO = resolve(FRONTEND, "..");
const DIST = join(FRONTEND, "dist-demo");
const SITE = join(REPO, "site");
const API_DIR = join(SITE, "demo-api");
const TOKEN = "qpilot-static-demo-recorder";
const KEEP_IN_SITE = new Set(["vercel.json", "README.md"]);

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const option = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const PORT = Number(option("--port", "7960"));
const ONLY = option("--only", "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

function log(...parts) {
  console.log(`[${new Date().toISOString().slice(11, 19)}]`, ...parts);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------------------------
// The real server

async function api(base, path, init = {}) {
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { "x-qpilot-token": TOKEN, "content-type": "application/json", ...init.headers },
  });
  const data = Buffer.from(await res.arrayBuffer());
  return { status: res.status, type: res.headers.get("content-type") ?? "", data };
}

const json = (r) => JSON.parse(r.data.toString("utf8"));

async function startServer(store, port) {
  const python = process.env.QPILOT_PYTHON ?? "python3";
  const env = {
    ...process.env,
    QPILOT_STUDIES_DIR: store,
    QPILOT_APP_TOKEN: TOKEN,
    QPILOT_MODEL_PROVIDER: "none",
    MPLBACKEND: "Agg",
    PYTHONPATH: [REPO, join(REPO, "sim", "src"), process.env.PYTHONPATH].filter(Boolean).join(":"),
  };
  const out = createWriteStream(join(dirname(store), "server.log"));
  const child = spawn(
    "nice",
    [
      "-n",
      "10",
      python,
      "-c",
      "import sys; from qpilot.cli import main; sys.exit(main(sys.argv[1:]))",
      "app",
      "--no-open",
      "--port",
      String(port),
    ],
    { env, stdio: ["ignore", "pipe", "pipe"] },
  );
  child.stdout.pipe(out);
  child.stderr.pipe(out);
  log(`qpilot app started (pid ${child.pid}) on :${port}, store ${store}`);
  const base = `http://127.0.0.1:${port}`;
  const until = Date.now() + 240_000;
  while (Date.now() < until) {
    if (child.exitCode !== null)
      throw new Error(`qpilot app exited (${child.exitCode}); see server.log`);
    try {
      if ((await api(base, "/api/system")).status === 200) return { child, base };
    } catch {
      /* not listening yet */
    }
    await sleep(1000);
  }
  throw new Error("qpilot app did not answer within 240 s");
}

/** Wait until no workspace is warming and no job is queued or running. */
async function serverQuiet(base, timeout = 600_000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    const ws = json(await api(base, "/api/workspaces")).workspaces;
    const jobs = json(await api(base, "/api/jobs"));
    const busy = jobs.filter((j) => j.status === "queued" || j.status === "running");
    if (!ws.some((w) => w.warming) && busy.length === 0) return;
    await sleep(1000);
  }
  throw new Error("the server stayed busy");
}

// ---------------------------------------------------------------------------------------------
// The browser

/** Track a page's requests, console errors and (in the demo) its misses. */
function watch(page, origin) {
  const state = { inflight: new Set(), errors: [], outbound: [], busy: [], apiCalls: 0, step: "" };
  page.on("console", (msg) => {
    if (msg.type() === "error") state.errors.push(`[${state.step}] ${msg.text()}`);
  });
  page.on("pageerror", (e) => state.errors.push(`[${state.step}] uncaught: ${e.message}`));
  page.on("request", (req) => {
    const url = req.url();
    if (!url.startsWith(origin) && !/^(data|blob):/.test(url)) {
      state.outbound.push(`[${state.step}] ${req.method()} ${url}`);
    }
    if (url.includes("/api/") || url.includes("/demo-api/")) state.apiCalls += 1;
    if (!url.includes("/api/events")) state.inflight.add(req);
  });
  const done = (req) => state.inflight.delete(req);
  page.on("requestfinished", done);
  page.on("requestfailed", done);
  return state;
}

/**
 * Wait until the page has nothing loading (no request in flight, no skeleton, nothing marked
 * busy) for half a second; while recording, until the server's jobs are done as well.
 */
function settler(page, state, base) {
  return async function settle(timeout = 30_000) {
    const until = Date.now() + timeout;
    let quietSince = 0;
    let lastJobs = 0;
    let busyJobs = [];
    let busyDom = 0;
    while (Date.now() < until) {
      busyDom = await page
        .locator(".qp-skeleton, [aria-busy=true]")
        .count()
        .catch(() => 0);
      if (base && Date.now() - lastJobs > 700) {
        lastJobs = Date.now();
        try {
          const jobs = json(await api(base, "/api/jobs"));
          busyJobs = jobs.filter((j) => j.status === "queued" || j.status === "running");
        } catch {
          busyJobs = [];
        }
      }
      if (state.inflight.size === 0 && busyDom === 0 && busyJobs.length === 0) {
        if (!quietSince) quietSince = Date.now();
        if (Date.now() - quietSince >= 500) break;
      } else {
        quietSince = 0;
      }
      await page.waitForTimeout(100);
    }
    if (Date.now() >= until) {
      state.busy.push(state.step);
      const urls = [...state.inflight]
        .slice(0, 3)
        .map((r) => r.url().replace(/^https?:\/\/[^/]+/, ""));
      log(
        `  (still busy after ${timeout / 1000} s at ${state.step}: ${state.inflight.size} requests ` +
          `${urls.join(" ")}; ${busyDom} busy on the page; jobs ${busyJobs.map((j) => j.kind).join(",")})`,
      );
    }
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
  };
}

/** Serve dist-demo/ on the server's origin (the API goes through to the server). */
async function serveDistOn(context, origin, headers) {
  await context.route(
    (url) => url.origin === origin && !url.pathname.startsWith("/api/"),
    async (route) => {
      const { pathname } = new URL(route.request().url());
      const file = resolve(
        DIST,
        pathname === "/" ? "index.html" : `.${decodeURIComponent(pathname)}`,
      );
      if (!file.startsWith(DIST + sep) || !existsSync(file) || !statSync(file).isFile()) {
        await route.fulfill({ status: 404, body: "not found", headers });
        return;
      }
      await route.fulfill({ path: file, headers });
    },
  );
}

// ---------------------------------------------------------------------------------------------
// Recording

async function record(base) {
  const recordings = new Map();
  let seq = 0;
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "en-GB",
    timezoneId: "Europe/London",
    colorScheme: "light",
    acceptDownloads: true,
    extraHTTPHeaders: { "x-qpilot-token": TOKEN },
  });
  await context.addInitScript(() => {
    window.__QPILOT_DEMO_RECORD__ = true;
  });
  await serveDistOn(context, base, siteHeaders(SITE));
  const page = await context.newPage();
  const state = watch(page, base);
  page.on("response", (res) => {
    const req = res.request();
    const key = req.headers()["x-qpilot-demo-key"];
    if (!key) return;
    const n = ++seq;
    const url = new URL(req.url());
    void res
      .body()
      .then((data) => {
        const old = recordings.get(key);
        if (old && old.seq > n) return;
        recordings.set(key, {
          seq: n,
          method: req.method(),
          path: url.pathname,
          query: url.search,
          body: req.postData() ?? null,
          status: res.status(),
          type: res.headers()["content-type"] ?? "",
          data,
        });
      })
      .catch(() => {});
  });

  const settle = settler(page, state, base);
  const stats = await walk({ page, base, mode: "record", settle, log, state, only: ONLY });
  await settle();
  await page.waitForTimeout(1000);
  await browser.close();
  log(`recorded ${recordings.size} answers (${state.apiCalls} API requests in the walk)`);
  if (state.errors.length) {
    log(`console errors while recording (${state.errors.length}), first ones:`);
    for (const e of state.errors.slice(0, 15)) log("  ", e.slice(0, 300));
  }
  return { recordings, stats };
}

/** Answers that were still loading (409 "loading", a warming frame, running jobs): ask again. */
async function settleRecordings(base, recordings) {
  await serverQuiet(base);
  let refreshed = 0;
  const problems = [];
  for (const [key, r] of recordings) {
    const loading =
      r.status === 409 ||
      r.status >= 500 ||
      /^\/api\/(jobs(\/[^/]+)?|workspaces|system|sessions\/[^/]+)$/.test(r.path) ||
      (r.type.startsWith("application/json") && /"warming":\s*true/.test(r.data.toString("utf8")));
    if (!loading) continue;
    if (r.method !== "GET" && r.status !== 409) continue;
    let fresh = null;
    for (let i = 0; i < 60; i += 1) {
      fresh = await api(base, `${r.path}${r.query}`, {
        method: r.method,
        ...(r.body != null ? { body: r.body } : {}),
      });
      const warming =
        fresh.type.startsWith("application/json") &&
        /"warming":\s*true/.test(fresh.data.toString("utf8"));
      if (fresh.status !== 409 && !warming) break;
      await sleep(2000);
    }
    if (fresh.status >= 200 && fresh.status < 300) {
      recordings.set(key, { ...r, status: fresh.status, type: fresh.type, data: fresh.data });
      refreshed += 1;
    } else if (r.status === 409 || r.status >= 500) {
      problems.push(`${fresh.status} ${r.method} ${r.path}${r.query}`);
    }
  }
  log(`asked the server again for ${refreshed} answers`);
  for (const p of problems) log("  still not answered:", p);
  return problems;
}

// ---------------------------------------------------------------------------------------------
// Every well's curve (about 25,000): read straight from the server, packed by plate

async function recordCurves(base, sid) {
  const plate0 = json(await api(base, `/api/sessions/${sid}/plate`));
  const packs = new Map();
  let wells = 0;
  for (const run of plate0.runs) {
    const plate = json(
      await api(base, `/api/sessions/${sid}/plate?run=${encodeURIComponent(run.run_id)}`),
    );
    const pack = {};
    const queue = plate.wells.map((w) => w.well);
    const worker = async () => {
      while (queue.length) {
        const well = queue.shift();
        const q = new URLSearchParams({ well: `${run.run_id}/${well}` });
        const r = await api(base, `/api/sessions/${sid}/curve?${q}`);
        if (r.status === 200) pack[well] = JSON.parse(r.data.toString("utf8"));
      }
    };
    await Promise.all(Array.from({ length: 6 }, worker));
    packs.set(run.run_id, pack);
    wells += Object.keys(pack).length;
  }
  log(`curves: ${wells} wells on ${packs.size} plates`);
  return { [sid]: packs };
}

// ---------------------------------------------------------------------------------------------
// The site

/** What must never be published: this computer's paths, user names, the recorder's key. */
function privateStrings() {
  const out = new Set([homedir(), userInfo().username, TOKEN, "/var/folders/", "/private/var/"]);
  for (const field of ["user.email", "user.name"]) {
    const v = spawnSync("git", ["config", field], { encoding: "utf8" }).stdout?.trim();
    if (v) out.add(v);
  }
  return [...out].filter((v) => v && v.length >= 4);
}

/** Local paths in an answer become qPilot's defaults (`~/.cache/qpilot/…`). */
function scrubber(work) {
  const roots = [
    [realpathSync(work), "~/.cache/qpilot"],
    [work, "~/.cache/qpilot"],
    [REPO, "~/qpilot"],
    [homedir(), "~"],
  ];
  return (text) => roots.reduce((t, [from, to]) => t.split(from).join(to), text);
}

const TEXT = /^(application\/(json|xml|javascript|x-ndjson)|text\/)/;

/** Zip-based downloads (xlsx, zip): the text inside each member, for the privacy check. */
function zipText(data) {
  const python = process.env.QPILOT_PYTHON ?? "python3";
  const script =
    "import io,sys,zipfile; z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); " +
    "sys.stdout.write(''.join(z.read(n).decode('utf8','replace') for n in z.namelist()))";
  const r = spawnSync(python, ["-c", script], { input: data, maxBuffer: 512e6 });
  return r.status === 0 ? r.stdout.toString("utf8") : null;
}

const gz = (buf) => gzipSync(buf, { level: 9 });

function assemble(recordings, curves, work) {
  if (!existsSync(DIST)) throw new Error("dist-demo/ is missing: run `npm run build:demo` first");
  mkdirSync(SITE, { recursive: true });
  for (const name of readdirSync(SITE)) {
    if (!KEEP_IN_SITE.has(name)) rmSync(join(SITE, name), { recursive: true, force: true });
  }
  cpSync(DIST, SITE, { recursive: true });
  mkdirSync(join(API_DIR, "curves"), { recursive: true });
  const scrub = scrubber(work);
  const secrets = privateStrings();
  const leaks = (text) => secrets.filter((x) => text.includes(x));
  const entries = {};
  const dropped = [];
  let raw = 0;
  let stored = 0;
  const sorted = [...recordings.entries()].sort(([, a], [, b]) =>
    `${a.path}${a.query}${a.method}`.localeCompare(`${b.path}${b.query}${b.method}`),
  );
  for (const [key, r] of sorted) {
    const type = r.type.split(";")[0].trim();
    let data = r.data;
    if (TEXT.test(type)) {
      let text = scrub(data.toString("utf8"));
      if (type === "application/json" && text) text = JSON.stringify(JSON.parse(text));
      const found = leaks(text);
      if (found.length) throw new Error(`private text left in ${r.method} ${r.path}: ${found}`);
      data = Buffer.from(text, "utf8");
    } else {
      const inside = data.subarray(0, 4).equals(Buffer.from("PK\x03\x04", "latin1"))
        ? zipText(data)
        : data.toString("latin1");
      const found = inside === null ? ["(unreadable zip)"] : leaks(inside);
      if (found.length) {
        dropped.push(`${r.method} ${r.path}${r.query} (${type})`);
        continue;
      }
    }
    const packed = gz(data);
    writeFileSync(join(API_DIR, `${key}.gz`), packed);
    raw += data.length;
    stored += packed.length;
    entries[key] = {
      s: r.status,
      ...(type === "application/json" ? {} : { t: r.type }),
      m: r.method,
      p: scrub(`${r.path}${r.query}`),
      ...(r.body ? { b: scrub(r.body.length > 300 ? `${r.body.slice(0, 300)}…` : r.body) } : {}),
    };
  }
  const curveIndex = {};
  let curveFiles = 0;
  for (const [sid, plates] of Object.entries(curves)) {
    curveIndex[sid] = {};
    for (const [run, pack] of plates) {
      const name = createHash("sha256").update(`${sid}/${run}`).digest("hex").slice(0, 24);
      const text = scrub(JSON.stringify(pack));
      const found = leaks(text);
      if (found.length) throw new Error(`private text left in the curves of ${run}: ${found}`);
      const packed = gz(Buffer.from(text, "utf8"));
      writeFileSync(join(API_DIR, "curves", `${name}.gz`), packed);
      raw += text.length;
      stored += packed.length;
      curveFiles += 1;
      curveIndex[sid][run] = name;
    }
  }
  const index = {
    note: "qPilot read-only online demo: answers recorded from a real `qpilot app` on the public Vermeulen 2009 / Ruijter 2013 neuroblastoma study (CC BY 4.0). Key = SHA-256 of method, path, sorted query and canonical JSON body (frontend/src/demo/key.ts); bodies are gzipped.",
    recorded_at: new Date().toISOString(),
    entries,
    curves: curveIndex,
  };
  const indexText = JSON.stringify(index);
  if (leaks(indexText).length)
    throw new Error(`private text left in index.json: ${leaks(indexText)}`);
  writeFileSync(join(API_DIR, "index.json"), indexText);
  for (const d of dropped) log("  not published (a local path inside the file):", d);
  log(
    `site/ assembled: ${Object.keys(entries).length} answers + ${curveFiles} curve packs, ` +
      `${(raw / 1e6).toFixed(1)} MB of answers stored as ${(stored / 1e6).toFixed(1)} MB gzipped`,
  );
  return { count: Object.keys(entries).length, raw, stored, dropped };
}

// ---------------------------------------------------------------------------------------------
// Verification: the site as Vercel serves it

async function verify() {
  const server = await serveSite(SITE, 0);
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "en-GB",
    timezoneId: "Europe/London",
    colorScheme: "light",
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const state = watch(page, server.url);
  const missing = [];
  page.on("response", (res) => {
    if (res.status() >= 400) missing.push(`${res.status()} ${res.request().method()} ${res.url()}`);
  });
  const settle = settler(page, state, null);
  const stats = await walk({
    page,
    base: server.url,
    mode: "verify",
    settle,
    log,
    state,
    only: ONLY,
  });
  await settle();
  const misses = [...stats.misses];
  await browser.close();
  await server.close();
  const failures = [
    ...misses.map((m) => `no recording: ${m}`),
    ...missing.map((m) => `failed load: ${m}`),
    ...state.outbound.map((m) => `left the site: ${m}`),
    ...state.errors.map((m) => `console: ${m}`),
    ...state.busy.map((m) => `still loading after 30 s: ${m}`),
  ];
  log(`verify: ${state.apiCalls} requests to the API and recordings, ${failures.length} problems`);
  for (const f of failures.slice(0, 60)) log("  ", f.slice(0, 400));
  return { failures, stats };
}

// ---------------------------------------------------------------------------------------------

async function main() {
  if (!flag("--verify")) {
    const seed = process.env.QPILOT_DEMO_SEED;
    if (!seed || !existsSync(seed)) throw new Error("set QPILOT_DEMO_SEED to the seeded store");
    if (!existsSync(join(DIST, "index.html"))) throw new Error("run `npm run build:demo` first");
    const work = join(tmpdir(), `qpilot-static-demo-${PORT}`);
    rmSync(work, { recursive: true, force: true });
    mkdirSync(work, { recursive: true });
    const store = join(work, "studies");
    cpSync(seed, store, { recursive: true });
    log(`store copied from ${seed}`);
    const { child, base } = await startServer(store, PORT);
    try {
      await serverQuiet(base);
      const { recordings, stats } = await record(base);
      const problems = await settleRecordings(base, recordings);
      if (ONLY.length && !flag("--write")) {
        log("--only: nothing written (add --write to assemble anyway)");
        return;
      }
      const curves = flag("--no-curves") ? {} : await recordCurves(base, stats.sid);
      assemble(recordings, curves, work);
      if (problems.length) log(`${problems.length} answers were still loading (see above)`);
    } finally {
      child.kill("SIGTERM");
      log(`qpilot app stopped (pid ${child.pid})`);
      if (!flag("--keep")) rmSync(work, { recursive: true, force: true });
    }
  }
  const { failures } = await verify();
  if (failures.length) {
    log("FAILED: the site does not answer everything the walk asked for");
    process.exitCode = 1;
  } else {
    log("OK: every request answered from the recordings, nothing left the site, no console error");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

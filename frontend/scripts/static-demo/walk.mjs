/**
 * The walk through the whole page that record.mjs makes twice: once on the real server to record
 * every answer (mode "record"), once on the assembled site to check that every request has its
 * recording (mode "verify"). Both walks make the same moves, so they ask for the same keys.
 *
 * What the page shows (the session, the study, its genes, the audit's choices, the history's
 * steps) is read from the API through the page itself, so the walk works from the recordings
 * too; nothing is hand-written. Where a section asks for one of many things (a plate, a gene's
 * curve calls, a trace plate), every one is also asked for through the page's own fetch, under
 * the same key the section would use.
 */

/** Read an API answer through the page (recorded by the shim, or answered from a recording). */
export async function apiGet(page, path, { tries = 90 } = {}) {
  for (let i = 0; ; i += 1) {
    const out = await page.evaluate(async (p) => {
      const r = await fetch(p, { credentials: "same-origin" });
      return { status: r.status, body: await r.json().catch(() => null) };
    }, path);
    if (out.status >= 200 && out.status < 300) return out.body;
    // 409 "loading" / 503 "warming": a job is preparing this view; ask again (as the page does).
    if ((out.status === 409 || out.status === 503) && i < tries) {
      await page.waitForTimeout(2000);
      continue;
    }
    throw new Error(`${out.status} ${path}`);
  }
}

/** Ask for many GETs through the page, a few at a time; returns how many answered 2xx. */
export async function fetchAll(page, paths, concurrency = 6) {
  return page.evaluate(
    async ({ paths, concurrency }) => {
      const queue = [...paths];
      let ok = 0;
      const worker = async () => {
        while (queue.length) {
          const p = queue.shift();
          for (let i = 0; i < 60; i += 1) {
            const r = await fetch(p, { credentials: "same-origin" }).catch(() => null);
            if (r && (r.status === 409 || r.status === 503)) {
              await r.arrayBuffer().catch(() => null);
              await new Promise((ok) => setTimeout(ok, 1500));
              continue;
            }
            // Read the body: the request only finishes (and is recorded) once it is read.
            await r?.arrayBuffer().catch(() => null);
            if (r?.ok) ok += 1;
            break;
          }
        }
      };
      await Promise.all(Array.from({ length: concurrency }, worker));
      return ok;
    },
    { paths, concurrency },
  );
}

export function helpers({ page, base, settle, log, state }) {
  const misses = new Set();

  async function collect() {
    const got = await page
      .evaluate(() => (window.__QPILOT_DEMO_MISSES__ ?? []).splice(0))
      .catch(() => []);
    for (const m of got) misses.add(m);
  }

  /** Open the page fresh at a hash route (a full load, as a visitor's link would). */
  async function load(hash = "/") {
    await collect();
    state.step = `load ${hash}`;
    await page.goto(`${base}/#${hash}`);
    await settle();
    await collect();
  }

  /** Move to a hash route inside the page (as the rail and links do). */
  async function go(hash) {
    state.step = hash;
    await page.evaluate((h) => {
      location.hash = h;
    }, hash);
    await settle();
    await collect();
  }

  /** Click something if it is there and enabled; returns whether it was clicked. */
  async function click(locator, what, { quiet = false } = {}) {
    const target = locator.first();
    if (
      !(await target.count()) ||
      !(await target.isVisible().catch(() => false)) ||
      !(await target.isEnabled().catch(() => false))
    ) {
      if (!quiet) log(`  (not there: ${what})`);
      return false;
    }
    try {
      await target.scrollIntoViewIfNeeded({ timeout: 5000 });
      await target.click({ timeout: quiet ? 3000 : 10_000 });
    } catch (e) {
      log(`  (could not click ${what}: ${String(e).split("\n")[0]})`);
      return false;
    }
    await settle();
    await collect();
    return true;
  }

  const main = () => page.locator("main");

  /** Click every tab of every tab list in a scope, then come back to the first one. */
  async function everyTab(scope = main()) {
    const lists = scope.getByRole("tablist");
    const n = await lists.count();
    for (let i = 0; i < n; i += 1) {
      const tabs = lists.nth(i).getByRole("tab");
      const m = await tabs.count();
      for (let j = 0; j < m; j += 1) await click(tabs.nth(j), `tab ${j + 1} of list ${i + 1}`);
      if (m) await click(tabs.nth(0), "the first tab");
    }
  }

  /** Open the closed disclosures (<details>) in a scope, at most `max`. */
  async function openDetails(scope = main(), max = 30) {
    for (let i = 0; i < max; i += 1) {
      const closed = scope.locator("details:not([open]) > summary");
      if (!(await closed.count())) break;
      if (!(await click(closed.first(), "a closed disclosure", { quiet: true }))) break;
    }
  }

  async function press(keys) {
    state.step = `key ${keys}`;
    await page.keyboard.press(keys);
    await settle();
    await collect();
  }

  return { misses, collect, load, go, click, everyTab, openDetails, press, main };
}

export async function walk(ctx) {
  const { page, log, only } = ctx;
  const h = helpers(ctx);
  const want = (name) => !only?.length || only.includes(name);

  await h.load("/");
  const ws = await apiGet(page, "/api/workspaces");
  const session = ws.workspaces.find((w) => w.is_demo && w.kind === "session");
  if (!session?.study_id) throw new Error("the demo session (with its study) is not in the store");
  const sid = session.key;
  const study = session.study_id;
  const S = (section, ...rest) =>
    `/s/${sid}/${[section, ...rest].map((x) => encodeURIComponent(x)).join("/")}`;
  const results = await apiGet(page, `/api/studies/${study}/results`);
  const genes = results.genes.map((g) => g.gene);
  log(`walk (${ctx.mode}): session ${sid}, study ${study}, ${genes.length} genes`);

  const run = { ...ctx, ...h, sid, study, S, genes, results };
  for (const step of STEPS) {
    if (!want(step.name)) continue;
    const t0 = Date.now();
    log(`- ${step.name}`);
    ctx.state.step = step.name;
    await step.run(run);
    log(`  ${step.name} done in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
  }
  await h.collect();
  return { misses: h.misses, genes: genes.length, sid, study };
}

const role = (page, r, name) => page.getByRole(r, { name });

/** The walk, section by section (see each section's controls in src/features/<id>). */
const STEPS = [
  {
    name: "open",
    run: async ({ page, go, click, load, sid }) => {
      await go("/");
      // "Continue the demo": the demo's session is in the store, so this is a link to it.
      await click(role(page, "link", /^Continue the demo/), "Continue the demo");
      await go("/");
      await page
        .getByRole("textbox", { name: /Filter recent/ })
        .fill("Vermeulen")
        .catch(() => {});
      await load("/");
    },
  },
  {
    name: "global",
    run: async ({ page, go, everyTab, openDetails }) => {
      await go("/settings");
      await everyTab();
      await openDetails();
      await go("/sheetcheck");
      await go("/instruments");
      const list = await apiGet(page, "/api/instruments");
      for (const i of list.instruments ?? [])
        await go(`/instruments/${encodeURIComponent(i.instrument_id)}`);
    },
  },
  {
    name: "design",
    run: async ({ page, go, click, S, sid, log }) => {
      await go(S("design"));
      const plate = await apiGet(page, `/api/sessions/${sid}/plate`);
      const runs = plate.runs.map((r) => r.run_id);
      const ok = await fetchAll(
        page,
        runs.map((r) => `/api/sessions/${sid}/plate?run=${encodeURIComponent(r)}`),
      );
      log(`  ${ok}/${runs.length} plates`);
      // The decided proposals (read-only once the stage is confirmed), and a few of them opened.
      await click(role(page, "button", /^Decided in this stage/), "Decided in this stage");
      const rows = page.locator("main [aria-expanded=false]");
      for (let i = 0; i < Math.min(await rows.count(), 6); i += 1)
        await click(rows.nth(i), `decided row ${i + 1}`, { quiet: true });
      // The plate picker, as a person uses it.
      const select = role(page, "combobox", /^Plate/);
      if (await select.count()) {
        await click(select, "the plate picker");
        await click(page.getByRole("option").nth(1), "another plate");
      }
    },
  },
  {
    name: "curves",
    run: async ({ page, go, click, S, sid, log }) => {
      await go(S("curves"));
      const plate = await apiGet(page, `/api/sessions/${sid}/plate`);
      const targets = [...new Set(plate.runs.flatMap((r) => r.targets))];
      const ok = await fetchAll(
        page,
        targets.map((g) => `/api/sessions/${sid}/curve-calls?gene=${encodeURIComponent(g)}`),
      );
      log(`  ${ok}/${targets.length} genes' curve calls`);
      const runs = plate.runs.filter((r) => r.in_design).map((r) => r.run_id);
      for (const r of runs.slice(0, 3)) {
        await go(S("curves", r));
        await click(page.locator("main [role=gridcell]").nth(30), "a well");
        await go(S("curves", r, "A1,B2,C3"));
      }
      await click(role(page, "button", /^Next plate/), "Next plate");
      await click(role(page, "button", /^Previous plate/), "Previous plate");
    },
  },
  {
    name: "results",
    run: async ({ page, go, click, everyTab, openDetails, S, study }) => {
      await go(S("results"));
      await everyTab();
      await openDetails();
      const cards = await apiGet(page, `/api/studies/${study}/cards`);
      for (const c of cards.cards ?? []) await go(S("results", "card", c.id));
      await go(S("results", "confirm"));
      await go(S("results"));
      const expand = page.locator("main button[aria-expanded=false]");
      for (let i = 0; i < Math.min(await expand.count(), 8); i += 1)
        await click(expand.nth(i), `results disclosure ${i + 1}`, { quiet: true });
    },
  },
  {
    name: "gate",
    run: async ({ page, go, click, openDetails, S }) => {
      await go(S("gate"));
      await openDetails();
      const rules = page.locator("main button[aria-expanded=false]");
      for (let i = 0; i < Math.min(await rules.count(), 10); i += 1)
        await click(rules.nth(i), `gate rule ${i + 1}`, { quiet: true });
    },
  },
  {
    name: "genes",
    run: async ({ page, go, click, S, genes }) => {
      await go(S("gene"));
      for (const g of genes) {
        await go(S("gene", g));
        // A sample's curve (from its plate's pack) and the jump links.
        await click(role(page, "button", /^View as table/), `${g}: samples as a table`, {
          quiet: true,
        });
      }
    },
  },
  {
    name: "audit",
    run: async ({ page, go, click, everyTab, openDetails, S, study, log }) => {
      await go(S("audit"));
      await everyTab();
      await openDetails();
      const overview = await apiGet(page, `/api/studies/${study}/audit/overview`);
      await go(S("audit", "whatif"));
      await click(role(page, "button", /^Show your choices/), "Show your choices", { quiet: true });
      await click(role(page, "button", /^Back to your planned analysis/), "Back to planned", {
        quiet: true,
      });
      let n = 0;
      for (const d of overview.decisions) {
        for (const o of d.options) {
          if (o.id === d.baseline) continue;
          await go(S("audit", "whatif", `${d.id}=${o.id}`));
          n += 1;
        }
      }
      log(`  ${n} what-if choices`);
      await go(S("audit", "how"));
      await openDetails();
      await go(S("audit", "verify"));
      const files = await apiGet(page, `/api/studies/${study}/audit/files`);
      const sizes = Object.fromEntries((files.files ?? []).map((f) => [f.name, f.bytes]));
      const clicked = await clickDownloads(page, sizes);
      log(`  ${clicked} audit files downloaded`);
      await click(role(page, "button", /^(Check again|Verify again|Re-check)/), "verify again", {
        quiet: true,
      });
    },
  },
  {
    name: "trace",
    run: async ({ page, go, click, S, sid, study, genes, log }) => {
      await go(S("trace"));
      await click(role(page, "button", /^Show all \d+/), "Show all (where to look)", {
        quiet: true,
      });
      const plate = await apiGet(page, `/api/sessions/${sid}/plate`);
      const ok = await fetchAll(
        page,
        plate.runs.map(
          (r) => `/api/studies/${study}/trace/plate?run=${encodeURIComponent(r.run_id)}`,
        ),
      );
      log(`  ${ok}/${plate.runs.length} trace plates`);
      for (const g of genes) {
        await go(S("trace", g));
        await click(role(page, "button", /^Show all \d+/), `${g}: show all places`, {
          quiet: true,
        });
        if (
          await click(role(page, "button", /^Set (it|these [\d,]+) aside/), `${g}: set aside`, {
            quiet: true,
          })
        )
          await click(role(page, "button", /^Put back/), `${g}: put back`, {
            quiet: true,
          });
      }
    },
  },
  {
    name: "claims",
    run: async ({ page, go, click, S }) => {
      await go(S("claims"));
      await click(role(page, "button", /^Try an example/), "Try an example");
      await page.waitForTimeout(500);
    },
  },
  {
    name: "prism",
    run: async ({ go, openDetails, S }) => {
      await go(S("prism"));
      await openDetails();
    },
  },
  {
    name: "report",
    run: async ({ page, go, click, openDetails, S, study, log }) => {
      await go(S("report"));
      await openDetails();
      for (const label of [
        /^Write the Markdown/,
        /^Write the printable page/,
        /^Write the passport/,
        /^Write the workbook/,
      ]) {
        await click(role(page, "button", label), String(label));
      }
      await go(S("report"));
      const exports = await apiGet(page, `/api/studies/${study}/report/exports`);
      const sizes = {};
      for (const e of exports.exports ?? []) {
        sizes[e.download.name] = e.download.bytes;
        if (e.record) sizes[e.record.download.name] = e.record.download.bytes;
      }
      log(`  ${await clickDownloads(page, sizes)} report files downloaded`);
    },
  },
  {
    name: "record",
    run: async ({ page, go, everyTab, openDetails, S, study, log }) => {
      await go(S("record"));
      await everyTab();
      await openDetails(undefined, 12);
      const records = await apiGet(page, `/api/studies/${study}/records`);
      const sizes = {};
      for (const r of records.records ?? []) sizes[r.download.name] = r.download.bytes;
      log(`  ${await clickDownloads(page, sizes)} records downloaded`);
    },
  },
  {
    name: "history",
    run: async ({ page, go, click, S, study, log }) => {
      await go(S("history"));
      const history = await apiGet(page, `/api/studies/${study}/history`);
      const seqs = (history.steps ?? []).map((s) => s.seq);
      const pairs = [];
      for (const a of seqs) for (const b of seqs) if (a !== b) pairs.push([a, b]);
      const ok = await fetchAll(page, [
        ...pairs.map(([a, b]) => `/api/studies/${study}/history/diff?from=${a}&to=${b}`),
        ...(history.related ?? []).map(
          (r) => `/api/studies/${study}/history/compare?other=${encodeURIComponent(r.study_id)}`,
        ),
      ]);
      log(`  ${ok} diffs and comparisons`);
      for (let i = 0; i <= seqs.length; i += 1)
        if (!(await click(role(page, "button", /^Previous point/), "Previous", { quiet: true })))
          break;
      for (let i = 0; i <= seqs.length; i += 1)
        if (!(await click(role(page, "button", /^Next point/), "Next", { quiet: true }))) break;
      // The earlier analysis the timeline links to: its history, results and gene pages.
      for (const r of history.related ?? []) {
        await go(`/r/${r.study_id}/history`);
        await go(`/r/${r.study_id}/results`);
        const earlier = await apiGet(page, `/api/studies/${r.study_id}/results`);
        for (const g of earlier.genes ?? [])
          await go(`/r/${r.study_id}/gene/${encodeURIComponent(g.gene)}`);
      }
      await go(S("history"));
    },
  },
  {
    name: "planner",
    run: async ({ page, go, click, S }) => {
      await go(S("planner"));
      await page.waitForTimeout(1500);
      await go(S("planner"));
      for (let i = 0; i < 3; i += 1)
        await click(role(page, "button", /^New random order/), "New random order");
    },
  },
  {
    name: "agents",
    run: async ({ go, S }) => {
      await go(S("agents"));
    },
  },
  {
    name: "shell",
    run: async ({ page, go, click, press, S, log }) => {
      await go(S("results"));
      // The palette (⌘K), the shortcut sheet (?), the agent bell.
      await press("ControlOrMeta+k");
      await page.keyboard.type("ODC1");
      await press("Escape");
      await press("?");
      await press("Escape");
      await click(
        page.getByRole("button", { name: /^(Agent requests|\d+ agent request|\d+ running)/ }),
        "the bell",
      );
      await press("Escape");
      // Ask (⌘J): every example question, one after the other, and what the model saw.
      await press("ControlOrMeta+j");
      const drawer = page.getByRole("dialog", { name: /Ask your data/ });
      const examples = () => drawer.locator("ul > li > button");
      const n = await examples().count();
      for (let i = 0; i < n; i += 1) {
        if (!(await click(examples().nth(i), `Ask example ${i + 1}`))) continue;
        await page.waitForTimeout(1000);
        await click(drawer.getByRole("button", { name: /^Clear the conversation/ }), "clear");
      }
      log(`  ${n} Ask examples`);
      await click(drawer.getByRole("button", { name: /What the model saw/ }), "What the model saw");
      await press("Escape");
    },
  },
];

/** Click the download links in <main> whose files are small enough to publish. */
async function clickDownloads(page, sizes, maxBytes = 5e6) {
  const links = page.locator('main a[download][href^="/api/"]');
  const n = await links.count();
  let clicked = 0;
  for (let i = 0; i < n; i += 1) {
    const link = links.nth(i);
    const name = await link.getAttribute("download");
    if (!(name in sizes) || sizes[name] > maxBytes) continue;
    const done = page.waitForEvent("download", { timeout: 30_000 }).catch(() => null);
    try {
      await link.scrollIntoViewIfNeeded({ timeout: 5000 });
      await link.click({ timeout: 10_000 });
      await done;
      clicked += 1;
    } catch {
      /* not clickable */
    }
  }
  await page.waitForTimeout(500);
  return clicked;
}

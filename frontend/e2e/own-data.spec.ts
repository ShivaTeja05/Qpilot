/**
 * A lab's own file, no model, through the page: the LightCycler 96 experiment file of the corpus
 * (`rdml/lightcycler96-lc96p-hmuy`: P. endodontalis hmuY and 16S rRNA, six samples in triplicate,
 * SYBR Green I, a melt in 0.2 °C steps; the depositors' conditions Hm and DIP) is opened on Open,
 * the design is set on the Design page ("Set the design on this page": the targets' roles, the
 * groups, the comparison), the rules' proposals are decided, the curves are checked and
 * confirmed, and the Results show the gene the person said they study. Then the melt: the Curves
 * melt panel and the Controls' G-MELT lines, against the melt API of the same study.
 *
 * The server must run with QPILOT_MODEL_PROVIDER=none (agent-bus/ex-env.sh sets it); the spec
 * checks that the page says no model is in use. It writes a new session: run it on a fresh store
 * copy (e2e/reset-store.sh).
 */
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { components } from "../src/api/schema";
import { literal } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import {
  CORPUS,
  checkFile,
  download,
  goTo,
  jobsDone,
  openFiles,
  resultsOf,
  reviewStage,
  sessionOf,
  settledJson,
  studyOf,
} from "./support/studio";

type S = components["schemas"];

const FILE = "hmuy_hm_vs_dip_r123.lc96p";
const LC96P = join(CORPUS, "rdml", "lightcycler96-lc96p-hmuy", FILE);
const REASON = "e2e: the depositors' conditions (Zenodo 14965510)";
/** The file's samples are named from their RDML description: Hm_1…3 and DIP_1…3. */
const CONDITIONS = { Hm: "Hm_*", DIP: "DIP_*" } as const;

/** Shared by the tests of this file, in order: the session opened and its study. */
const walked: { sid?: string; study?: string } = {};

test.describe("a LightCycler 96 file with no model", () => {
  // In order (one worker): the walk first; each later test reads the walked session from the
  // server and is skipped, not failed, when it is not there.
  test.describe.configure({ mode: "default" });
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");

  test("Open → Design set on the page → Curves → Results", async ({ app, api }) => {
    test.setTimeout(20 * 60_000);
    const before = await sessionOf(api, FILE);
    test.skip(
      Boolean(before?.results_visible),
      "this store already walked the file: re-copy the seed (e2e/reset-store.sh)",
    );
    const page = app.page;
    const main = page.getByRole("main");
    const sid = await openFiles(app, [LC96P]);
    walked.sid = sid;
    await expect(page).toHaveURL(new RegExp(`#/s/${sid}/design`));

    // No model: the rules alone propose (the page says which model, if any, is in use).
    const system = (await (await api.get("/api/system")).json()) as {
      model?: { provider?: string };
    };
    expect(system.model?.provider ?? "none").toBe("none");
    const propose = main.getByRole("button", { name: "Propose the design" });
    if (await propose.count()) {
      await propose.click();
      await jobsDone(api, sid);
      await app.settle(60_000);
    }

    // The editor: what the file cannot say, a person sets.
    const editor = main.getByRole("region", { name: "Set the design on this page" });
    await expect(editor).toBeVisible({ timeout: 120_000 });
    const view = await settledJson<S["DesignEditorView"]>(
      api,
      `/api/sessions/${sid}/design/editor`,
    );
    const names = view.targets.map((t) => t.target);
    const hmuy = names.find((t) => /hmuy/i.test(t))!;
    const rrna = names.find((t) => /16s/i.test(t))!;
    const empty = names.find((t) => t !== hmuy && t !== rrna)!;
    expect([hmuy, rrna, empty].every(Boolean), names.join(", ")).toBe(true);

    await editor.getByRole("tab", { name: /^Targets/ }).click();
    const role = (target: string, label: string) =>
      editor.getByRole("radiogroup", { name: `Role of target ${target}` }).getByRole("radio", {
        name: label,
      });
    await role(rrna, "Reference gene").click();
    await role(hmuy, "Gene of interest").click();
    await role(empty, "Leave out").click();
    await app.axe("design editor, targets");

    await editor.getByRole("tab", { name: /^Samples/ }).click();
    for (const [group, pattern] of Object.entries(CONDITIONS)) {
      await editor.getByLabel("Select by name").fill(pattern);
      await editor.getByRole("button", { name: "Select matching" }).click();
      await expect(editor.getByText(/^3 samples selected/)).toBeVisible();
      await editor.getByRole("combobox", { name: "Group name" }).fill(group);
      await editor.getByRole("button", { name: "Put in group" }).click();
    }
    await app.axe("design editor, samples");

    await editor.getByRole("tab", { name: /^Comparison/ }).click();
    const pick = async (label: string, value: string) => {
      await editor.getByRole("combobox", { name: label }).click();
      await page.getByRole("option", { name: new RegExp(`^${value}\\b`) }).click();
    };
    await pick("Compared group", "DIP");
    await pick("Reference group", "Hm");
    await expect(editor.getByText("Fold change = DIP relative to Hm.")).toBeVisible();
    await editor.getByRole("button", { name: "Set the comparison" }).click();
    await app.axe("design editor, comparison");

    await editor.getByRole("button", { name: "Review and record…" }).click();
    const review = page.getByRole("dialog", { name: "Review and record your changes" });
    await expect(review).toBeVisible();
    const record = review.getByRole("button", { name: /^Record \d+ changes?$/ });
    await expect(record).toBeVisible({ timeout: 120_000 });
    await review.getByRole("textbox", { name: /^Why/ }).fill(REASON);
    await app.axe("design editor, review dialog");
    await record.click();
    await expect(review).toBeHidden({ timeout: 120_000 });
    await app.settle(60_000);

    // The server has the person's design, every write theirs, with the reason.
    const after = await settledJson<S["DesignEditorView"]>(
      api,
      `/api/sessions/${sid}/design/editor`,
    );
    expect(Object.fromEntries(after.targets.map((t) => [t.target, t.role]))).toEqual({
      [rrna]: "ref",
      [hmuy]: "toi",
      [empty]: "ignore",
    });
    expect(after.groups).toEqual({ Hm: 3, DIP: 3 });
    expect(after.comparison).toMatchObject({ group_a: "DIP", group_b: "Hm" });

    // What the rules proposed besides (well roles, the declared references) is decided too,
    // then the design is confirmed.
    await reviewStage(app, api, sid, "design", REASON);

    // Curves: the rules check every well (no model), the person decides, confirms.
    await goTo(app, sid, "curves");
    await main.getByRole("button", { name: "Check the curves" }).click();
    await jobsDone(api, sid);
    await app.settle(120_000);
    await reviewStage(app, api, sid, "curves", REASON);

    // Results: the gene the person studies, compared as they set it.
    const study = await studyOf(api, sid);
    walked.study = study;
    const results = await resultsOf(api, study);
    expect(results.genes.map((g) => g.gene)).toEqual([hmuy]);
    await goTo(app, sid, "results");
    const genes = main.getByRole("table", { name: /^All genes/ });
    await expect(genes).toBeVisible({ timeout: 120_000 });
    await expect(genes.getByRole("row", { name: new RegExp(hmuy) })).toBeVisible();
    await expect(main.getByText(/DIP/).first()).toBeVisible();
    await app.axe("results of a LightCycler 96 file");
    await app.noSideScroll("results of a LightCycler 96 file");
    await app.shot("own-data", "lc96-results");
  });

  test("Curves: the melt panel reads each assay's product from the file", async ({ app, api }) => {
    const { sid } = await lc96(api);
    const melt = await settledJson<S["MeltView"]>(api, `/api/sessions/${sid}/melt`);
    expect(melt.has_melt).toBe(true);
    await goTo(app, sid, "curves");
    const card = app.page.getByRole("region", { name: "Melt curve" });
    await expect(card).toBeVisible({ timeout: 120_000 });
    const assays = card.getByRole("list", { name: "Assays on this plate" });
    await expect(assays).toBeVisible();
    for (const a of melt.assays) {
      await expect(assays.getByText(a.target).first()).toBeVisible();
    }
    const flagged = melt.calls.filter((c) => c.flagged);
    if (flagged.length) {
      const chips = card.getByRole("list", { name: "Wells G-MELT points at" });
      await expect(chips.getByRole("listitem")).toHaveCount(flagged.length);
      // A flagged well opens as its melt curve (−dF/dT), here on the Curves page.
      await chips.getByRole("button").first().click();
      await expect(card.getByRole("img").first()).toBeVisible();
    } else {
      await expect(card.getByText(/G-MELT points at no well on this plate/)).toBeVisible();
    }
    await app.axe("curves, melt panel");
    await app.shot("own-data", "lc96-melt");
  });

  test("Controls: the G-MELT lines and their melt curves", async ({ app, api }) => {
    const { sid, study } = await lc96(api);
    const gate = await settledJson<S["GateView"]>(api, `/api/studies/${study}/gate`);
    const lines = gate.evaluations.filter((e) => e.rule_id === "G-MELT");
    expect(lines.length).toBeGreaterThan(0);
    await goTo(app, sid, "gate");
    const main = app.page.getByRole("main");
    await main
      .getByRole("radiogroup", { name: "Show checks by verdict" })
      .getByRole("radio", { name: "All" })
      .click();
    await main.getByRole("combobox", { name: "Show checks of one rule" }).click();
    await app.page.getByRole("option", { name: /^G-MELT/ }).click();
    const rows = main
      .getByRole("list", { name: "Rule checks" })
      .getByRole("button", { name: /G-MELT/ });
    await expect(rows).toHaveCount(lines.length);
    await rows.first().click();
    await expect(rows.first()).toHaveAttribute("aria-expanded", "true");
    const first = filterOrder(lines)[0]!;
    await expect(main.getByText(first.reason.plain).first()).toBeVisible();
    await app.axe("controls, a G-MELT line open");
    await app.shot("own-data", "lc96-gate-melt");
  });

  test("Report: every export downloads; the workbook holds numbers as numbers", async ({
    app,
    api,
  }) => {
    test.setTimeout(10 * 60_000);
    const { sid, study } = await lc96(api);
    const results = await resultsOf(api, study);
    const gene = results.genes[0]!.gene;
    await goTo(app, sid, "report");
    const panel = app.page.getByRole("region", { name: "Export: numbers, figures and the report" });
    await expect(panel).toBeVisible({ timeout: 120_000 });
    const dir = mkdtempSync(join(tmpdir(), "qpilot-e2e-exports-"));
    const got: Record<string, { path: string; name: string }> = {};
    for (const [action, kind] of [
      ["Write the workbook", "xlsx"],
      ["Write the CSV tables", "csv"],
      ["Write the figures", "figures"],
      ["Write the supplement", "supplement"],
    ] as const) {
      const before = await panel
        .getByRole("link")
        .evaluateAll((as) => as.map((a) => a.getAttribute("href")));
      await panel.getByRole("button", { name: action }).click();
      let link = panel.locator("a[download]").last();
      await expect
        .poll(
          async () => {
            const hrefs = await panel
              .locator("a[download]")
              .evaluateAll((as) => as.map((a) => a.getAttribute("href")));
            const added = hrefs.findIndex((h) => !before.includes(h));
            if (added >= 0) link = panel.locator("a[download]").nth(added);
            return added >= 0;
          },
          { timeout: 300_000, intervals: [1000, 2000] },
        )
        .toBe(true);
      got[kind] = await download(app, link, dir);
    }
    expect(got.xlsx!.name).toMatch(/\.xlsx$/);
    for (const kind of ["csv", "figures", "supplement"]) expect(got[kind]!.name).toMatch(/\.zip$/);
    // The workbook: numbers are number cells, the gene name a text cell (never a date).
    const book = checkFile<{
      sheets: string[];
      gene_type: string;
      numeric: Record<string, { type: string; value: unknown }>;
    }>("xlsx-numbers", got.xlsx!.path, gene);
    expect(book.sheets.slice(0, 3)).toEqual(["Results", "Per unit", "Per well"]);
    expect(book.gene_type).toBe("s");
    const numbers = Object.entries(book.numeric);
    expect(numbers.length).toBeGreaterThanOrEqual(4);
    for (const [column, cell] of numbers) {
      expect(cell.type, `${column} is a number cell`).toBe("n");
    }
    const row = results.genes[0]!;
    const fold = numbers.find(([k]) => k.startsWith("Fold change"))![1].value as number;
    expect(fold).toBeCloseTo(row.fc, 6);
    // The CSV tables, the figures and the supplement are what they say.
    const csv = checkFile<string[]>("zip-names", got.csv!.path);
    expect(csv.some((n) => n.endsWith(".csv"))).toBe(true);
    const figures = checkFile<string[]>("zip-names", got.figures!.path);
    expect(figures.some((n) => n.endsWith(`${gene}.svg`) || n.endsWith(".svg"))).toBe(true);
    expect(figures.some((n) => n.endsWith(".png"))).toBe(true);
    const supplement = checkFile<string[]>("zip-names", got.supplement!.path);
    expect(supplement.some((n) => n.endsWith(".xlsx"))).toBe(true);
    expect(supplement.some((n) => /\.rdml$/i.test(n))).toBe(true);
    await app.axe("report, exports written");
  });

  test("Gene: the figure downloads as SVG and PNG", async ({ app, api }) => {
    const { sid, study } = await lc96(api);
    const gene = (await resultsOf(api, study)).genes[0]!.gene;
    await goTo(app, sid, "gene", `/${encodeURIComponent(gene)}`);
    const main = app.page.getByRole("main");
    const svg = main.getByRole("link", { name: /^SVG editable: download the figure/ });
    await expect(svg).toBeVisible({ timeout: 120_000 });
    const dir = mkdtempSync(join(tmpdir(), "qpilot-e2e-figure-"));
    const a = await download(app, svg, dir);
    expect(a.name).toMatch(/\.svg$/);
    expect(readFileSync(a.path, "utf8")).toMatch(/^<\?xml|<svg/);
    const b = await download(
      app,
      main.getByRole("link", { name: /^PNG 300 dpi: download the figure/ }),
      dir,
    );
    expect(b.name).toMatch(/\.png$/);
    expect(
      [...readFileSync(b.path).subarray(1, 4)].map((c) => String.fromCharCode(c)).join(""),
    ).toBe("PNG");
    await app.axe("gene, figure");
  });

  test("Prism: send writes a .pzfx; a project edited in Prism comes back as questions", async ({
    app,
    api,
  }) => {
    test.setTimeout(15 * 60_000);
    const { sid, study } = await lc96(api);
    const gene = (await resultsOf(api, study)).genes[0]!.gene;
    const page = app.page;
    const main = page.getByRole("main");
    // The analysis choices are fixed first (every Decision Card of this study is decided).
    const frame = (await (await api.get(`/api/sessions/${sid}`)).json()) as S["WorkspaceView"];
    if (!frame.stages.find((s) => s.stage === "choices")?.confirmed) {
      await goTo(app, sid, "results");
      await main.getByRole("button", { name: "Confirm the analysis choices…" }).click();
      const dialog = page.getByRole("dialog", { name: "Confirm the analysis choices" });
      await expect(dialog).toBeVisible();
      await app.axe("results, confirm the choices");
      await dialog.getByRole("button", { name: "Yes, confirm" }).click();
      await expect(dialog).toBeHidden({ timeout: 120_000 });
      await app.settle(60_000);
    }
    await goTo(app, sid, "prism");
    const project = main.getByRole("region", { name: "The Prism project", exact: true });
    await expect(project).toBeVisible({ timeout: 120_000 });
    const draft = project.getByRole("button", { name: /^Draft (the Prism project|it again)$/ });
    // The drafted project waits for a person: accept it (it is a proposal like any other).
    const drafted = project.getByRole("article", { name: /^Prism project/ });
    if (await draft.count()) {
      await draft.click();
      await jobsDone(api, sid);
      await expect(drafted).toBeVisible({ timeout: 120_000 });
    }
    if (await drafted.count()) {
      await expect(drafted).toContainText(gene);
      await drafted.getByRole("button", { name: /^Accept(…)?$/ }).click();
      const why = drafted.getByRole("textbox", { name: /Why you accept it/ });
      if (await why.count()) {
        await why.fill(REASON);
        await drafted.getByRole("button", { name: "Accept", exact: true }).click();
      }
      await expect(drafted).toBeHidden({ timeout: 120_000 });
      await app.settle(60_000);
    }
    const send = main.getByRole("region", { name: "Send to Prism" });
    const sendButton = send.getByRole("button", { name: /^(Send to Prism|Send again)$/ });
    await expect(sendButton).toBeEnabled({ timeout: 120_000 });
    await sendButton.click();
    const bundleLink = send.getByRole("link", { name: /^Download the bundle/ });
    await expect(bundleLink).toBeVisible({ timeout: 300_000 });
    await app.axe("prism, sent");
    const dir = mkdtempSync(join(tmpdir(), "qpilot-e2e-prism-"));
    const bundle = await download(app, bundleLink, dir);
    expect(bundle.name).toMatch(/\.zip$/);
    const names = checkFile<string[]>("zip-names", bundle.path);
    // The project of the study (and one of every replicate, beside it).
    expect(names).toContain(`qpilot_${study}.pzfx`);

    // In Prism a value is excluded and the project saved; it comes back by upload.
    const edited = join(dir, "saved in Prism.pzfx");
    const changed = checkFile<{ row: string }>("pzfx-exclude", bundle.path, edited);
    const back = main.getByRole("region", { name: "Round trip: what changed in Prism" });
    await back.getByLabel("The project Prism saved (.pzfx)").setInputFiles(edited);
    await back.getByRole("button", { name: "Read the saved project" }).click();
    await jobsDone(api, sid);
    await app.settle(60_000);
    const asked = await settledJson<S["ProposalList"]>(
      api,
      `/api/sessions/${sid}/proposals?stage=roundtrip`,
    );
    const questions = asked.proposals.filter((p) => p.status === "proposed");
    expect(questions.length).toBeGreaterThan(0);
    await expect(
      back.getByText(new RegExp(`You excluded sample.*${changed.row}`)).first(),
    ).toBeVisible({
      timeout: 60_000,
    });
    await app.axe("prism, a question from the round trip");
    await app.shot("own-data", "lc96-prism-roundtrip");
  });

  test("one decision reads each view it changes once, and nothing waits on a 409", async ({
    app,
    api,
  }) => {
    test.setTimeout(10 * 60_000);
    const { sid, study } = await lc96(api);
    const list = await settledJson<S["CardsView"]>(api, `/api/studies/${study}/cards`);
    const card = list.cards.find((c) => c.options.length > 1)!;
    expect(card, "a Decision Card with two options").toBeTruthy();
    await goTo(app, sid, "results");
    const page = app.page;
    const article = page.getByRole("article", { name: card.title });
    await expect(article).toBeVisible({ timeout: 120_000 });
    const show = article.getByRole("button", { name: "Show" });
    if (await show.count()) await show.click();
    // A decided card (here automatically: no option changes a conclusion) opens for a change.
    const change = article.getByRole("button", { name: "Change the decision" });
    if (await change.count()) await change.click();
    const now = card.card.decision ?? card.card.recommended;
    const other = card.options.find((o) => o.id !== now)!;
    await article.getByRole("radio", { name: literal(other.label) }).check();
    await article.getByRole("textbox", { name: /Why this option/ }).fill(REASON);

    // Every GET the page sends from the click until it is quiet again (the event stream and
    // job polls aside), and every 409 it receives.
    const reads = new Map<string, number>();
    const refused: string[] = [];
    const onRequest = (req: import("@playwright/test").Request) => {
      const url = new URL(req.url());
      if (req.method() !== "GET" || !url.pathname.startsWith("/api/")) return;
      if (/^\/api\/(events|jobs)\b/.test(url.pathname)) return;
      const key = url.pathname + url.search;
      reads.set(key, (reads.get(key) ?? 0) + 1);
    };
    const onResponse = (res: import("@playwright/test").Response) => {
      if (res.status() === 409) refused.push(`${res.request().method()} ${res.url()}`);
    };
    page.on("request", onRequest);
    page.on("response", onResponse);
    await article.getByRole("button", { name: /^Decide: / }).click();
    await expect
      .poll(
        async () => {
          const after = await settledJson<S["CardsView"]>(api, `/api/studies/${study}/cards`);
          return after.cards.find((c) => c.card.id === card.card.id)?.card.decision;
        },
        { timeout: 120_000 },
      )
      .toBe(other.id);
    await jobsDone(api, sid);
    await app.settle(120_000);
    // Quiet for a few seconds more: a late duplicate read would show here.
    await page.waitForTimeout(3000);
    await app.settle(60_000);
    page.off("request", onRequest);
    page.off("response", onResponse);

    const twice = [...reads].filter(([, n]) => n > 1);
    expect(twice, `views read more than once after one decision: ${JSON.stringify(twice)}`).toEqual(
      [],
    );
    expect([...reads.keys()].some((k) => k.startsWith(`/api/studies/${study}/cards`))).toBe(true);
    expect(refused, "409 answers the page received").toEqual([]);
    await test.info().attach("reads-after-one-decision.json", {
      body: JSON.stringify(Object.fromEntries(reads), null, 2),
      contentType: "application/json",
    });
    await app.axe("results, after a decision");
  });
});

/** The rule checks in the order the page lists them (problems first, then the pack's order). */
function filterOrder(lines: S["GateView"]["evaluations"]): S["GateView"]["evaluations"] {
  const rank = { fail: 0, warn: 1, pass: 2, not_applicable: 3 } as Record<string, number>;
  return [...lines].sort((a, b) => (rank[a.verdict] ?? 9) - (rank[b.verdict] ?? 9));
}

/** The walked LightCycler 96 session and its study (the first test of this file makes them). */
async function lc96(api: import("@playwright/test").APIRequestContext) {
  const w = await sessionOf(api, FILE);
  test.skip(!w?.results_visible, "the LightCycler 96 file has not been walked (first test)");
  const sid = w!.key;
  return { sid, study: walked.study ?? (await studyOf(api, sid)) };
}

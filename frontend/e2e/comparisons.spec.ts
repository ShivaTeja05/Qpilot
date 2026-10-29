/**
 * Several comparisons on a real lab's conditions, through the page, no model: the RDML that
 * LinRegPCR wrote from a LightCycler 480 II study of the unfolded protein response in
 * Komagataella phaffii (Büchner, Ludwig, Kerpes & Becker 2025; CC BY 4.0; corpus
 * `rdml/linregpcr-rdml-1.3-lc480-kphaffii`: eight conditions in three biological replicates, four
 * UPR genes, reference genes ACT1 and TFC1). On the Design page a person puts four conditions in
 * their groups (20, 28, D20, D28), sets "Several comparisons": each against the control 20, with
 * Dunnett's correction. Then Results show a comparison picker and the side-by-side table (each
 * gene in every comparison, with its corrected p and q); picking a comparison changes the gene
 * table, and Trace and the gene's page follow the same pick.
 *
 * It writes a new session: run it on a fresh store copy (e2e/reset-store.sh).
 */
import { join } from "node:path";
import type { Page } from "@playwright/test";
import type { components } from "../src/api/schema";
import { literal } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import {
  CORPUS,
  goTo,
  jobsDone,
  openFiles,
  reviewStage,
  sessionOf,
  settledJson,
  studyOf,
} from "./support/studio";

type S = components["schemas"];

const FILE = "12934_2025_2809_MOESM5_ESM.rdml";
const RDML = join(CORPUS, "rdml", "linregpcr-rdml-1.3-lc480-kphaffii", FILE);
const GROUPS = ["20", "28", "D20", "D28"] as const;
const CONTROL = "20";
const REFERENCES = ["ACT1", "TFC1"];
const REASON = "e2e: each condition against 20, as prespecified in the protocol";

/** Move within the page (a hash change, no reload): the comparison picked stays picked. */
async function within(page: Page, route: string): Promise<void> {
  await page.evaluate((r) => {
    window.location.hash = r;
  }, route);
}

test.describe("several comparisons on a real lab's conditions", () => {
  test.describe.configure({ mode: "default" });
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");

  test("Design → Several comparisons: each against a control, with Dunnett's correction", async ({
    app,
    api,
  }) => {
    test.setTimeout(25 * 60_000);
    const before = await sessionOf(api, FILE);
    test.skip(
      Boolean(before?.results_visible),
      "this store already walked the file: re-copy the seed",
    );
    const page = app.page;
    const main = page.getByRole("main");
    const sid = await openFiles(app, [RDML]);
    const propose = main.getByRole("button", { name: "Propose the design" });
    if (await propose.count()) {
      await propose.click();
      await jobsDone(api, sid);
      await app.settle(60_000);
    }
    const editor = main.getByRole("region", { name: "Set the design on this page" });
    await expect(editor).toBeVisible({ timeout: 120_000 });
    const view = await settledJson<S["DesignEditorView"]>(
      api,
      `/api/sessions/${sid}/design/editor`,
    );

    await editor.getByRole("tab", { name: /^Targets/ }).click();
    for (const t of view.targets) {
      const label = REFERENCES.includes(t.target) ? "Reference gene" : "Gene of interest";
      await editor
        .getByRole("radiogroup", { name: `Role of target ${t.target}` })
        .getByRole("radio", { name: label })
        .click();
    }
    await editor.getByRole("tab", { name: /^Samples/ }).click();
    for (const group of GROUPS) {
      await editor.getByLabel("Select by name").fill(`${group}_*`);
      await editor.getByRole("button", { name: "Select matching" }).click();
      await expect(editor.getByText(/^3 samples selected/)).toBeVisible();
      await editor.getByRole("combobox", { name: "Group name" }).fill(group);
      await editor.getByRole("button", { name: "Put in group" }).click();
    }

    await editor.getByRole("tab", { name: /^Comparison/ }).click();
    await editor
      .getByRole("radiogroup", { name: "How many comparisons" })
      .getByRole("radio", { name: "Several comparisons" })
      .click();
    await editor
      .getByRole("radiogroup", { name: "Which comparisons" })
      .getByRole("radio", { name: "Each group against a control" })
      .click();
    const control = editor.getByRole("combobox", { name: "Control group" });
    if ((await control.textContent())?.trim().split(/\s/)[0] !== CONTROL) {
      await control.click();
      await page.getByRole("option", { name: new RegExp(`^${CONTROL}\\b`) }).click();
    }
    await editor.getByRole("radio", { name: /^Dunnett/ }).check();
    await expect(editor.getByRole("status").filter({ hasText: /^3 comparisons:/ })).toBeVisible();
    await app.axe("design editor, several comparisons");
    await editor.getByRole("button", { name: "Set the comparisons" }).click();
    await editor.getByRole("button", { name: "Review and record…" }).click();
    const review = page.getByRole("dialog", { name: "Review and record your changes" });
    const record = review.getByRole("button", { name: /^Record \d+ changes?$/ });
    await expect(record).toBeVisible({ timeout: 120_000 });
    await review.getByRole("textbox", { name: /^Why/ }).fill(REASON);
    await record.click();
    await expect(review).toBeHidden({ timeout: 120_000 });
    await app.settle(60_000);

    const after = await settledJson<S["DesignEditorView"]>(
      api,
      `/api/sessions/${sid}/design/editor`,
    );
    expect(after.comparison_plan).toMatchObject({ correction: "dunnett", control: CONTROL });
    // The person set every item of this study; what the rules proposed besides is not part of it.
    await reviewStage(app, api, sid, "design", REASON, "reject");
    await goTo(app, sid, "curves");
    await main.getByRole("button", { name: "Check the curves" }).click();
    await jobsDone(api, sid);
    await app.settle(120_000);
    await reviewStage(app, api, sid, "curves", REASON);
    await studyOf(api, sid);
  });

  test("Results: the picker, the side-by-side table with q; Trace and Gene follow the pick", async ({
    app,
    api,
  }) => {
    test.setTimeout(10 * 60_000);
    const w = await sessionOf(api, FILE);
    test.skip(!w?.results_visible, "the file has not been walked (first test)");
    const sid = w!.key;
    const study = await studyOf(api, sid);
    const side = await settledJson<S["ComparisonsView"]>(api, `/api/studies/${study}/comparisons`);
    expect(side.correction).toBe("dunnett");
    expect(side.comparisons.map((c) => c.label)).toHaveLength(GROUPS.length - 1);
    const page = app.page;
    const main = page.getByRole("main");
    await goTo(app, sid, "results");

    // The side-by-side table: every gene in every comparison, the corrected p and q of each.
    const table = main.getByRole("table", {
      name: "Every gene across every comparison: call, fold change, corrected p-value and q-value",
    });
    await expect(table).toBeVisible({ timeout: 120_000 });
    for (const c of side.comparisons)
      await expect(
        table.getByRole("columnheader", { name: literal(c.label) }).first(),
      ).toBeVisible();
    for (const g of side.genes) {
      const row = table.getByRole("row").filter({ hasText: g.gene }).first();
      await expect(row).toBeVisible();
      await expect(row).toContainText("q ");
    }
    await app.axe("results, several comparisons");

    // The picker: the second comparison; the gene table shows its calls.
    const picker = main.getByRole("radiogroup", { name: "Comparison shown" }).first();
    const second = side.comparisons[1]!;
    await picker.getByRole("radio", { name: literal(second.label) }).click();
    await expect(picker.getByRole("radio", { name: literal(second.label) })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(main.getByText(`Showing ${second.label}:`).first()).toBeVisible();
    const shown = await settledJson<S["ResultsView"]>(
      api,
      `/api/studies/${study}/results?comparison=${encodeURIComponent(second.id)}`,
    );
    expect(shown.comparison).toBe(second.id);
    const genes = main.getByRole("table", { name: /^All genes/ });
    for (const g of shown.genes)
      await expect(genes.getByRole("row").filter({ hasText: g.gene }).first()).toBeVisible();
    await app.shot("comparisons", "results-second-comparison");

    // Trace follows the pick (the same page, no reload)…
    const gene = shown.genes[0]!.gene;
    await within(page, `/s/${sid}/trace/${encodeURIComponent(gene)}`);
    await app.settle(120_000);
    await expect(page.getByTestId("trace-comparisons")).toContainText(`Tracing ${second.label}:`, {
      timeout: 120_000,
    });
    await app.axe("trace, a picked comparison");
    // …and so does the gene's page.
    await within(page, `/s/${sid}/gene/${encodeURIComponent(gene)}`);
    await app.settle(120_000);
    await expect(main.getByText(`Showing ${second.label}:`).first()).toBeVisible({
      timeout: 120_000,
    });
    await app.axe("gene, a picked comparison");
  });
});

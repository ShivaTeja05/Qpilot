/**
 * Absolute quantities from a real lab's standards, through the page, no model: the QuantStudio 3
 * (Design & Analysis 2.7) export of an airplane-wastewater run (corpus
 * `thermofisher/securebio-qs3-design-analysis-2.7`: SARS-CoV-2 (Cov2, FAM) and the faecal
 * normaliser PMMoV (VIC) in triplicate, five standards `Std 1` … `Std 5` with no quantity in the
 * export, NTCs). On Open the four CSV files are dropped; on the Design page a person sets PMMoV as
 * the reference gene and Cov2 the gene of interest, makes the standards a ten-fold series whose
 * top quantity comes from the ng → copies helper (the export does not carry it), puts the
 * airplane samples of the two sites (DNI, DSI) in their groups and compares them. Then the curves
 * are confirmed and Results → Quantities shows every unit's copies with its 95 % prediction
 * interval, the same numbers as the quantities API.
 *
 * It writes a new session: run it on a fresh store copy (e2e/reset-store.sh).
 */
import { readdirSync } from "node:fs";
import { join } from "node:path";
import type { components } from "../src/api/schema";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import {
  CORPUS,
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

const FOLDER = join(CORPUS, "thermofisher", "securebio-qs3-design-analysis-2.7");
const FILES = readdirSync(FOLDER)
  .filter((n) => n.endsWith(".csv"))
  .sort()
  .map((n) => join(FOLDER, n));
const REASON = "e2e: plate map and standard series from the lab notebook";
/** 0.0003079 ng of a 3000 bp plasmid is 1.000 × 10⁵ copies: the lab's top standard. */
const NG = "0.0003079";
const LENGTH = "3000";

test.describe("absolute quantities from a QuantStudio export", () => {
  test.describe.configure({ mode: "default" });
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");

  test("Design: standards from the ng → copies helper, groups, comparison; then Curves", async ({
    app,
    api,
  }) => {
    test.setTimeout(20 * 60_000);
    const before = await sessionOf(api, `${FILES[0]!.split("/").pop()}`);
    test.skip(
      Boolean(before?.results_visible),
      "this store already walked the export: re-copy the seed",
    );
    const page = app.page;
    const main = page.getByRole("main");
    const sid = await openFiles(app, FILES);
    const propose = main.getByRole("button", { name: "Propose the design" });
    if (await propose.count()) {
      await propose.click();
      await jobsDone(api, sid);
      await app.settle(60_000);
    }
    const editor = main.getByRole("region", { name: "Set the design on this page" });
    await expect(editor).toBeVisible({ timeout: 120_000 });

    await editor.getByRole("tab", { name: /^Targets/ }).click();
    const role = (target: string, label: string) =>
      editor
        .getByRole("radiogroup", { name: `Role of target ${target}` })
        .getByRole("radio", { name: label });
    await role("PMMoV", "Reference gene").click();
    await role("Cov2", "Gene of interest").click();

    await editor.getByRole("tab", { name: /^Samples/ }).click();
    const select = async (pattern: string, n?: number) => {
      await editor.getByLabel("Select by name").fill(pattern);
      await editor.getByRole("button", { name: "Select matching" }).click();
      if (n) await expect(editor.getByText(new RegExp(`^${n} samples selected`))).toBeVisible();
    };
    // The standards: a ten-fold series from the helper's copies.
    await select("Std *", 5);
    await editor.getByRole("combobox", { name: "Sample type" }).click();
    await page.getByRole("option", { name: /^Standard/ }).click();
    await editor.getByRole("button", { name: "From ng to copies…" }).click();
    const helper = editor.getByRole("group", { name: "ng to copies" });
    await helper.getByLabel("ng (or ng per µL)").fill(NG);
    await helper.getByLabel("Length").fill(LENGTH);
    const copies = (await (
      await api.get(`/api/tools/copies?ng=${NG}&length=${LENGTH}&kind=dsDNA`)
    ).json()) as S["CopiesAnswer"];
    await expect(helper.getByRole("status")).toContainText("copies", { timeout: 30_000 });
    await app.axe("design editor, ng to copies");
    await helper.getByRole("button", { name: "Use as the highest quantity" }).click();
    await expect(editor.getByLabel("Highest quantity")).toHaveValue(
      String(Number(copies.copies.toPrecision(4))),
    );
    await editor.getByRole("button", { name: "Set type" }).click();
    // The airplane samples of the two sites, compared.
    for (const site of ["DNI", "DSI"]) {
      await select(`*-${site}-*`);
      await editor.getByRole("combobox", { name: "Group name" }).fill(site);
      await editor.getByRole("button", { name: "Put in group" }).click();
    }
    await editor.getByRole("tab", { name: /^Comparison/ }).click();
    const pick = async (label: string, value: string) => {
      await editor.getByRole("combobox", { name: label }).click();
      await page.getByRole("option", { name: new RegExp(`^${value}\\b`) }).click();
    };
    await pick("Compared group", "DNI");
    await pick("Reference group", "DSI");
    await editor.getByRole("button", { name: "Set the comparison" }).click();
    await editor.getByRole("button", { name: "Review and record…" }).click();
    const review = page.getByRole("dialog", { name: "Review and record your changes" });
    const record = review.getByRole("button", { name: /^Record \d+ changes?$/ });
    await expect(record).toBeVisible({ timeout: 120_000 });
    await review.getByRole("textbox", { name: /^Why/ }).fill(REASON);
    await record.click();
    await expect(review).toBeHidden({ timeout: 120_000 });
    await app.settle(60_000);

    // The server has the person's series: Std 1 the helper's copies, each next ten-fold less.
    const view = await settledJson<S["DesignEditorView"]>(
      api,
      `/api/sessions/${sid}/design/editor`,
    );
    expect(view.groups).toMatchObject({ DNI: expect.any(Number), DSI: expect.any(Number) });
    const standards = view.samples
      .filter((s) => s.role === "std")
      .map((s) => s.quantity)
      .filter((q): q is number => typeof q === "number")
      .sort((a, b) => b - a);
    expect(standards).toHaveLength(5);
    expect(standards[0]).toBeCloseTo(Number(copies.copies.toPrecision(4)), 6);
    for (let i = 1; i < 5; i++) expect(standards[i]! * 10).toBeCloseTo(standards[i - 1]!, 6);

    await reviewStage(app, api, sid, "design", REASON);
    await goTo(app, sid, "curves");
    await main.getByRole("button", { name: "Check the curves" }).click();
    await jobsDone(api, sid);
    await app.settle(120_000);
    await reviewStage(app, api, sid, "curves", REASON);
    const study = await studyOf(api, sid);
    expect((await resultsOf(api, study)).genes.map((g) => g.gene)).toEqual(["Cov2"]);
  });

  test("Results → Quantities: every unit's copies with its prediction interval", async ({
    app,
    api,
  }) => {
    const w = await sessionOf(api, `${FILES[0]!.split("/").pop()}`);
    test.skip(!w?.results_visible, "the export has not been walked (first test)");
    const sid = w!.key;
    const study = await studyOf(api, sid);
    const all = await settledJson<S["QuantitiesView"]>(api, `/api/studies/${study}/quantities`);
    expect(all.available, all.why).toBe(true);
    const assay = all.assays[0]!;
    const detail = await settledJson<S["AssayQuantities"]>(
      api,
      `/api/studies/${study}/quantities/${encodeURIComponent(assay.target)}`,
    );
    await goTo(app, sid, "results");
    const card = app.page.getByRole("region", { name: "Quantities" });
    await expect(card).toBeVisible({ timeout: 120_000 });
    const table = card.getByRole("table").filter({ hasText: "95 % prediction interval" });
    await expect(table).toBeVisible({ timeout: 60_000 });
    const quantified = detail.units.filter((u) => u.quantity != null);
    expect(quantified.length).toBeGreaterThan(0);
    for (const u of quantified.slice(0, 5)) {
      const row = table.getByRole("row").filter({ hasText: u.unit }).first();
      await expect(row).toBeVisible();
      await expect(row).toContainText(`${u.n_detected} of ${u.n_wells}`);
      // its copies, and the 95 % prediction interval as low–high
      if (u.low != null && u.high != null) await expect(row).toContainText("–");
    }
    // A standard curve is drawn when it was fitted; its numbers are beside it.
    if (detail.curves.some((c) => c.fitted)) {
      await expect(card.getByText(/efficiency|slope/i).first()).toBeVisible();
    }
    await app.axe("results, quantities");
    await app.noSideScroll("results, quantities");
    await app.shot("quantities", "qs3-quantities");
  });
});

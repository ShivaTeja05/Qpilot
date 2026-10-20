/**
 * Audit and Gene on the seeded demo session (the seed already holds a robustness audit, so
 * nothing is re-run): the verdict strip is the server's (/audit/overview), every tab opens, a
 * gene opens the Gene section, whose header shows the server's numbers (/genes/{gene}).
 */
import type { APIRequestContext } from "@playwright/test";
import type { components } from "../src/api/schema";
import { ci, fold, pValue } from "../src/lib/format";
import { demoSession, literal, route, type Workspace } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

type ResultsView = components["schemas"]["ResultsView"];

interface AuditOverview {
  verdicts: { key: string; label: string; count: number }[];
  genes: { gene: string; verdict: string }[];
}

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  let res = await api.get(path, { timeout: 110_000 });
  // 409 "loading": the audit's views are being prepared (a job, ~15 s on a cold server).
  for (let i = 0; i < 40 && res.status() === 409; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    res = await api.get(path, { timeout: 110_000 });
  }
  expect(res.status(), `GET ${path}`).toBe(200);
  return (await res.json()) as T;
}

const overview = (api: APIRequestContext, w: Workspace) =>
  getJson<AuditOverview>(api, `/api/studies/${w.study_id}/audit/overview`);

const TABS = ["Study", "What-if lab", "How it works", "Verify"] as const;

test.describe("Audit", () => {
  test.beforeEach(() => test.fixme(!LANDED.audit, notLanded("audit")));

  test("the seeded audit shows the server's verdict counts", async ({ app, api }) => {
    const demo = await demoSession(api);
    const status = await getJson<{ status: string }>(api, `/api/studies/${demo.study_id}/audit`);
    expect(status.status, "the seed has an audit").toBe("ready");
    const o = await overview(api, demo);
    await app.open(route(demo, "audit"));
    const tabs = app.page.getByRole("tablist", { name: "Audit views" });
    await expect(tabs.getByRole("tab", { name: "Study" })).toHaveAttribute("aria-selected", "true");
    const strip = app.page.getByRole("region", { name: "Verdicts" });
    for (const v of o.verdicts) {
      await expect(strip).toContainText(v.label);
      await expect(strip).toContainText(String(v.count));
    }
    await app.axe("Audit, Study tab");
  });

  test("every tab opens and passes axe", async ({ app, api }) => {
    test.setTimeout(240_000);
    const demo = await demoSession(api);
    await app.open(route(demo, "audit"));
    const tabs = app.page.getByRole("tablist", { name: "Audit views" });
    for (const name of [...TABS.slice(1), TABS[0]]) {
      await tabs.getByRole("tab", { name }).click();
      await app.settle(90_000);
      await expect(tabs.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
      await expect(app.page.getByRole("tabpanel", { name })).toBeVisible();
      await app.axe(`Audit, ${name}`);
      await app.shot("audit", `tab-${name}`);
    }
  });

  test("a gene in the audit's list opens the Gene section", async ({ app, api }) => {
    test.fixme(!LANDED.gene, notLanded("gene"));
    const demo = await demoSession(api);
    const o = await overview(api, demo);
    const gene = o.genes[0]!.gene;
    await app.open(route(demo, "audit"));
    const list = app.page.getByRole("list", { name: "Genes" });
    // The link reads "<verdict> <gene> <fold>": find the gene as a whole word.
    await list
      .getByRole("link", { name: new RegExp(`(^|\\s)${literal(gene).source}(\\s|$)`) })
      .click();
    await app.settle();
    expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(`#${route(demo, "gene", gene)}`);
    await expect(app.page.getByRole("main").getByRole("heading", { level: 1 })).toHaveText(gene);
  });
});

test.describe("Gene", () => {
  test.beforeEach(() => test.fixme(!LANDED.gene, notLanded("gene")));

  test("the header shows the server's call, fold [CI] and p for the gene", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { genes } = await getJson<ResultsView>(api, `/api/studies/${demo.study_id}/results`);
    const g = genes[0]!;
    await app.open(route(demo, "gene", g.gene));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(g.gene);
    await expect(main).toContainText(fold(g.fc));
    await expect(main).toContainText(ci(g.ci[0], g.ci[1]));
    await expect(main).toContainText(pValue(g.p));
    if (g.level) await expect(main).toContainText(g.level);
    await app.axe(`Gene ${g.gene}`);
    await app.shot("gene", `${g.gene}-1440-light`);
  });

  test("the panels are there: what holds, cards, assay and wells, reference genes", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const { genes } = await getJson<ResultsView>(api, `/api/studies/${demo.study_id}/results`);
    await app.open(route(demo, "gene", genes[0]!.gene));
    for (const name of [
      "What holds",
      "Decision Cards that affect this gene",
      "Assay and wells",
      "Reference genes",
    ]) {
      await expect(app.page.getByRole("region", { name })).toBeVisible();
    }
  });

  test("Next / Previous gene follow the server's order, by link and by ] / [", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const { genes } = await getJson<ResultsView>(api, `/api/studies/${demo.study_id}/results`);
    const start = genes[0]!.gene;
    const view = await getJson<{ next_gene: string | null; prev_gene: string | null }>(
      api,
      `/api/studies/${demo.study_id}/genes/${encodeURIComponent(start)}`,
    );
    test.skip(!view.next_gene, "the first gene has no next gene");
    await app.open(route(demo, "gene", start));
    const nav = app.page.getByRole("navigation", { name: "Genes" });
    await nav.getByRole("button", { name: `Next gene: ${view.next_gene}` }).click();
    await app.settle();
    const h1 = app.page.getByRole("main").getByRole("heading", { level: 1 });
    await expect(h1).toHaveText(view.next_gene!);
    await app.page.locator("body").press("[");
    await app.settle();
    await expect(h1).toHaveText(start);
    await app.page.locator("body").press("]");
    await app.settle();
    await expect(h1).toHaveText(view.next_gene!);
  });
});

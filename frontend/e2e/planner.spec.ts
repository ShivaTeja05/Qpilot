/**
 * Plan next on the seeded demo session: what the study measured (groups, rule) and every gene's
 * noise are the server's (/planner), the explorer starts from the server's defaults, the power
 * chart has a summary, and the plates for the next experiment are laid out.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, literal, route } from "./support/data";
import { expect, test } from "./support/fixtures";

interface PlannerView {
  groups: { label: string; n: number }[];
  rule_text: string;
  genes: { gene: string }[];
  defaults: { genes: string[] };
}

async function planner(api: APIRequestContext, studyId: string): Promise<PlannerView> {
  const res = await api.get(`/api/studies/${studyId}/planner`, { timeout: 110_000 });
  expect(res.status()).toBe(200);
  return (await res.json()) as PlannerView;
}

test.describe("Plan next", () => {
  test("what the study measured and every gene's noise come from /planner", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const view = await planner(api, demo.study_id!);
    await app.open(route(demo, "planner"));
    await expect(app.page.getByRole("main").getByRole("heading", { level: 1 })).toHaveText(
      "Plan the next experiment",
    );
    const measured = app.page.getByRole("region", { name: "What this study measured" });
    for (const g of view.groups) {
      await expect(measured).toContainText(g.label);
      await expect(measured).toContainText(String(g.n));
    }
    await expect(measured).toContainText(view.rule_text);
    const genes = app.page.getByRole("region", { name: "Every gene under this plan" });
    const table = genes.getByRole("table", { name: /^Every compared gene under the plan/ });
    await expect(table).toBeVisible();
    const find = genes
      .getByRole("textbox", { name: "Find a gene" })
      .or(genes.getByRole("searchbox", { name: "Find a gene" }));
    const list = view.genes;
    for (const g of [list[0]!, list[Math.floor(list.length / 2)]!, list[list.length - 1]!]) {
      await find.first().fill(g.gene);
      await expect(table.getByRole("row", { name: literal(g.gene) }).first()).toBeVisible();
    }
    await find.first().fill("");
    await app.axe("Plan next");
  });

  test("the explorer starts from the server's genes and its power chart has a summary", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const view = await planner(api, demo.study_id!);
    await app.open(route(demo, "planner"));
    const explorer = app.page.getByRole("region", {
      name: "How many samples, and what they can detect",
    });
    for (const g of view.defaults.genes) {
      await expect(explorer.getByRole("button", { name: `Remove ${g}` })).toBeVisible();
    }
    const chart = explorer.getByRole("img").first();
    await expect(chart).toBeVisible();
    expect(
      (await chart.getAttribute("aria-label"))?.length ?? 0,
      "the chart's summary",
    ).toBeGreaterThan(20);
    await app.axe("Plan next, explorer");
  });

  test("the plates for the next experiment are laid out", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "planner"));
    const layout = app.page.getByRole("region", { name: "Plates for the next experiment" });
    await expect(layout).toBeVisible();
    await expect(
      layout.getByRole("list", { name: "Every plate" }).getByRole("listitem").first(),
    ).toBeVisible({
      timeout: 60_000,
    });
    await app.axe("Plan next, plates");
    await app.shot("planner", "plates-1440-light");
  });
});

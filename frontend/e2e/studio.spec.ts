/**
 * Design and Curves (blind stages) on the seeded demo session: the inboxes render the session's
 * real proposals (subjects and counts read from /proposals), the plate map and heatmap render,
 * a well opens its curve, and j/k move between cards.
 */
import { demoSession, literal, proposals, route } from "./support/data";
import { expect, test, type App } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

/** Show decided proposals too (the seeded stages are confirmed: nothing waits). */
async function showAll(app: App): Promise<void> {
  const all = app.page
    .getByRole("tab", { name: /^(all|decided)/i })
    .or(app.page.getByRole("radio", { name: /^(all|decided)/i }));
  if (await all.count()) {
    await all.first().click();
    await app.settle();
  }
}

for (const stage of ["design", "curves"] as const) {
  test.describe(stage === "design" ? "Design" : "Curves", () => {
    test.beforeEach(() => test.fixme(!LANDED[stage], notLanded(stage)));

    test("the inbox renders the session's real proposals", async ({ app, api }) => {
      const demo = await demoSession(api);
      const list = await proposals(api, demo.key, stage);
      expect(list.proposals.length, "the seeded stage has proposals").toBeGreaterThan(0);
      await app.open(route(demo, stage));
      await showAll(app);
      // The first proposal the server lists (contradicted first) is on the page, as text.
      const first = list.proposals.find((p) => p.kind !== "stage.confirm")!;
      await expect(app.page.getByText(literal(first.subject)).first()).toBeVisible();
      // Each status count the server reports is shown with its number.
      for (const [status, n] of Object.entries(list.counts)) {
        await expect(
          app.page.getByText(new RegExp(`${n}\\s*${status}|${status}\\D{0,3}${n}`, "i")).first(),
        ).toBeVisible();
      }
      await app.axe(`${stage} inbox`);
    });

    test("a proposal card folds out its evidence and engine check", async ({ app, api }) => {
      const demo = await demoSession(api);
      const list = await proposals(api, demo.key, stage);
      const first = list.proposals.find((p) => p.kind !== "stage.confirm")!;
      await app.open(route(demo, stage));
      await showAll(app);
      const card = app.page
        .getByRole("article")
        .filter({ hasText: literal(first.subject) })
        .first();
      await expect(card).toBeVisible();
      await expect(card.getByText(new RegExp(first.check.status, "i")).first()).toBeVisible();
      for (const rule of first.check.rule_ids.slice(0, 3))
        await expect(card.getByText(rule).first()).toBeVisible();
      const why = card.getByRole("button", { name: /why/i }).first();
      if (await why.count()) {
        await why.click();
        await app.axe(`${stage} card, evidence open`);
      }
    });

    test("j / k move between proposal cards", async ({ app, api }) => {
      const demo = await demoSession(api);
      await app.open(route(demo, stage));
      await showAll(app);
      await app.page.locator("body").press("j");
      const firstFocus = await app.page.evaluate(() => document.activeElement?.textContent ?? "");
      await app.page.locator("body").press("j");
      const secondFocus = await app.page.evaluate(() => document.activeElement?.textContent ?? "");
      expect(firstFocus).not.toBe("");
      expect(secondFocus).not.toBe(firstFocus);
      await app.page.locator("body").press("k");
      expect(await app.page.evaluate(() => document.activeElement?.textContent ?? "")).toBe(
        firstFocus,
      );
    });
  });
}

test.describe("plate views", () => {
  test("Design: the plate map renders as an image with a summary and a table view", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.design, notLanded("design"));
    const demo = await demoSession(api);
    await app.open(route(demo, "design"));
    const map = app.page.getByRole("img", { name: /plate/i }).first();
    await expect(map).toBeVisible();
    await app.page
      .getByRole("button", { name: /view as table/i })
      .first()
      .click();
    await expect(app.page.getByRole("table").first()).toBeVisible();
    await app.axe("design plate map as table");
  });

  test("Curves: the heatmap renders, a well opens its curve, Escape closes it", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.curves, notLanded("curves"));
    const demo = await demoSession(api);
    await app.open(route(demo, "curves"));
    const heatmap = app.page.getByRole("img", { name: /plate|heatmap|wells/i }).first();
    await expect(heatmap).toBeVisible();
    // Wells are buttons (keyboard reachable); open the first one.
    const well = app.page.getByRole("button", { name: /^[A-P]\d{1,2}\b/ }).first();
    await well.click();
    const viewer = app.page.getByRole("img", { name: /fluorescence|curve/i }).first();
    await expect(viewer).toBeVisible();
    await app.axe("curves, curve viewer open");
    await app.page.keyboard.press("Escape");
    await app.shot("curves", "curve-viewer-closed");
  });

  test("Curves: no group labels or fold changes are shown (blind stage)", async ({ app, api }) => {
    test.fixme(!LANDED.curves, notLanded("curves"));
    const demo = await demoSession(api);
    await app.open(route(demo, "curves"));
    const text = await app.page.locator("main").innerText();
    expect(text).not.toMatch(/\d+(\.\d+)?×|fold change|p\s*[<=]\s*0\.\d/i);
  });
});

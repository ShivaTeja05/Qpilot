/**
 * Design and Curves (blind stages) on the seeded demo session, whose two stages are confirmed:
 * the inbox says nothing waits and lists every decided proposal the server has (/proposals), a
 * decided proposal opens as a read-only card, the plate map renders, and a well opens its curve.
 */
import { demoSession, literal, proposals, route } from "./support/data";
import { expect, test, type App } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

/** A well with a reaction in it (empty cells are labelled "…, empty"). */
const FILLED_WELL = /^(?!.*empty$).+/;

async function openDecided(app: App): Promise<void> {
  const toggle = app.page.getByRole("button", { name: /^Decided in this stage/ });
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

for (const stage of ["design", "curves"] as const) {
  const title = stage === "design" ? "Design" : "Curves";
  test.describe(title, () => {
    test.beforeEach(() => test.fixme(!LANDED[stage], notLanded(stage)));

    test("the inbox lists every proposal the server has decided", async ({ app, api }) => {
      const demo = await demoSession(api);
      const list = await proposals(api, demo.key, stage);
      const waiting = list.proposals.filter((p) => p.status === "proposed");
      const decided = list.proposals.filter((p) => p.status !== "proposed");
      expect(decided.length, "the seeded stage has decided proposals").toBeGreaterThan(0);
      await app.open(route(demo, stage));
      await expect(app.page.getByRole("main").getByRole("heading", { level: 1 })).toHaveText(title);
      if (!waiting.length) {
        await expect(app.page.getByText("Nothing is waiting in this stage")).toBeVisible();
        await expect(
          app.page.getByText(`Every proposal is decided (${decided.length})`),
        ).toBeVisible();
      }
      const toggle = app.page.getByRole("button", { name: /^Decided in this stage/ });
      await expect(toggle).toContainText(`(${decided.length})`);
      for (const n of Object.values(list.counts)) await expect(toggle).toContainText(String(n));
      await app.axe(`${stage} inbox`);
    });

    test("a decided proposal opens as a read-only card with its parts", async ({ app, api }) => {
      const demo = await demoSession(api);
      const list = await proposals(api, demo.key, stage);
      const first = list.proposals.find(
        (p) => p.status !== "proposed" && p.kind !== "stage.confirm",
      );
      test.skip(!first, "no decided proposal");
      await app.open(route(demo, stage));
      await openDecided(app);
      const row = app.page.getByRole("button", { name: literal(first!.subject) }).first();
      await row.click();
      await expect(row).toHaveAttribute("aria-expanded", "true");
      const card = app.page
        .getByRole("article")
        .filter({ hasText: literal(first!.subject) })
        .first();
      await expect(card).toBeVisible();
      for (const part of ["Why", "Engine check", "Consequence", "Level"]) {
        await expect(card.getByText(part, { exact: true }).first()).toBeVisible();
      }
      // Read only: a decided proposal cannot be accepted or rejected again.
      await expect(card.getByRole("button", { name: /^(Accept|Reject)$/ })).toHaveCount(0);
      await app.axe(`${stage}, decided card open`);
    });
  });
}

test.describe("plates", () => {
  test("Design: the plate map renders, and a well opens its curve", async ({ app, api }) => {
    test.fixme(!LANDED.design, notLanded("design"));
    const demo = await demoSession(api);
    await app.open(route(demo, "design"));
    const panel = app.page.getByRole("region", { name: "Plate map" });
    await expect(panel.getByRole("img", { name: /^Plate .+ wells/ })).toBeVisible();
    const well = panel.getByRole("gridcell", { name: FILLED_WELL }).first();
    await well.click();
    const dialog = app.page.getByRole("dialog", { name: /^Curve of well / });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("img", { name: /^Raw fluorescence of well/ })).toBeVisible({
      timeout: 60_000,
    });
    await app.axe("design, well curve open");
    await app.page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("Curves: the plate renders, a well shows its curve, no group labels", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.curves, notLanded("curves"));
    const demo = await demoSession(api);
    await app.open(route(demo, "curves"));
    const plate = app.page.getByRole("region", { name: "The plate" });
    await expect(plate.getByRole("grid")).toBeVisible();
    const curve = app.page.getByRole("region", { name: /curve/i }).filter({
      hasText: "Pick a well on the plate",
    });
    await expect(curve).toBeVisible();
    await plate.getByRole("gridcell", { name: FILLED_WELL }).first().click();
    await expect(app.page.getByText("Pick a well on the plate")).toHaveCount(0, {
      timeout: 60_000,
    });
    await app.settle(60_000);
    await app.axe("curves, a well chosen");
    await app.shot("curves", "well-chosen-1440-light");
    // Blind stage: no fold changes or p-values on the screen.
    const text = await app.page.getByRole("main").innerText();
    expect(text).not.toMatch(/\d+(\.\d+)?×|fold change|p\s*[<=]\s*0\.\d/i);
  });

  test("Curves: the previous / next plate buttons move between plates", async ({ app, api }) => {
    test.fixme(!LANDED.curves, notLanded("curves"));
    const demo = await demoSession(api);
    await app.open(route(demo, "curves"));
    const plate = app.page.getByRole("region", { name: "The plate" });
    const picker = plate.getByRole("combobox", { name: "Plate" });
    const before = await picker.innerText();
    await plate.getByRole("button", { name: "Next plate (])" }).click();
    await app.settle();
    await expect(picker).not.toHaveText(before);
    await plate.getByRole("button", { name: "Previous plate ([)" }).click();
    await app.settle();
    await expect(picker).toHaveText(before);
  });
});

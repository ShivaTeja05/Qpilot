/**
 * Results and the Decision Cards at phone width (375 px, touch): the page reads, every card of
 * the server is there and opens, nothing scrolls sideways, axe finds nothing serious. On the
 * seeded demo and on every other analysed session in the store (a lab's own files).
 */
import type { components } from "../src/api/schema";
import { route, workspaces, type Workspace } from "./support/data";
import { expect, test, type App } from "./support/fixtures";
import { settledJson } from "./support/studio";

type S = components["schemas"];

test.use({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });

async function checkResults(
  app: App,
  w: Workspace,
  results: S["ResultsView"],
  cards: S["CardsView"],
): Promise<void> {
  const page = app.page;
  const main = page.getByRole("main");
  await app.open(route(w, "results"));
  await expect(main.getByRole("heading", { level: 1 })).toHaveText("Results", { timeout: 120_000 });
  // At phone width every gene is a row of a list, not a wide table.
  const genes = main
    .getByRole("region", { name: "All genes" })
    .getByRole("list", { name: "All genes" });
  await expect(genes).toBeVisible({ timeout: 120_000 });
  await expect(genes).toContainText(results.genes[0]!.gene);
  await app.noSideScroll(`${w.title}: results at 375 px`);
  const region = main.getByRole("region", { name: "Decision Cards" });
  await region.scrollIntoViewIfNeeded();
  for (const c of cards.cards) {
    await expect(region.getByRole("article", { name: c.title })).toBeVisible();
  }
  // A card opens to its options, still inside the screen.
  const first = region.getByRole("article", { name: cards.cards[0]!.title });
  const show = first.getByRole("button", { name: "Show" });
  if (await show.count()) await show.tap();
  await expect(first.getByRole("radio").first()).toBeVisible();
  const box = await first.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(376);
  await app.noSideScroll(`${w.title}: a Decision Card open at 375 px`);
  await app.axe(`${w.title}: results at 375 px`);
}

test.describe("phone width: Results and the Decision Cards", () => {
  test("every analysed session reads at 375 px", async ({ app, api }) => {
    test.setTimeout(10 * 60_000);
    const analysed = (await workspaces(api)).filter(
      (w) => w.kind === "session" && w.results_visible,
    );
    expect(analysed.length, "the store has an analysed session (the seeded demo)").toBeGreaterThan(
      0,
    );
    for (const w of analysed) {
      const frame = await settledJson<S["WorkspaceView"]>(api, `/api/sessions/${w.key}`);
      const cards = await settledJson<S["CardsView"]>(api, `/api/studies/${frame.study_id}/cards`);
      if (!cards.cards.length) continue;
      const results = await settledJson<S["ResultsView"]>(
        api,
        `/api/studies/${frame.study_id}/results`,
      );
      await checkResults(app, w, results, cards);
      await app.shot("phone", `results-${w.key}`);
    }
  });
});

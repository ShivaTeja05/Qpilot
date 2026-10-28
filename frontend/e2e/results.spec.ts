/**
 * Results and Gene on the seeded demo session: the genes, the robustness map and the Decision
 * Cards are the server's (/results, /cards); deciding a card and undoing it writes two chain
 * entries and the server agrees with what the page shows (a disposable store: e2e/reset-store.sh).
 */
import type { APIRequestContext } from "@playwright/test";
import type { components } from "../src/api/schema";
import { demoSession, literal, route, workspaceView, type Workspace } from "./support/data";
import { E2E } from "./support/env";
import { expect, test, type App } from "./support/fixtures";

type ResultsView = components["schemas"]["ResultsView"];
type CardsView = components["schemas"]["CardsView"];
type CardView = components["schemas"]["CardView"];
type DecisionsView = components["schemas"]["DecisionsView"];

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  const res = await api.get(path, { timeout: 110_000 });
  expect(res.status(), `GET ${path}`).toBe(200);
  return (await res.json()) as T;
}

const results = (api: APIRequestContext, w: Workspace) =>
  getJson<ResultsView>(api, `/api/studies/${w.study_id}/results`);
const cards = (api: APIRequestContext, w: Workspace) =>
  getJson<CardsView>(api, `/api/studies/${w.study_id}/cards`);
const decisions = (api: APIRequestContext, w: Workspace) =>
  getJson<DecisionsView>(api, `/api/studies/${w.study_id}/decisions`);

/** A Decision Card on the page, found by its title (an <article> labelled by its <h3>). */
function cardOnPage(app: App, c: CardView) {
  return app.page.getByRole("article", { name: c.title });
}

const focusedLabel = (app: App) =>
  app.page.evaluate(() => document.activeElement?.getAttribute("aria-labelledby") ?? null);

test.describe("Results", () => {
  test("the all-genes table lists the study's real genes", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    expect(genes.length).toBeGreaterThan(0);
    await app.open(route(demo, "results"));
    const table = app.page.getByRole("table", { name: /^All genes/ });
    await expect(table).toBeVisible();
    // Virtualised: find a few genes from the start, middle and end of the server's list.
    const find = app.page.getByRole("searchbox", { name: "Find a gene" });
    for (const g of [genes[0]!, genes[Math.floor(genes.length / 2)]!, genes[genes.length - 1]!]) {
      await find.fill(g.gene);
      await expect(table.getByRole("row", { name: literal(g.gene) }).first()).toBeVisible();
    }
    await find.fill("");
    await app.axe("Results");
  });

  test("the call filter shows the server's count for each call", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    await app.open(route(demo, "results"));
    const filter = app.page.getByRole("radiogroup", { name: "Call" });
    await expect(filter).toBeVisible();
    for (const call of ["up", "down", "none"] as const) {
      const n = genes.filter((g) => g.conclusion === call).length;
      await expect(filter).toContainText(String(n));
    }
  });

  test("the robustness map summarises the real genes and has a table view", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    await app.open(route(demo, "results"));
    const map = app.page.getByRole("img", { name: /^Robustness map of/ });
    await expect(map).toBeVisible();
    await expect(map).toHaveAccessibleName(new RegExp(`of ${genes.length} genes`));
    const panel = app.page.getByRole("region", { name: "Robustness map" });
    await panel.getByRole("button", { name: /view as table/i }).click();
    await expect(panel.getByRole("table")).toBeVisible();
    await expect(panel.getByRole("table")).toContainText(genes[0]!.gene);
    await app.axe("Results, map as table");
  });

  test("the Decision Cards are the server's, with the next step", async ({ app, api }) => {
    const demo = await demoSession(api);
    const all = await cards(api, demo);
    const view = await workspaceView(api, demo);
    await app.open(route(demo, "results"));
    const region = app.page.getByRole("region", { name: /Decision Cards/ });
    await expect(region.getByRole("article")).toHaveCount(all.cards.length);
    for (const c of all.cards) await expect(cardOnPage(app, c)).toBeVisible();
    if (view.next_step) {
      await expect(app.page.getByRole("region", { name: "Next step" })).toContainText(
        view.next_step.title,
      );
    }
  });

  test("j / k move between the Decision Cards; Enter goes to the reason", async ({ app, api }) => {
    const demo = await demoSession(api);
    const open = (await cards(api, demo)).cards.filter((c) => c.card.status === "open");
    test.skip(open.length < 2, "needs two open cards (re-copy the seed)");
    await app.open(route(demo, "results"));
    await app.page.locator("body").press("j");
    const first = await focusedLabel(app);
    expect(first, "j focuses a card").toBeTruthy();
    await app.page.keyboard.press("j");
    expect(await focusedLabel(app)).not.toBe(first);
    await app.page.keyboard.press("k");
    expect(await focusedLabel(app)).toBe(first);
    await app.page.keyboard.press("Enter");
    await expect(app.page.getByRole("textbox", { name: /Why this option/ }).first()).toBeFocused();
  });

  test("a gene row opens the Gene section; [ and ] move between genes", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    test.skip(genes.length < 2, "needs two genes");
    await app.open(route(demo, "results"));
    const table = app.page.getByRole("table", { name: /^All genes/ });
    await app.page.getByRole("searchbox", { name: "Find a gene" }).fill(genes[0]!.gene);
    await table
      .getByRole("row", { name: literal(genes[0]!.gene) })
      .first()
      .click();
    await app.settle();
    expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(
      `#${route(demo, "gene", genes[0]!.gene)}`,
    );
    const heading = app.page.getByRole("main").getByRole("heading", { level: 1 });
    await expect(heading).toContainText(genes[0]!.gene);
    await app.page.locator("body").press("]");
    await app.settle();
    await expect(heading).not.toContainText(genes[0]!.gene);
    await app.page.locator("body").press("[");
    await app.settle();
    await expect(heading).toContainText(genes[0]!.gene);
    await app.axe("Gene");
  });
});

test.describe("deciding", () => {
  test.beforeEach(() => {
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
  });

  test("decide a card with a reason, then Undo it: two chain entries, the server agrees", async ({
    app,
    api,
  }) => {
    test.setTimeout(300_000);
    const demo = await demoSession(api);
    const card = (await cards(api, demo)).cards.find((c) => c.card.status === "open");
    test.skip(!card, "every card is decided in this store (re-copy the seed)");
    const chainBefore = (await decisions(api, demo)).entries.length;
    const recommended = card!.options.find((o) => o.id === card!.card.recommended)!;

    await app.open(route(demo, "results"));
    const article = cardOnPage(app, card!);
    await expect(article).toBeVisible();
    await article.scrollIntoViewIfNeeded();
    // The recommended option is preselected; Decide waits for a reason.
    await expect(article.getByRole("radio", { name: literal(recommended.label) })).toBeChecked();
    const decide = article.getByRole("button", { name: /^Decide: / });
    await expect(decide).toBeDisabled();
    await article
      .getByRole("textbox", { name: /Why this option/ })
      .fill("e2e: checking decide and undo on the page");
    await app.axe("Decision Card, ready to decide");
    await decide.click();

    // A toast says what happened, titled with the card (its words are the server's message).
    const toasts = app.page.getByRole("region", { name: /^Notifications/ }).getByRole("listitem");
    await expect(toasts.filter({ hasText: card!.title }).first()).toBeVisible({ timeout: 120_000 });
    await app.settle(120_000);
    await app.axe("after Decide (toast, card decided)");
    const decided = (await cards(api, demo)).cards.find((c) => c.card.id === card!.card.id)!;
    expect(decided.card.status, "the server has the decision").not.toBe("open");
    expect(decided.card.decision).toBe(recommended.id);
    expect((await decisions(api, demo)).entries.length).toBe(chainBefore + 1);
    await expect(article).toContainText(decided.status_line);

    // Undo is a new chain entry, with its own reason.
    test.skip(!decided.undo_option, "the server offers no undo for this card");
    const show = article.getByRole("button", { name: "Show" });
    if (await show.count()) await show.click();
    await article.getByRole("button", { name: "Undo", exact: true }).click();
    await article
      .getByRole("textbox", { name: /Why undo it/ })
      .fill("e2e: undoing the test decision");
    await article.getByRole("button", { name: /^Undo: back to / }).click();
    await expect
      .poll(async () => (await decisions(api, demo)).entries.length, {
        timeout: 120_000,
      })
      .toBe(chainBefore + 2);
    await app.settle(120_000);
    const after = (await cards(api, demo)).cards.find((c) => c.card.id === card!.card.id)!;
    expect((await decisions(api, demo)).entries.length, "undo is a new entry").toBe(
      chainBefore + 2,
    );
    expect(after.card.decision, "back to the option before").toBe(decided.undo_option);
    await expect(article).toContainText(after.status_line);
    await app.axe("after Undo");
  });
});

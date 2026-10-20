/**
 * Results and Gene on the seeded demo session: the genes, the robustness map and the Decision
 * Cards are the server's (/results, /cards, /genes/{gene}); deciding a card and undoing it writes
 * two chain entries and leaves the card undecided (a disposable store copy: e2e/reset-store.sh).
 */
import {
  demoSession,
  literal,
  maybeJson,
  route,
  workspaceView,
  type Workspace,
} from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";
import type { APIRequestContext } from "@playwright/test";

/** The parts of the results route the tests read (docs/app.md §2, Results). */
interface Results {
  genes: { gene: string; conclusion?: string }[];
}
interface Card {
  id: string;
  question: string;
  decided?: boolean;
  status?: string;
}

async function results(api: APIRequestContext, w: Workspace): Promise<Results> {
  const r = await maybeJson<Results>(api, `/api/studies/${w.study_id}/results`);
  test.fixme(!r, "GET /api/studies/{id}/results is not served yet (owner: api)");
  return r!;
}

async function cards(api: APIRequestContext, w: Workspace): Promise<Card[]> {
  const r = await maybeJson<{ cards: Card[] } | Card[]>(api, `/api/studies/${w.study_id}/cards`);
  test.fixme(!r, "GET /api/studies/{id}/cards is not served yet (owner: api)");
  return Array.isArray(r) ? r : r!.cards;
}

const undecided = (c: Card) =>
  !c.decided && (c.status === undefined || c.status === "open" || c.status === "pending");

test.describe("Results", () => {
  test.beforeEach(() => test.fixme(!LANDED.results, notLanded("results")));

  test("the all-genes table lists the study's real genes", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    expect(genes.length).toBeGreaterThan(0);
    await app.open(route(demo, "results"));
    const table = app.page.getByRole("table", { name: /genes/i }).first();
    await expect(table).toBeVisible();
    // Virtualised: filter by name to reach each of a few genes from the start, middle and end.
    const filter = app.page.getByRole("searchbox", { name: /gene|filter|search/i }).first();
    for (const g of [genes[0]!, genes[Math.floor(genes.length / 2)]!, genes[genes.length - 1]!]) {
      await filter.fill(g.gene);
      await expect(table.getByRole("row", { name: literal(g.gene) }).first()).toBeVisible();
    }
    await filter.fill("");
    await app.axe("Results");
  });

  test("the robustness map has a summary and a table view with every gene", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    await app.open(route(demo, "results"));
    const map = app.page.getByRole("img", { name: /robust/i }).first();
    await expect(map).toBeVisible();
    expect(
      (await map.getAttribute("aria-label"))?.length ?? 0,
      "the map's aria-label summarises it",
    ).toBeGreaterThan(20);
    await app.page
      .getByRole("button", { name: /view as table/i })
      .first()
      .click();
    await expect(
      app.page.getByRole("row", { name: literal(genes[0]!.gene) }).first(),
    ).toBeVisible();
    await app.axe("Results, map as table");
  });

  test("the Decision Cards are the server's, the next step names them", async ({ app, api }) => {
    const demo = await demoSession(api);
    const all = await cards(api, demo);
    const view = await workspaceView(api, demo);
    await app.open(route(demo, "results"));
    for (const c of all.filter(undecided))
      await expect(app.page.getByText(literal(c.question)).first()).toBeVisible();
    if (view.next_step)
      await expect(app.page.getByText(view.next_step.title).first()).toBeVisible();
  });

  test("a gene row opens the Gene section; [ and ] move between genes", async ({ app, api }) => {
    test.fixme(!LANDED.gene, notLanded("gene"));
    const demo = await demoSession(api);
    const { genes } = await results(api, demo);
    test.skip(genes.length < 2, "needs two genes");
    await app.open(route(demo, "results"));
    await app.page
      .getByRole("link", { name: new RegExp(`^${literal(genes[0]!.gene).source}\\b`) })
      .first()
      .click();
    await app.settle();
    expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(
      `#${route(demo, "gene", genes[0]!.gene)}`,
    );
    await expect(
      app.page.getByRole("heading", { level: 1, name: literal(genes[0]!.gene) }),
    ).toBeVisible();
    await app.page.locator("body").press("]");
    await app.settle();
    await expect(app.page.getByRole("heading", { level: 1 })).not.toHaveText(
      literal(genes[0]!.gene),
    );
    await app.page.locator("body").press("[");
    await app.settle();
    await expect(
      app.page.getByRole("heading", { level: 1, name: literal(genes[0]!.gene) }),
    ).toBeVisible();
    await app.axe("Gene");
  });
});

test.describe("deciding", () => {
  test.beforeEach(() => {
    test.fixme(!LANDED.decide, notLanded("decide"));
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
  });

  test("decide a card with a reason, then Undo: two chain entries, the card is open again", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const before = await cards(api, demo);
    const card = before.find(undecided);
    test.skip(!card, "every card is decided in this store (re-copy the seed)");
    const headBefore = (await workspaceView(api, demo)).decisions_head;

    await app.open(route(demo, "results"));
    const region = app.page
      .getByRole("article")
      .filter({ hasText: literal(card!.question) })
      .first();
    await region.scrollIntoViewIfNeeded();
    await region.getByRole("radio").first().check();
    await region
      .getByRole("textbox", { name: /reason/i })
      .fill("e2e: deciding and undoing to test the page");
    await app.axe("Decision Card, ready to decide");
    await region.getByRole("button", { name: /^decide/i }).click();

    const toast = app.page
      .getByRole("status")
      .or(app.page.locator("[data-sonner-toast]"))
      .filter({ hasText: /decided/i });
    await expect(toast.first()).toBeVisible();
    await app.axe("after Decide (toast)");
    await toast.first().getByRole("button", { name: /undo/i }).click();
    await app.settle();

    await expect(region.getByRole("button", { name: /^decide/i })).toBeVisible();
    const after = await cards(api, demo);
    expect(
      after.find((c) => c.id === card!.id) && undecided(after.find((c) => c.id === card!.id)!),
    ).toBe(true);
    expect(
      (await workspaceView(api, demo)).decisions_head,
      "the chain moved on (undo is a new entry)",
    ).not.toBe(headBefore);
  });

  test("keyboard only: j moves to a card and Enter focuses its reason", async ({ app, api }) => {
    const demo = await demoSession(api);
    const card = (await cards(api, demo)).find(undecided);
    test.skip(!card, "every card is decided in this store (re-copy the seed)");
    await app.open(route(demo, "results"));
    await app.page.locator("body").press("j");
    await app.page.keyboard.press("Enter");
    await expect(app.page.getByRole("textbox", { name: /reason/i }).first()).toBeFocused();
  });
});

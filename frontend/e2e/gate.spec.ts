/**
 * Controls (Run Gate) on the seeded demo session: the page's headline, verdict counts, plates and
 * cards are the server's (/gate), a check opens to its reason, a person can decide a card here
 * (options and a required reason), and the page is axe-clean. The writing test leaves a card's
 * wells out with a reason, waits for the study to be analysed again, and puts them back.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, literal, route, workspaceView } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

interface Option {
  id: string;
  label: string;
}

interface Gate {
  study_id: string;
  headline: { plain: string };
  counts: Record<string, number>;
  plates: { plate: string }[];
  can_decide: boolean;
  cards: { card: { id: string; status: string; recommended: string }; options: Option[] }[];
  consequences: {
    card_id: string | null;
    decision_id: string;
    decision: { option: string | null; action: string; reason: string } | null;
  }[];
  evaluations: { verdict: string; reason: { plain: string } }[];
}

async function gate(api: APIRequestContext, studyId: string): Promise<Gate> {
  // The first gate of a study runs as a job (409 loading): ask until it answers.
  for (let i = 0; i < 300; i++) {
    const res = await api.get(`/api/studies/${studyId}/gate`, { timeout: 110_000 });
    if (res.status() === 200) return (await res.json()) as Gate;
    expect(res.status(), "GET /gate").toBe(409);
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("/gate kept loading");
}

/**
 * Back to the top before axe: the top bar is sticky, and axe counts a button half under it as too
 * small (target-size). axe still checks the whole page, opened rows and forms included.
 */
async function toTop(page: import("@playwright/test").Page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (let el = document.querySelector("main") as HTMLElement | null; el; el = el.parentElement)
      if (el.scrollHeight > el.clientHeight) el.scrollTop = 0;
  });
}

/** The first clause of a server sentence (the page cites numbers inline, so compare words). */
const firstClause = (s: string) => s.split(/[.:;]/)[0]!.trim();

test.describe("Controls", () => {
  test.beforeEach(() => test.fixme(!LANDED.gate, notLanded("gate")));

  test("the page says what /gate says, and a check opens to its reason", async ({ app, api }) => {
    const demo = await demoSession(api);
    const g = await gate(api, demo.study_id!);
    await app.open(route(demo, "gate"));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(
      "What the controls on each plate say",
      { timeout: 60_000 },
    );
    await expect(main).toContainText(firstClause(g.headline.plain));
    const plates = main.getByRole("list", { name: "Plates" });
    await expect(plates.getByRole("button")).toHaveCount(g.plates.length);
    await expect(
      main.getByRole("region", { name: "Decision Cards from the controls" }),
    ).toBeVisible();
    await expect(
      main.getByRole("region", { name: "Decision Cards from the controls" }).getByRole("article"),
    ).toHaveCount(g.cards.length);
    const problems = (g.counts.fail ?? 0) + (g.counts.warn ?? 0);
    const rows = main.getByRole("list", { name: "Rule checks" }).getByRole("button");
    if (problems) {
      await expect(rows).toHaveCount(Math.min(problems, 60));
      await rows.first().click();
      await expect(rows.first()).toHaveAttribute("aria-expanded", "true");
    }
    await toTop(app.page);
    await app.axe("Controls");
    await app.shot("gate", "1440-light");
  });

  test("a person decides a card here: its options and a reason first", async ({ app, api }) => {
    const demo = await demoSession(api);
    const g = await gate(api, demo.study_id!);
    expect(g.can_decide, "a Studio session's cards are decided on this page").toBe(true);
    test.skip(g.cards.length === 0, "no control finding can change a conclusion in this store");
    await app.open(route(demo, "gate"));
    const region = app.page
      .getByRole("main")
      .getByRole("region", { name: "Decision Cards from the controls" });
    const article = region.getByRole("article").first();
    await article.scrollIntoViewIfNeeded();
    const card = g.cards[0]!;
    if (card.card.status !== "open")
      await article.getByRole("button", { name: "Change the decision" }).click();
    await expect(article.getByRole("radio")).toHaveCount(card.options.length);
    const decide = article.getByRole("button", { name: /^Decide: / });
    await expect(decide).toBeDisabled();
    await article.getByRole("textbox", { name: /Why this option/ }).fill("e2e: not sent");
    await expect(decide).toBeEnabled();
    await toTop(app.page);
    await app.axe("Controls, a card ready to decide");
  });
});

test.describe("Controls: deciding", () => {
  test.beforeEach(() => {
    test.fixme(!LANDED.gate, notLanded("gate"));
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
  });

  test("leave a card's wells out with a reason, then put them back", async ({ app, api }) => {
    test.setTimeout(600_000);
    const demo = await demoSession(api);
    const first = demo.study_id!;
    const g = await gate(api, first);
    test.skip(g.cards.length === 0, "no control finding can change a conclusion in this store");
    const card = g.cards[0]!;
    const leaveOut = card.options.find((o) => o.id !== card.card.recommended)!;
    const decisionId = g.consequences.find((c) => c.card_id === card.card.id)!.decision_id;

    await app.open(route(demo, "gate"));
    const region = app.page
      .getByRole("main")
      .getByRole("region", { name: "Decision Cards from the controls" });
    const article = region.getByRole("article").first();
    await article.scrollIntoViewIfNeeded();
    if (card.card.status !== "open")
      await article.getByRole("button", { name: "Change the decision" }).click();
    await article.getByRole("radio", { name: literal(leaveOut.label) }).check();
    await article
      .getByRole("textbox", { name: /Why this option/ })
      .fill("e2e: leaving the flagged wells out");
    await article.getByRole("button", { name: `Decide: ${leaveOut.label}` }).click();
    const toasts = app.page.getByRole("region", { name: /^Notifications/ }).getByRole("listitem");
    await expect(toasts.filter({ hasText: leaveOut.label }).first()).toBeVisible({
      timeout: 120_000,
    });

    // The study is analysed again without the wells; the gate then reads the new analysis.
    let second = "";
    await expect
      .poll(
        async () => {
          second = (await workspaceView(api, demo)).study_id ?? "";
          return second !== "" && second !== first;
        },
        { timeout: 400_000, intervals: [2000] },
      )
      .toBe(true);
    const after = await gate(api, second);
    const decided = after.consequences.find((c) => c.decision_id === decisionId)!;
    expect(decided.decision?.option).toBe(leaveOut.id);
    expect(decided.decision?.reason).toBe("e2e: leaving the flagged wells out");
    const left = app.page
      .getByRole("main")
      .getByRole("article")
      .filter({
        has: app.page.getByRole("button", { name: "Put the wells back" }),
      });
    await expect(left).toBeVisible({ timeout: 120_000 });
    await app.settle(60_000);
    await toTop(app.page);
    await app.axe("Controls, wells left out");

    // Put them back: the first analysis again, and the card says a person decided.
    await left.getByRole("button", { name: "Put the wells back" }).click();
    await left
      .getByRole("textbox", { name: /Why put them back/ })
      .fill("e2e: putting the wells back");
    await left.getByRole("button", { name: "Put the wells back" }).click();
    await expect
      .poll(async () => (await workspaceView(api, demo)).study_id, { timeout: 300_000 })
      .toBe(first);
    const back = await gate(api, first);
    const keep = back.consequences.find((c) => c.decision_id === decisionId)!;
    expect(keep.decision?.action).toBe("put_back");
    await expect(region.getByRole("article").first()).toContainText("Decided by you", {
      timeout: 120_000,
    });
  });
});

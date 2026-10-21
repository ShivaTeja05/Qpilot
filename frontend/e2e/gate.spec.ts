/**
 * Controls (Run Gate) on the seeded demo session: the page's headline, verdict counts, plates and
 * cards are the server's (/gate), a check opens to its reason, and the page is axe-clean.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, route } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

interface Gate {
  headline: { plain: string };
  counts: Record<string, number>;
  plates: { plate: string }[];
  cards: unknown[];
  evaluations: { verdict: string; reason: { plain: string } }[];
}

async function gate(api: APIRequestContext, studyId: string): Promise<Gate> {
  // The first gate of a study runs as a job (409 loading): ask until it answers.
  for (let i = 0; i < 120; i++) {
    const res = await api.get(`/api/studies/${studyId}/gate`, { timeout: 110_000 });
    if (res.status() === 200) return (await res.json()) as Gate;
    expect(res.status(), "GET /gate").toBe(409);
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("/gate kept loading");
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
    await app.axe("Controls");
    await app.shot("gate", "1440-light");
  });
});

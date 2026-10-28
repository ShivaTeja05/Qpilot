/**
 * A whole Studio walk of the demo through the page, from a fresh start: open the demo, propose
 * the design, accept what the engine finds consistent, reject what it contradicts, confirm; check
 * the curves, reject the contradicted AI calls, confirm; then the results are the same as the
 * seeded walk's (the seed was walked with the same rule by a scripted person).
 *
 * It moves the seeded demo aside, so it runs only with E2E_WALK=1, alone, on a fresh store copy:
 *
 *   e2e/reset-store.sh && <start qpilot app> && E2E_WALK=1 npx playwright test e2e/walk.spec.ts
 *   … then e2e/reset-store.sh again before the other specs.
 */
import type { components } from "../src/api/schema";
import { demoSession, proposals, route } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { jobsDone, resultsOf as results, reviewStage } from "./support/studio";

type ResultsView = components["schemas"]["ResultsView"];

const WALK = process.env.E2E_WALK === "1";
const REASON = "e2e walk: decided by the engine's check, as the seeded walk was";

test.describe("a Studio walk of the demo", () => {
  test.skip(!WALK, "E2E_WALK=1 only: it moves the seeded demo aside (re-copy the seed after)");
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");

  test("open → design → curves → results equal the seeded walk's", async ({ app, api }) => {
    test.setTimeout(30 * 60_000);
    const seeded = await demoSession(api);
    expect(seeded.results_visible, "start from the seeded store (e2e/reset-store.sh)").toBe(true);
    const before = await results(api, seeded.study_id!);

    // Setup (not under test here): move the seeded demo aside, as Settings' "Start a fresh demo".
    // Refused (409 busy) while a job on the demo runs, e.g. the cold start's: ask again.
    let fresh = await api.post("/api/demo/fresh");
    for (let i = 0; i < 60 && fresh.status() === 409; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      fresh = await api.post("/api/demo/fresh");
    }
    expect(fresh.status(), await fresh.text()).toBe(200);

    await app.open("/");
    await app.page.getByRole("main").getByRole("button", { name: "Open the demo study" }).click();
    await app.page.waitForURL(/#\/s\/[0-9a-f]{12}\/design/, { timeout: 300_000 });
    await app.settle(120_000);
    const sid = new URL(app.page.url()).hash.split("/")[2]!;

    // Design: propose (a job), then review and confirm.
    await app.page.getByRole("main").getByRole("button", { name: "Propose the design" }).click();
    await jobsDone(api, sid);
    await expect(app.page.getByRole("list", { name: /proposals waiting for you$/ })).toBeVisible({
      timeout: 300_000,
    });
    await app.axe("design, proposals waiting");
    await app.shot("walk", "design-waiting");
    await reviewStage(app, api, sid, "design", REASON);
    expect(
      (await proposals(api, sid, "design")).proposals.some((p) => p.status === "proposed"),
    ).toBe(false);

    // Curves: check (a job), then review and confirm.
    await app.page.goto(`${E2E.origin}/#${route({ key: sid, kind: "session" }, "curves")}`);
    await app.settle(120_000);
    await app.page.getByRole("main").getByRole("button", { name: "Check the curves" }).click();
    await jobsDone(api, sid);
    await expect(app.page.getByRole("list", { name: /proposals waiting for you$/ })).toBeVisible({
      timeout: 300_000,
    });
    await app.axe("curves, proposals waiting");
    await app.shot("walk", "curves-waiting");
    await reviewStage(app, api, sid, "curves", REASON);

    // Results: the same genes and calls as the seeded walk.
    const walked = await demoSession(api);
    expect(walked.results_visible).toBe(true);
    const after = await results(api, walked.study_id!);
    const calls = (r: ResultsView) =>
      Object.fromEntries(r.genes.map((g) => [g.gene, g.conclusion]));
    expect(calls(after)).toEqual(calls(before));
    await app.page.goto(`${E2E.origin}/#${route(walked, "results")}`);
    await app.settle(120_000);
    await expect(app.page.getByRole("table", { name: /^All genes/ })).toBeVisible();
    await app.axe("results after the walk");
    await app.shot("walk", "results");
  });
});

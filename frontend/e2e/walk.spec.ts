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
import type { APIRequestContext } from "@playwright/test";
import type { components } from "../src/api/schema";
import { demoSession, proposals, route } from "./support/data";
import { E2E } from "./support/env";
import { expect, test, type App } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

type ResultsView = components["schemas"]["ResultsView"];

const WALK = process.env.E2E_WALK === "1";
const REASON = "e2e walk: decided by the engine's check, as the seeded walk was";

async function results(api: APIRequestContext, studyId: string): Promise<ResultsView> {
  const res = await api.get(`/api/studies/${studyId}/results`, { timeout: 300_000 });
  expect(res.status()).toBe(200);
  return (await res.json()) as ResultsView;
}

/** Wait until the session has no job running (a proposal job fills the inbox as it goes). */
async function jobsDone(api: APIRequestContext, sid: string): Promise<void> {
  await expect
    .poll(
      async () => {
        const res = await api.get(`/api/sessions/${sid}`, { timeout: 60_000 });
        const frame = (await res.json()) as { active_jobs?: unknown[] };
        return frame.active_jobs?.length ?? 0;
      },
      { timeout: 600_000, intervals: [2000] },
    )
    .toBe(0);
}

/** Decide every waiting proposal of the stage the way the seeded walk did. */
async function reviewStage(
  app: App,
  api: APIRequestContext,
  sid: string,
  stage: "design" | "curves",
): Promise<void> {
  const page = app.page;
  const bulk = async (button: RegExp, go: RegExp) => {
    const open = page.getByRole("main").getByRole("button", { name: button });
    if (!(await open.count()) || (await open.isDisabled())) return;
    await open.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // The dialog lists exactly what it will do; wait for that list (a non-zero count).
    const goButton = dialog.getByRole("button", { name: go });
    const nothing = dialog.getByText(/^No waiting proposal/);
    await expect(goButton.or(nothing).first()).toBeVisible({ timeout: 120_000 });
    if (!(await goButton.count())) {
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      return;
    }
    const reason = dialog.getByRole("textbox", { name: "One reason for all of them" });
    if (await reason.count()) await reason.fill(REASON);
    await app.axe(`${stage}, bulk dialog`);
    await expect(goButton).toBeEnabled({ timeout: 60_000 });
    await goButton.click();
    await expect(dialog).toBeHidden({ timeout: 300_000 });
    await app.settle(120_000);
  };
  await bulk(/^Accept all consistent/, /^Accept these [1-9]/);
  await bulk(/^Reject contradicted AI calls/, /^Reject these [1-9]/);

  // What is left one by one: contradicted → Reject, the rest → Accept (with a reason).
  const waiting = page.getByRole("list", { name: /proposals waiting for you$/ });
  for (let i = 0; i < 60 && (await waiting.count()); i++) {
    const card = waiting.getByRole("article").first();
    const contradicted = (await card.getByRole("button", { name: "Accept anyway…" }).count()) > 0;
    if (contradicted) {
      await card.getByRole("button", { name: "Reject…" }).click();
      await card.getByRole("textbox", { name: /Why do you reject it/ }).fill(REASON);
      await card.getByRole("button", { name: "Reject", exact: true }).click();
    } else {
      await card.getByRole("button", { name: /^Accept(…)?$/ }).click();
      const why = card.getByRole("textbox", { name: /Why you accept it/ });
      if (await why.count()) {
        await why.fill(REASON);
        await card.getByRole("button", { name: "Accept", exact: true }).click();
      }
    }
    await app.settle(60_000);
  }
  await expect(page.getByText("Nothing is waiting in this stage")).toBeVisible({ timeout: 60_000 });
  // …and the server agrees.
  const waitingOnServer = async () =>
    (await proposals(api, sid, stage)).proposals.filter((p) => p.status === "proposed").length;
  await expect.poll(waitingOnServer, { timeout: 60_000 }).toBe(0);

  await page
    .getByRole("main")
    .getByRole("button", { name: /^(Confirm this stage|Review the confirm step)…$/ })
    .first()
    .click();
  const confirm = page.getByRole("dialog", { name: `Confirm the ${stage}` });
  await expect(confirm).toBeVisible();
  await app.axe(`${stage}, confirm dialog`);
  await confirm.getByRole("button", { name: "Yes, confirm" }).click();
  await expect(confirm).toBeHidden({ timeout: 300_000 });
  await app.settle(120_000);
}

test.describe("a Studio walk of the demo", () => {
  test.skip(!WALK, "E2E_WALK=1 only: it moves the seeded demo aside (re-copy the seed after)");
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
  test.beforeEach(() => {
    test.fixme(!LANDED.home, notLanded("home"));
    test.fixme(!LANDED.design, notLanded("design"));
    test.fixme(!LANDED.curves, notLanded("curves"));
    test.fixme(!LANDED.results, notLanded("results"));
  });

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
    await reviewStage(app, api, sid, "design");
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
    await reviewStage(app, api, sid, "curves");

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

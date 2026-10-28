/**
 * Trace in a Studio session, on the seeded demo: a place whose option changes a call is decided
 * on the page (Decide… → set the sample aside, with a reason), the study is analysed again
 * without it and the Results change as the place said; then "Put the wells back" returns to the
 * first analysis (the same study). And the Run Review's repeat plan: what to repeat and why, and
 * the repeat plate as the planner's CSV.
 *
 * Which gene, which place and what changes are read from the API (where-to-look); the spec puts
 * the wells back at the end, through the page, or through the API when the page failed.
 */
import type { APIRequestContext } from "@playwright/test";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { components } from "../src/api/schema";
import { demoSession, literal, route, workspaceView, type Workspace } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { download, jobsDone, resultsOf, settledJson } from "./support/studio";

type S = components["schemas"];
type Where = S["WhereView"];

const REASON =
  "e2e: the HMBS curve of this well never rose; the other reference wells read normally";

/** A gene, a place and its set-aside option that changes the gene's call (none: skip). */
async function placeToSetAside(api: APIRequestContext, demo: Workspace) {
  const results = await resultsOf(api, demo.study_id!);
  for (const { gene } of results.genes) {
    const where = await settledJson<Where>(
      api,
      `/api/studies/${demo.study_id}/where-to-look?gene=${encodeURIComponent(gene)}`,
    );
    if (!where.can_apply) continue;
    for (const place of where.places) {
      const option = place.options.find(
        (o) => o.id === "set_aside" && o.applies && o.changed_calls.includes(gene),
      );
      if (place.can_decide && option) return { gene, where, place, option };
    }
  }
  return null;
}

/** The session's study once it is analysed again (a decision on Trace starts the analysis). */
async function studyAfter(api: APIRequestContext, sid: string, not: string): Promise<string> {
  let study = "";
  await expect
    .poll(
      async () => {
        const frame = await workspaceView(api, { key: sid, kind: "session" });
        study = frame.results_visible && frame.study_id ? frame.study_id : "";
        return Boolean(study) && study !== not;
      },
      { timeout: 600_000, intervals: [1000, 2000] },
    )
    .toBe(true);
  return study;
}

async function putBackByApi(api: APIRequestContext, study: string): Promise<void> {
  const listed = await settledJson<S["TraceSetAsideView"]>(
    api,
    `/api/studies/${study}/where-to-look/set-aside`,
  );
  for (const entry of listed.set_aside) {
    await api.post(`/api/studies/${study}/where-to-look/put-back`, {
      data: {
        card_id: entry.card_id,
        reason: "e2e: cleaning up after a failed run",
        expected_inbox: listed.inbox_head,
      },
    });
  }
}

test.describe("Trace: Decide…, set aside, put back", () => {
  test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");

  test("a set-aside changes the Results as the place said; Put the wells back undoes it", async ({
    app,
    api,
  }) => {
    test.setTimeout(20 * 60_000);
    const demo = await demoSession(api);
    const first = demo.study_id!;
    const found = await placeToSetAside(api, demo);
    test.skip(!found, "no place of this study has a set-aside that changes a call");
    const { gene, place, option } = found!;
    const before = (await resultsOf(api, first)).genes.find((g) => g.gene === gene)!;
    let now = first;
    try {
      await app.open(route(demo, "trace", gene));
      const page = app.page;
      const places = page.getByRole("list", { name: "Places to look" });
      await expect(places).toBeVisible({ timeout: 120_000 });
      const row = places.getByRole("listitem").filter({ hasText: place.sample }).first();
      await row.getByRole("button", { name: /^Decide…/ }).click();
      const choices = row.getByRole("radiogroup", { name: "What to do at this place" });
      await expect(choices).toBeVisible();
      await choices.getByRole("radio", { name: literal(option.label) }).check();
      await row.getByRole("textbox", { name: /^Why this option/ }).fill(REASON);
      await app.axe("trace, deciding a place");
      await row.getByRole("button", { name: `Decide: ${option.label}` }).click();

      // The wells are out; the session's study is analysed again without them.
      now = await studyAfter(api, demo.key, first);
      await jobsDone(api, demo.key);
      const after = (await resultsOf(api, now)).genes.find((g) => g.gene === gene);
      expect(after?.conclusion, `${gene}'s call without the wells`).not.toBe(before.conclusion);
      await app.open(route(demo, "results"));
      const table = page.getByRole("table", { name: /^All genes/ });
      await expect(table).toBeVisible({ timeout: 120_000 });
      await app.axe("results, after a set-aside");

      // Put the wells back, from Trace: the first analysis again.
      await app.open(route(demo, "trace", gene));
      const aside = page.getByRole("region", { name: "Set aside from Trace" });
      await expect(aside).toBeVisible({ timeout: 120_000 });
      await expect(aside).toContainText(REASON);
      await aside
        .getByRole("button", { name: /^Put the wells back/ })
        .first()
        .click();
      await aside
        .getByRole("textbox", { name: /^Why put them back/ })
        .fill("e2e: the repeat plate gave the same value");
      await app.axe("trace, putting the wells back");
      await aside.getByRole("button", { name: "Put the wells back", exact: true }).click();
      now = await studyAfter(api, demo.key, now);
      expect(now, "the same design: the first analysis, the same study").toBe(first);
      await jobsDone(api, demo.key);
      const back = (await resultsOf(api, now)).genes.find((g) => g.gene === gene)!;
      expect(back.conclusion).toBe(before.conclusion);
      expect(back.log2fc).toBeCloseTo(before.log2fc, 12);
    } finally {
      if (now !== first) await putBackByApi(api, now);
    }
  });

  test("Run Review: the repeat plan, and the repeat plate as a CSV", async ({ app, api }) => {
    const demo = await demoSession(api);
    const plan = await settledJson<S["RepeatView"]>(
      api,
      `/api/studies/${demo.study_id}/review/repeat?include=consequential`,
    );
    await app.open(route(demo, "report"));
    const block = app.page.getByRole("region", { name: "What to repeat and why" });
    await expect(block).toBeVisible({ timeout: 120_000 });
    const items = block.getByRole("list", { name: "What to repeat, most consequential first" });
    if (plan.plan.items.length) {
      await expect(items.getByRole("listitem")).toHaveCount(
        Math.min(plan.plan.items.length, await items.getByRole("listitem").count()),
      );
      await expect(items.getByRole("listitem").first()).toBeVisible();
    }
    const link = block.getByRole("link", { name: "Download the repeat plate (CSV)" });
    const dir = mkdtempSync(join(tmpdir(), "qpilot-e2e-repeat-"));
    const file = await download(app, link, dir);
    expect(file.name).toBe(plan.csv_name);
    const [header, ...rows] = readFileSync(file.path, "utf8").trim().split("\n");
    expect(header!.toLowerCase()).toContain("well");
    expect(header!.toLowerCase()).toContain("sample");
    expect(rows.length).toBeGreaterThan(0);
    await app.axe("report, run review repeat plan");
  });
});

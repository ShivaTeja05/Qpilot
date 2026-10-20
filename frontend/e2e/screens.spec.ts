/**
 * Every section of the seeded demo session at every width (1440 / 1024 / 768 / 390), in light
 * and dark: it renders without an error, axe finds nothing serious, the page never scrolls
 * sideways, and a screenshot is saved under e2e/screenshots/<section>/<width>-<theme>.png.
 * A section still showing the development placeholder is `fixme` with its owner.
 */
import { demoSession, route, type Workspace } from "./support/data";
import { THEMES, viewportFor, WIDTHS } from "./support/env";
import { expect, test, type App } from "./support/fixtures";
import { PENDING_TEXT, SECTIONS } from "./support/sections";
import type { APIRequestContext } from "@playwright/test";

/** Words that mean the page is showing a bug instead of plain words (docs/app.md §1.7). */
const LEAKS =
  /\bNaN\b|\bundefined\b|\[object Object\]|Traceback \(most recent|^\s*at \S+ \(.+:\d+:\d+\)/m;

/** A gene of the open study, from the results route (the Gene section needs one). */
async function firstGene(api: APIRequestContext, w: Workspace): Promise<string | null> {
  const res = await api.get(`/api/studies/${w.study_id}/results`);
  if (!res.ok()) return null;
  const body = (await res.json()) as { genes?: { gene: string }[] };
  return body.genes?.[0]?.gene ?? null;
}

async function checkState(app: App, group: string, name: string): Promise<void> {
  const page = app.page;
  await expect(page.locator("main"), "a <main> landmark").toHaveCount(1);
  await expect(
    page.getByRole("heading", { level: 1 }).first(),
    "the section's heading",
  ).toBeVisible();
  const text = await page.locator("body").innerText();
  expect
    .soft(text.match(LEAKS)?.[0] ?? null, `${group} ${name}: shows a bug, not words`)
    .toBeNull();
  await app.noSideScroll(`${group} ${name}`);
  await app.axe(`${group} ${name}`);
  await app.shot(group, name);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test.describe(`${width} px, ${theme}`, () => {
      test.use({ viewport: viewportFor(width), colorScheme: theme });

      for (const section of SECTIONS) {
        test(`${section.label}`, async ({ app, api }) => {
          const demo = section.scope === "workspace" ? await demoSession(api) : null;
          const rest: string[] = [];
          if (section.id === "gene") {
            const gene = demo ? await firstGene(api, demo) : null;
            test.fixme(
              !gene,
              "no gene to open: GET /api/studies/{id}/results is not served yet (owner: api)",
            );
            rest.push(gene!);
          }
          await app.open(route(demo, section.id, ...rest));
          const pending = await app.page.getByText(PENDING_TEXT).count();
          test.fixme(
            pending > 0,
            `${section.label} is still the placeholder (owner: ${section.owner})`,
          );
          await checkState(app, section.id, `${width}-${theme}`);
        });
      }
    });
  }
}

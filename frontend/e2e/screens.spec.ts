/**
 * Every section of the seeded demo session at every width (1440 / 1024 / 768 / 390), in light
 * and dark: it renders without an error, axe finds nothing serious, the page never scrolls
 * sideways, and a screenshot is saved under e2e/screenshots/<section>/<width>-<theme>.png.
 * No section may show the development placeholder.
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
  const main = page.getByRole("main");
  await expect(main, "one <main> landmark").toHaveCount(1);
  await expect.soft(main.getByRole("heading").first(), "the section's heading").toBeVisible();
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
          // A full-page screenshot and axe at every width: heavy on a loaded machine (the run of
          // 28 Oct at load ~60 timed out at 120 s with nothing wrong on the page).
          test.slow();
          const demo = section.scope === "workspace" ? await demoSession(api) : null;
          const rest: string[] = [];
          if (section.id === "gene") {
            const gene = demo ? await firstGene(api, demo) : null;
            expect(gene, "a gene to open (GET /api/studies/{id}/results)").toBeTruthy();
            rest.push(gene!);
          }
          await app.open(route(demo, section.id, ...rest));
          await expect(
            app.page.getByText(PENDING_TEXT),
            `${section.label} shows the development placeholder (owner: ${section.owner})`,
          ).toHaveCount(0);
          await checkState(app, section.id, `${width}-${theme}`);
        });
      }
    });
  }
}

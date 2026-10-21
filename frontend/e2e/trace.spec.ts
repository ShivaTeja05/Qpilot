/**
 * Trace on the seeded demo session: the study overview's words are the server's (/trace), a gene's
 * trace shows what it stands on and the places to look (/trace/{gene}), and the Gene section links
 * to it.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, literal, route } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

interface Texts {
  texts: Record<string, { plain: string }>;
}

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  const res = await api.get(path, { timeout: 110_000 });
  expect(res.status(), `GET ${path}`).toBe(200);
  return (await res.json()) as T;
}

/** The first clause of a server sentence (the page cites numbers inline, so compare words). */
const firstClause = (s: string) => s.split(/[.:;]/)[0]!.trim();

test.describe("Trace", () => {
  test.beforeEach(() => test.fixme(!LANDED.trace, notLanded("trace")));

  test("the study overview says what /trace says, with its four lists", async ({ app, api }) => {
    const demo = await demoSession(api);
    const t = await getJson<Texts>(api, `/api/studies/${demo.study_id}/trace`);
    await app.open(route(demo, "trace"));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText("What each result stands on", {
      timeout: 60_000,
    });
    await expect(main).toContainText(firstClause(t.texts.summary!.plain));
    await expect(
      main.getByRole("figure", { name: /^How many samples it takes to change each call:/ }),
    ).toBeVisible();
    for (const name of [
      "Calls that hang on few samples",
      "Samples behind the most calls",
      "Control-gene wells that disagree",
    ]) {
      // The card and, inside it, its scrolling table carry the same name.
      await expect(main.getByRole("region", { name }).first()).toBeVisible();
    }
    await app.axe("Trace overview");
  });

  test("a headline gene's trace: what it stands on and the places to look", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const { headline } = await getJson<{ headline: string[] }>(
      api,
      `/api/studies/${demo.study_id}/results`,
    );
    const gene = headline[0]!;
    const t = await getJson<Texts>(
      api,
      `/api/studies/${demo.study_id}/trace/${encodeURIComponent(gene)}`,
    );
    await app.open(route(demo, "trace", gene));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(gene, { timeout: 60_000 });
    await expect(main.getByRole("region", { name: `What ${gene} stands on` })).toBeVisible();
    const places = main.getByRole("region", { name: "Places to look" });
    await expect(places).toBeVisible();
    if (t.texts.place_1) await expect(places).toContainText(firstClause(t.texts.place_1.plain));
    await app.axe(`Trace ${gene}`);
    await app.shot("trace", `${gene}-1440-light`);
  });

  test("the Gene section links to the gene's trace", async ({ app, api }) => {
    const demo = await demoSession(api);
    const { headline } = await getJson<{ headline: string[] }>(
      api,
      `/api/studies/${demo.study_id}/results`,
    );
    const gene = headline[0]!;
    await app.open(route(demo, "gene", gene));
    await app.page
      .getByRole("link", {
        name: new RegExp(`^Trace this gene\\s*:\\s*${literal(gene).source} down to its samples`),
      })
      .first()
      .click();
    await app.settle();
    expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(`#${route(demo, "trace", gene)}`);
  });
});

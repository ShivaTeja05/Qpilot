/**
 * Prism on the seeded demo session: what the usual routes into Prism would change is the server's
 * (/prism/routes: per route, how many conclusions differ and which genes), and each gene opens
 * the Gene section. Nothing is sent to Prism here (that launches an app on this machine).
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, literal, route } from "./support/data";
import { expect, test } from "./support/fixtures";

interface PrismRoutes {
  n_genes: number;
  routes: { route: string; n_differ: number; n_genes: number; genes: string[] }[];
}

async function routes(api: APIRequestContext, sid: string): Promise<PrismRoutes> {
  const res = await api.get(`/api/sessions/${sid}/prism/routes`, { timeout: 110_000 });
  expect(res.status()).toBe(200);
  return (await res.json()) as PrismRoutes;
}

test.describe("Prism", () => {
  test("each route into Prism lists the genes it concludes differently, as the server says", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const r = await routes(api, demo.key);
    expect(r.routes.length).toBeGreaterThan(0);
    await app.open(route(demo, "prism"));
    const list = app.page.getByRole("list", { name: "Routes into Prism" });
    await expect(list).toBeVisible();
    for (const x of r.routes.filter((x) => x.n_differ > 0)) {
      const genes = list.getByRole("list", {
        name: `Genes this route concludes differently (${x.n_differ})`,
      });
      await expect(genes.first()).toBeVisible();
      await expect(list).toContainText(`${x.n_differ} of ${x.n_genes} differ`);
    }
    // Every gene a route names is a link to that gene.
    const worst = [...r.routes].sort((a, b) => b.n_differ - a.n_differ)[0]!;
    const genes = list.getByRole("list", {
      name: `Genes this route concludes differently (${worst.n_differ})`,
    });
    // Long lists show the first genes and a "Show all N" button.
    const all = list.getByRole("button", { name: `Show all ${worst.n_differ}` });
    if (await all.count()) await all.first().click();
    for (const g of worst.genes) {
      const link = genes.first().getByRole("link", { name: new RegExp(`^${literal(g).source} `) });
      await expect(link).toHaveAttribute("href", `#${route(demo, "gene", g)}`);
    }
    await app.axe("Prism");
  });
});

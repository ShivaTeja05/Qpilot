/**
 * Prism on the seeded demo session: the routes table and the preview come from /prism/routes and
 * /prism/preview; nothing is sent to Prism here (that launches an app on this machine).
 */
import { demoSession, maybeJson, route } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

test.describe("Prism", () => {
  test.beforeEach(() => test.fixme(!LANDED.prism, notLanded("prism")));

  test("the routes table lists the server's routes", async ({ app, api }) => {
    const demo = await demoSession(api);
    const routes = await maybeJson<{ routes?: { name?: string; label?: string }[] }>(
      api,
      `/api/sessions/${demo.key}/prism/routes`,
    );
    test.fixme(!routes, "GET …/prism/routes is not served yet (owner: api-files)");
    await app.open(route(demo, "prism"));
    const table = app.page.getByRole("table", { name: /route/i }).first();
    await expect(table).toBeVisible();
    for (const r of (routes!.routes ?? []).slice(0, 5)) {
      const name = r.label ?? r.name;
      if (name) await expect(table.getByText(name).first()).toBeVisible();
    }
    await app.axe("Prism");
  });
});

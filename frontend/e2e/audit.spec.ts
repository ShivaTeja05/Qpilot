/**
 * Audit on the seeded demo session (the seed already holds a robustness audit, so nothing is
 * re-run): the Study tab's verdict counts are the server's, the tabs work, a gene row opens Gene.
 */
import { demoSession, literal, maybeJson, route } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

interface AuditStatus {
  state?: string;
  status?: string;
}

test.describe("Audit", () => {
  test.beforeEach(() => test.fixme(!LANDED.audit, notLanded("audit")));

  test("the seeded audit is shown as done, with the server's verdict counts", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    expect(demo.has_audit, "the seed has an audit").toBe(true);
    const status = await maybeJson<AuditStatus>(api, `/api/studies/${demo.study_id}/audit`);
    test.fixme(!status, "GET /api/studies/{id}/audit is not served yet (owner: api-audit)");
    const overview = await maybeJson<{ verdicts?: Record<string, number> }>(
      api,
      `/api/studies/${demo.study_id}/audit/overview`,
    );
    await app.open(route(demo, "audit"));
    await expect(app.page.getByRole("tab", { name: /study/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    for (const [verdict, n] of Object.entries(overview?.verdicts ?? {})) {
      await expect(
        app.page.getByText(new RegExp(`${n}\\s*${verdict}|${verdict}\\D{0,3}${n}`, "i")).first(),
      ).toBeVisible();
    }
    await app.axe("Audit, Study tab");
  });

  test("every tab opens and passes axe", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "audit"));
    for (const name of [/what-if/i, /how it works/i, /verify/i, /study/i]) {
      await app.page.getByRole("tab", { name }).click();
      await app.settle();
      await expect(app.page.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
      await app.axe(`Audit, ${name.source} tab`);
      await app.shot("audit", `tab-${name.source.replace(/\W/g, "")}`);
    }
  });

  test("a gene row opens the Gene section with the audit's views", async ({ app, api }) => {
    test.fixme(!LANDED.gene, notLanded("gene"));
    const demo = await demoSession(api);
    await app.open(route(demo, "audit"));
    const row = app.page
      .getByRole("row")
      .filter({ has: app.page.getByRole("link") })
      .first();
    const gene = (await row.getByRole("link").first().innerText()).trim();
    await row.getByRole("link").first().click();
    await app.settle();
    await expect(app.page.getByRole("heading", { level: 1, name: literal(gene) })).toBeVisible();
    await expect(app.page.getByText(/what changes it/i).first()).toBeVisible();
  });
});

/**
 * Record and Agents on the seeded demo session: the timeline is the server's chain, Export
 * downloads an Analysis Record (a zip), and Agents shows how to connect and what agents asked.
 */
import { readFileSync } from "node:fs";
import { demoSession, maybeJson, route, workspaceView } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

test.describe("Record", () => {
  test.beforeEach(() => test.fixme(!LANDED.record, notLanded("record")));

  test("the timeline shows every chain entry and the chain head", async ({ app, api }) => {
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    const chain = await maybeJson<{ entries?: unknown[] } | unknown[]>(
      api,
      `/api/studies/${demo.study_id}/decisions`,
    );
    test.fixme(!chain, "GET /api/studies/{id}/decisions is not served yet (owner: api)");
    const entries = Array.isArray(chain) ? chain : (chain!.entries ?? []);
    await app.open(route(demo, "record"));
    const timeline = app.page.getByRole("list", { name: /chain|timeline|decisions/i }).first();
    await expect(timeline.getByRole("listitem")).toHaveCount(entries.length);
    if (view.decisions_head)
      await expect(app.page.getByText(view.decisions_head.slice(0, 8)).first()).toBeVisible();
    await app.axe("Record");
  });

  test("Export the Analysis Record downloads a zip", async ({ app, api }) => {
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
    test.setTimeout(180_000);
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await app.page.getByRole("button", { name: /export the analysis record/i }).click();
    // A job: its card says what it does; then a download link or an automatic download.
    const download = app.page.waitForEvent("download", { timeout: 150_000 });
    const link = app.page.getByRole("link", { name: /download/i }).first();
    const got = await Promise.race([
      download,
      link.waitFor({ timeout: 150_000 }).then(async () => {
        const [d] = await Promise.all([app.page.waitForEvent("download"), link.click()]);
        return d;
      }),
    ]);
    expect(got.suggestedFilename()).toMatch(/\.zip$/);
    const path = await got.path();
    const bytes = readFileSync(path);
    expect(bytes.subarray(0, 2).toString("latin1"), "a zip file").toBe("PK");
    await app.axe("Record, after export");
  });

  test("the qpilot verify / rerun commands are copyable", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await expect(app.page.getByText(/qpilot verify/).first()).toBeVisible();
    await expect(app.page.getByText(/qpilot rerun/).first()).toBeVisible();
    await expect(app.page.getByRole("button", { name: /copy/i }).first()).toBeVisible();
  });
});

test.describe("Agents", () => {
  test.beforeEach(() => test.fixme(!LANDED.agents, notLanded("agents")));

  test("shows the MCP command, the tools and the waiting requests from /api/agents", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const agents = await maybeJson<{
      command?: string;
      tools?: { name: string }[];
      pending?: unknown[];
    }>(api, "/api/agents");
    test.fixme(!agents, "GET /api/agents is not served yet (owner: api-ops)");
    await app.open(route(demo, "agents"));
    if (agents!.command) await expect(app.page.getByText(agents!.command).first()).toBeVisible();
    for (const t of (agents!.tools ?? []).slice(0, 5))
      await expect(app.page.getByText(t.name).first()).toBeVisible();
    await expect(app.page.getByRole("button", { name: /copy/i }).first()).toBeVisible();
    await app.axe("Agents");
  });
});

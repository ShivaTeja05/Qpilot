/**
 * Record and Agents on the seeded demo session: the timeline is the server's chain (/decisions),
 * Export downloads an Analysis Record (a zip) that Verify then checks, a changed copy does not
 * check out, and Agents shows how to connect, the rules and the tools from /api/agents.
 */
import { readFileSync, writeFileSync } from "node:fs";
import type { APIRequestContext } from "@playwright/test";
import type { components } from "../src/api/schema";
import { demoSession, route, type Workspace } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";

type DecisionsView = components["schemas"]["DecisionsView"];

interface AgentsView {
  connect: string;
  rules: string[];
  tools: { name: string; summary: string }[];
  pending: unknown[];
}

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  const res = await api.get(path, { timeout: 110_000 });
  expect(res.status(), `GET ${path}`).toBe(200);
  return (await res.json()) as T;
}

const decisions = (api: APIRequestContext, w: Workspace) =>
  getJson<DecisionsView>(api, `/api/studies/${w.study_id}/decisions`);

test.describe("Record", () => {
  test("the timeline shows every chain entry, and the chain is intact", async ({ app, api }) => {
    const demo = await demoSession(api);
    const chain = await decisions(api, demo);
    await app.open(route(demo, "record"));
    const timeline = app.page.getByRole("list", { name: "Decision chain entries, newest first" });
    await expect(timeline).toBeVisible();
    await expect(timeline.getByRole("article")).toHaveCount(chain.entries.length);
    for (const e of chain.entries) {
      await expect(timeline.getByRole("article", { name: `Entry ${e.entry.seq}` })).toBeVisible();
    }
    await expect(app.page.getByText("Intact: every hash checks out")).toBeVisible();
    await app.axe("Record");
  });

  test("Export downloads a record zip, and Verify says it checks out", async ({ app, api }) => {
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
    test.setTimeout(300_000);
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    const exportCard = app.page.getByRole("region", { name: "Export the Analysis Record" });
    await exportCard
      .getByRole("button", { name: /^(Export the Analysis Record|Export again)$/ })
      .click();
    // A job card while it runs, then the download link with the record's file name.
    const link = exportCard.getByRole("link", { name: /^Download( the record| .+\.zip)/ });
    await expect(link).toBeVisible({ timeout: 240_000 });
    await app.axe("Record, exported");
    const [download] = await Promise.all([app.page.waitForEvent("download"), link.click()]);
    expect(download.suggestedFilename()).toMatch(/\.zip$/);
    const zip = await download.path();
    expect(readFileSync(zip).subarray(0, 2).toString("latin1"), "a zip file").toBe("PK");

    // Verify the same file in the page.
    const verifyCard = app.page.getByRole("region", { name: "Verify a record" });
    await verifyCard.locator('input[type="file"]').setInputFiles({
      name: download.suggestedFilename(),
      mimeType: "application/zip",
      buffer: readFileSync(zip),
    });
    await expect(verifyCard.getByText("This record checks out")).toBeVisible({ timeout: 120_000 });
    await app.axe("Record, verified");

    // A copy with one byte changed in the middle must not check out.
    const bytes = Buffer.from(readFileSync(zip));
    const at = Math.floor(bytes.length / 2);
    bytes[at] = bytes[at]! ^ 0xff;
    const changed = test.info().outputPath("changed.zip");
    writeFileSync(changed, bytes);
    await verifyCard.locator('input[type="file"]').setInputFiles(changed);
    await expect(
      verifyCard.getByText(/This record does not check out|This file could not be checked/),
    ).toBeVisible({ timeout: 120_000 });
    await expect(verifyCard.getByText("This record checks out")).toHaveCount(0);
    app.allowConsole(/status of 4\d\d/);
  });

  test("the qpilot verify / rerun commands are shown with a copy button", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await expect(app.page.getByText(/qpilot verify/).first()).toBeVisible();
    await expect(app.page.getByText(/qpilot rerun/).first()).toBeVisible();
    await expect(app.page.getByRole("button", { name: /copy/i }).first()).toBeVisible();
  });
});

test.describe("Agents", () => {
  test("shows the connect command, the rules and the tools from /api/agents", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const agents = await getJson<AgentsView>(api, "/api/agents");
    await app.open(route(demo, "agents"));
    await expect(
      app.page.getByRole("region", { name: "Connect an agent" }).getByText(agents.connect),
    ).toBeVisible();
    const rules = app.page.getByRole("region", { name: "What an agent can never do" });
    for (const r of agents.rules) await expect(rules).toContainText(r);
    const tools = app.page.getByRole("region", { name: "The tools" });
    await expect(tools).toContainText(`${agents.tools.length} tools`);
    for (const t of agents.tools)
      await expect(tools.getByText(t.name, { exact: true })).toBeAttached();
    await expect(app.page.getByRole("button", { name: /copy/i }).first()).toBeVisible();
    if (agents.pending.length === 0)
      await expect(app.page.getByText("No requests waiting")).toBeVisible();
    await app.axe("Agents");
  });
});

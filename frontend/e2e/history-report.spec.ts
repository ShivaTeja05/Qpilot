/**
 * History and Report on the seeded demo session: the timeline, the Studio log and the chain state
 * are the server's (/history); the report's summary, reviewer's findings, methods and MIQE checklist
 * come from /report, and writing the passport downloads a file.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, route } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";

interface HistoryView {
  chain_intact: boolean;
  steps: { seq: number }[];
  studio: { title: string }[];
}
interface Text {
  plain: string;
}
interface ReportView {
  summary: Text;
  methods: { paragraphs: { id: string; title: string }[] };
  review: { lead: Text };
}

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  const res = await api.get(path, { timeout: 110_000 });
  expect(res.status(), `GET ${path}`).toBe(200);
  return (await res.json()) as T;
}

test.describe("History", () => {
  test("the timeline, the Studio log and the chain state are the server's", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const h = await getJson<HistoryView>(api, `/api/studies/${demo.study_id}/history`);
    await app.open(route(demo, "history"));
    await expect(app.page.getByRole("main").getByRole("heading", { level: 1 })).toHaveText(
      "History",
    );
    await expect(app.page.getByRole("list", { name: "History of this analysis" })).toBeVisible();
    if (h.chain_intact)
      await expect(app.page.getByText("Intact: every hash checks out").first()).toBeVisible();
    const log = app.page.getByRole("region", { name: "Studio log" });
    for (const s of h.studio) await expect(log).toContainText(s.title);
    await expect(
      app.page.getByRole("region", { name: "Robustness map at this point" }),
    ).toBeVisible();
    await app.axe("History");
  });
});

test.describe("Report", () => {
  test("summary, reviewer's findings, methods and MIQE come from /report", async ({ app, api }) => {
    const demo = await demoSession(api);
    const r = await getJson<ReportView>(api, `/api/studies/${demo.study_id}/report`);
    await app.open(route(demo, "report"));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText("Report");
    // Facts are cited inline, so compare the words of the first sentence.
    const firstSentence = r.summary.plain.split(". ")[0]!;
    await expect(main).toContainText(firstSentence);
    await expect(main.getByRole("list", { name: "Findings" })).toBeVisible();
    for (const p of r.methods.paragraphs) await expect(main).toContainText(p.title);
    await expect(main.getByRole("img", { name: /^MIQE 2\.0 items by status:/ })).toBeVisible();
    await expect(main.getByRole("button", { name: "Copy as plain text" })).toBeVisible();
    await app.axe("Report");
  });

  test("writing the passport ends with a file to download", async ({ app, api }) => {
    test.skip(E2E.readOnly, "E2E_READONLY=1: no writes");
    test.setTimeout(300_000);
    const demo = await demoSession(api);
    await app.open(route(demo, "report"));
    const panel = app.page.getByRole("region", { name: "Export: numbers, figures and the report" });
    await panel.getByRole("button", { name: "Write the passport" }).click();
    const link = panel.getByRole("link", { name: /download/i }).first();
    await expect(link).toBeVisible({ timeout: 240_000 });
    const [download] = await Promise.all([app.page.waitForEvent("download"), link.click()]);
    expect(download.suggestedFilename()).toMatch(/\.(html|zip|pdf|md)$/);
    await app.axe("Report, passport written");
  });
});

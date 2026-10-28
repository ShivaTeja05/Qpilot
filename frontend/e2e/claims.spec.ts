/**
 * Claims on the seeded demo session: the page's examples are the server's (/claims/examples), and
 * a checked paragraph gets the same verdicts on the page as the server gives it (POST /claims).
 * Nothing is stored: the check reads the study's record only.
 */
import type { APIRequestContext } from "@playwright/test";
import { demoSession, route } from "./support/data";
import { expect, test } from "./support/fixtures";

interface ClaimsReport {
  claims: { id: string; verdict: string; verdict_label: string }[];
  summary: { n: number; sentence: string; counts: Record<string, number> };
}

async function check(api: APIRequestContext, studyId: string, text: string): Promise<ClaimsReport> {
  const res = await api.post(`/api/studies/${studyId}/claims`, {
    data: { text },
    timeout: 110_000,
  });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()) as ClaimsReport;
}

test.describe("Claims", () => {
  test("a paragraph typed in is checked with the server's verdicts", async ({ app, api }) => {
    const demo = await demoSession(api);
    const ex = await api.get(`/api/studies/${demo.study_id}/claims/examples`);
    const { examples } = (await ex.json()) as { examples: { text: string }[] };
    expect(examples.length).toBeGreaterThan(0);
    // Two of the study's own example sentences, as one paragraph a person might paste.
    const text = examples
      .slice(0, 2)
      .map((e) => e.text)
      .join(" ");
    const expected = await check(api, demo.study_id!, text);

    await app.open(route(demo, "claims"));
    const main = app.page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText("Claims");
    await main.getByRole("textbox", { name: "The text to check" }).fill(text);
    await app.page.keyboard.press(`${process.platform === "darwin" ? "Meta" : "Control"}+Enter`);
    const found = main.getByRole("region", { name: "What was found" });
    await expect(found).toBeVisible({ timeout: 60_000 });
    // "1 of 2 claims supported": the server's counts (its sentence adds "by this study's record").
    const supported = expected.summary.counts.supported ?? 0;
    await expect(main).toContainText(
      new RegExp(`${supported} of ${expected.summary.n} claims? supported`),
    );
    for (const c of expected.claims) await expect(found).toContainText(c.verdict_label);
    await app.axe("Claims, checked");
    await app.shot("claims", "checked-1440-light");
  });

  test("Try an example from this study fills the text and checks it", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "claims"));
    const main = app.page.getByRole("main");
    await main.getByRole("button", { name: "Try an example from this study" }).click();
    await expect(main.getByRole("region", { name: "What was found" })).toBeVisible({
      timeout: 60_000,
    });
    await expect(main.getByText("Your text, checked")).toBeVisible();
  });
});

/**
 * The shell: the printed link, the needs-key screen, nothing leaving the machine, the rail
 * (every section reachable from Open → Recent → the rail), and the theme.
 */
import { demoSession, literal, route, workspaceView } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded, SECTIONS } from "./support/sections";

test.describe("the launch key", () => {
  test("the printed link sets the key and drops it from the address bar", async ({ app }) => {
    const answers: number[] = [];
    app.page.on("response", (r) => {
      if (r.url().startsWith(`${E2E.origin}/api/`)) answers.push(r.status());
    });
    await app.open("/");
    expect(
      new URL(app.page.url()).searchParams.has("token"),
      "the key is gone from the address",
    ).toBe(false);
    expect(answers.length, "the page asked the API something").toBeGreaterThan(0);
    expect(
      answers.filter((s) => s === 401),
      "no API call was refused for a missing key",
    ).toEqual([]);
  });

  test("a link from another launch is refused in words", async ({ page }) => {
    const res = await page.goto(`${E2E.origin}/?token=not-this-launch`);
    expect(res?.status()).toBe(403);
    await expect(page.locator("body")).toContainText("another launch");
  });

  test("the page is served with a same-origin-only CSP", async ({ request }) => {
    const res = await request.get(`${E2E.origin}/`);
    expect(res.ok()).toBe(true);
    const csp = res.headers()["content-security-policy"] ?? "";
    expect(csp, "Content-Security-Policy").toContain("default-src 'self'");
  });

  test("without the key the page says to open the printed link", async ({ browser }) => {
    test.fixme(!LANDED.needsKey, notLanded("needsKey"));
    // A fresh browser profile: no cookie. Open the bare address (no ?token=).
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(`${E2E.origin}/`);
    await expect(page.getByText(/Open the link qPilot printed/i)).toBeVisible();
    // The screen is the whole page: no section, no rail, no raw error.
    await expect(page.getByText(/no_token|401|Unauthorized/)).toHaveCount(0);
    await context.close();
    expect(errors.filter((e) => !/401/.test(e))).toEqual([]);
  });
});

test.describe("the rail", () => {
  test("Open → Recent → every section is reachable from the rail", async ({ app, api }) => {
    test.fixme(!LANDED.home, notLanded("home"));
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    await app.open("/");
    await app.page
      .getByRole("link", { name: literal(demo.title) })
      .first()
      .click();
    await app.settle();
    const nav = app.page.getByRole("navigation", { name: /sections|workflow/i });
    for (const s of SECTIONS.filter((x) => !x.hidden && x.scope === "workspace")) {
      await nav.getByRole("link", { name: new RegExp(`^${s.label}`) }).click();
      await app.settle();
      expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(`#${route(demo, s.id)}`);
      await expect(app.page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await app.axe(`rail → ${s.label}`);
    }
    await nav.getByRole("link", { name: /^Settings/ }).click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toBe("#/settings");
  });

  test("the rail shows each stage's live state", async ({ app, api }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    await app.open(route(demo, "results"));
    const nav = app.page.getByRole("navigation", { name: /sections|workflow/i });
    for (const stage of view.stages.filter((s) => s.stage === "design" || s.stage === "curves")) {
      const link = nav.getByRole("link", { name: new RegExp(`^${stage.stage}`, "i") });
      // A confirmed stage says so in words (not by colour alone).
      if (stage.confirmed) await expect(link).toHaveAccessibleName(/confirmed/i);
    }
  });

  test("the next-step banner names the workspace's next step", async ({ app, api }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    test.skip(!view.next_step, "the workspace has no next step");
    await app.open(route(demo, "record"));
    await expect(app.page.getByText(view.next_step!.title)).toBeVisible();
  });
});

test.describe("the theme", () => {
  test("the toggle switches light ↔ dark and the choice survives a reload", async ({ app }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    await app.open("/");
    const html = app.page.locator("html");
    await app.page
      .getByRole("button", { name: /theme|dark|light/i })
      .first()
      .click();
    const after = await html.getAttribute("data-theme");
    expect(after === "dark" || after === "light").toBe(true);
    await app.axe(`theme ${after}`);
    await app.page.reload();
    await app.settle();
    await expect(html).toHaveAttribute("data-theme", after!);
  });

  test("the system's dark mode is followed with no saved choice", async ({ app }) => {
    await app.page.emulateMedia({ colorScheme: "dark" });
    await app.open("/");
    await expect(app.page.locator("html")).not.toHaveAttribute("data-theme", "light");
    // The page's own background (body, else html), not a transparent default.
    const bg = await app.page.evaluate(() => {
      const opaque = (c: string) => !/rgba\(.*,\s*0\)$|transparent/.test(c);
      const body = getComputedStyle(document.body).backgroundColor;
      return opaque(body) ? body : getComputedStyle(document.documentElement).backgroundColor;
    });
    const [r = 255, g = 255, b = 255] = (bg.match(/\d+(\.\d+)?/g) ?? []).map(Number);
    expect((r + g + b) / 3, `page background ${bg} is dark`).toBeLessThan(80);
  });
});

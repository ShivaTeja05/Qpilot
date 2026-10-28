/**
 * The shell: the printed link, the needs-key screen, nothing leaving the machine, the rail
 * (every section reachable from Open → Recent → the rail), and the theme.
 */
import { demoSession, literal, route, workspaceView } from "./support/data";
import { E2E } from "./support/env";
import { App, expect, test } from "./support/fixtures";
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
    const bare = new App(await context.newPage(), test.info());
    bare.allowConsole(/401/);
    await bare.page.goto(`${E2E.origin}/`);
    await bare.settle();
    const main = bare.page.getByRole("main");
    await expect(
      main.getByRole("heading", { level: 1, name: /Open the link qPilot printed/ }),
    ).toBeVisible();
    // The screen is the whole page: no rail, no raw error code.
    await expect(bare.page.getByRole("navigation")).toHaveCount(0);
    await expect(bare.page.getByText(/no_token|\b401\b|Unauthorized/)).toHaveCount(0);
    await bare.axe("needs-key screen");
    await bare.shot("needs-key", "1440-light");
    expect(bare.outbound).toEqual([]);
    expect(bare.unexpectedConsole()).toEqual([]);
    await context.close();
  });
});

test.describe("the rail", () => {
  test("Open → Recent → every section is reachable from the rail", async ({ app, api }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    await app.open("/");
    // The rail's Recent list (outside a workspace) opens the demo.
    const rail = app.page.getByRole("complementary", { name: "Sections" });
    await rail
      .getByRole("link", { name: literal(demo.title) })
      .first()
      .click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toContain(`/${demo.key}/`);

    const nav = rail.getByRole("navigation", { name: "Workflow" });
    for (const s of SECTIONS.filter((x) => !x.hidden && !x.notInRail && x.scope === "workspace")) {
      if (s.sessionOnly && demo.kind !== "session") continue;
      const link = nav.getByRole("link", { name: new RegExp(`^${s.label}\\b`) });
      await link.click();
      await app.settle();
      expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(`#${route(demo, s.id)}`);
      await expect(link).toHaveAttribute("aria-current", "page");
      const main = app.page.getByRole("main", { name: s.label });
      await expect(main).toBeVisible();
      // Every state has a heading to navigate by (a locked section too).
      await expect.soft(main.getByRole("heading").first(), `${s.label}: a heading`).toBeVisible();
      // A locked section says why, in the rail's words and on the page.
      const locked = (await link.getAttribute("aria-label"))?.match(/locked: (.+)\)$/)?.[1];
      if (locked) await expect(main.getByText(/not open yet|stays hidden/).first()).toBeVisible();
      await app.axe(`rail → ${s.label}`);
    }
    await rail.getByRole("link", { name: /^Settings/ }).click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toBe("#/settings");
  });

  test("the rail says each confirmed stage in words", async ({ app, api }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    await app.open(route(demo, "results"));
    const nav = app.page.getByRole("navigation", { name: "Workflow" });
    for (const stage of view.stages.filter((s) => s.stage === "design" || s.stage === "curves")) {
      const link = nav.getByRole("link", { name: new RegExp(`^${stage.stage}\\b`, "i") });
      if (stage.confirmed) await expect(link).toHaveAccessibleName(/confirmed/);
      else await expect(link).not.toHaveAccessibleName(/confirmed/);
    }
  });

  test("on a phone the bottom bar reaches every section (More for the rest)", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    await app.page.setViewportSize({ width: 390, height: 844 });
    const demo = await demoSession(api);
    await app.open(route(demo, "results"));
    const bar = app.page.getByRole("navigation", { name: "Sections" });
    await expect(bar).toBeVisible();
    for (const s of SECTIONS.filter((x) => !x.hidden && !x.notInRail && x.scope === "workspace")) {
      const direct = bar.getByRole("link", { name: new RegExp(`^${s.label}\\b`) });
      if (await direct.count()) {
        await direct.click();
      } else {
        await bar.getByRole("button", { name: /^More/ }).click();
        const more = app.page.getByRole("dialog", { name: "More" });
        await app.axe("bottom bar, More open");
        await more.getByRole("button", { name: new RegExp(`^${s.label}\\b`) }).click();
      }
      await app.settle();
      expect(decodeURIComponent(new URL(app.page.url()).hash)).toBe(`#${route(demo, s.id)}`);
    }
  });

  test("the next-step banner names the workspace's next step", async ({ app, api }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    test.skip(!view.next_step, "the workspace has no next step");
    await app.open(route(demo, "record"));
    const banner = app.page.getByRole("region", { name: "Next step" });
    await expect(banner).toContainText(view.next_step!.title);
    if (view.next_step!.detail) await expect(banner).toContainText(view.next_step!.detail);
  });

  test("the top bar shows the study's title and the window title names the section", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    const demo = await demoSession(api);
    const view = await workspaceView(api, demo);
    await app.open(route(demo, "record"));
    await expect(app.page.getByRole("banner").getByText(view.title).first()).toBeVisible();
    await expect(app.page).toHaveTitle(`Record · ${view.title} — qPilot`);
  });

  test("an unknown study id says so in words, with a way out", async ({ app }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    app.allowConsole(/status of 404/);
    await app.open("/r/000000000000/results");
    await expect(
      app.page.getByText("This study was not found (it may have been moved or the link is old)"),
    ).toBeVisible();
    await app.axe("unknown study");
    await app.page.getByRole("button", { name: "Back to Open" }).click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toMatch(/^#\/?$/);
  });
});

test.describe("the theme", () => {
  test("the theme menu switches to dark and the choice survives a reload", async ({ app }) => {
    test.fixme(!LANDED.shellFrame, notLanded("shellFrame"));
    await app.open("/");
    const html = app.page.locator("html");
    for (const [word, value] of [
      ["Dark", "dark"],
      ["Light", "light"],
    ] as const) {
      await app.page.getByRole("button", { name: /^Theme:/ }).click();
      await app.page.getByRole("menuitem", { name: new RegExp(`^${word}`) }).click();
      await expect(html).toHaveAttribute("data-theme", value);
      await app.axe(`theme ${value}`);
      await app.page.reload();
      await app.settle();
      await expect(html).toHaveAttribute("data-theme", value);
    }
    await app.page.getByRole("button", { name: /^Theme:/ }).click();
    await app.page.getByRole("menuitem", { name: /^Same as the system/ }).click();
    await expect(html).toHaveAttribute("data-theme", "light"); // the emulated system theme
    expect(await app.page.evaluate(() => localStorage.getItem("qpilot.theme"))).toBeNull();
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

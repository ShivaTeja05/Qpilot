/**
 * Open (#/) and Settings (#/settings): what the page shows comes from /api/system, /api/workspaces
 * and /api/model of the server under test.
 */
import { literal, workspaces } from "./support/data";
import { expect, test } from "./support/fixtures";

interface SystemView {
  version: string;
  method: string;
  studies_dir: string;
  model: { reason: string; outbound: string };
  autonomy: string;
  policy: string[];
  never: string[];
}

test.describe("Open", () => {
  test("Recent lists every workspace in the store, the demo marked", async ({ app, api }) => {
    const all = await workspaces(api);
    await app.open("/");
    const recent = app.page.getByRole("main").getByRole("list", { name: "Recent" });
    await expect(recent.getByRole("listitem")).toHaveCount(all.length);
    for (const w of all) {
      const card = recent.getByRole("link", { name: literal(w.title) });
      await expect(card, `Recent card for "${w.title}"`).toBeVisible();
      if (w.is_demo) await expect(card).toContainText(/demo/i);
    }
    await app.axe("Open");
  });

  test("the system strip shows this server's version, method and outbound line", async ({
    app,
    api,
  }) => {
    const system = (await (await api.get("/api/system")).json()) as SystemView;
    await app.open("/");
    const strip = app.page.locator('footer[aria-label="This install"]');
    await expect(strip).toContainText(`qPilot ${system.version}`);
    await expect(strip).toContainText(system.method);
    await expect(strip).toContainText(system.model.outbound);
    for (const line of system.never) await expect(strip).toContainText(line);
  });

  test("a Recent card opens its workspace", async ({ app, api }) => {
    const [first] = await workspaces(api);
    test.skip(!first, "the store is empty");
    await app.open("/");
    const recent = app.page.getByRole("main").getByRole("list", { name: "Recent" });
    await recent.getByRole("link", { name: literal(first!.title) }).click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toContain(`/${first!.key}/`);
    await expect(app.page.getByRole("banner").getByText(first!.title).first()).toBeVisible();
  });

  test("keyboard only: Tab reaches a Recent card and Enter opens it", async ({ app, api }) => {
    const [first] = await workspaces(api);
    test.skip(!first, "the store is empty");
    await app.open("/");
    const card = app.page
      .getByRole("main")
      .getByRole("list", { name: "Recent" })
      .getByRole("link", { name: literal(first!.title) });
    for (let i = 0; i < 60; i++) {
      if (await card.evaluate((el) => el === document.activeElement)) break;
      await app.page.keyboard.press("Tab");
    }
    await expect(card, "reachable with Tab").toBeFocused();
    await app.page.keyboard.press("Enter");
    await app.settle();
    expect(new URL(app.page.url()).hash).toContain(`/${first!.key}/`);
  });
});

test.describe("Settings", () => {
  test("the model's status, the never-does lines and this install, from the server", async ({
    app,
    api,
  }) => {
    const system = (await (await api.get("/api/system")).json()) as SystemView;
    await app.open("/settings");
    await expect(app.page.getByRole("main").getByRole("heading", { level: 1 })).toHaveText(
      "Settings",
    );
    // The server's reason, as a sentence (capitalised) on the page.
    await expect(app.page.getByRole("region", { name: "Model" })).toContainText(
      literal(system.model.reason, "i"),
    );
    const never = app.page.getByRole("region", { name: "What qPilot never does" });
    for (const line of system.never) await expect(never).toContainText(line);
    await expect(never).toContainText(`qPilot ${system.version}`);
    await expect(never).toContainText(system.method);
    await expect(never).toContainText(system.studies_dir);
    await app.axe("Settings");
  });

  test("the autonomy shows the server's setting and its policy lines", async ({ app, api }) => {
    const system = (await (await api.get("/api/system")).json()) as SystemView;
    await app.open("/settings");
    const card = app.page.getByRole("region", { name: "What agents may do on their own" });
    const choice = app.page.getByRole("radiogroup", { name: "What agents may do on their own" });
    const title = system.autonomy === "suggest" ? "Suggest" : "Decide and tell me";
    await expect(choice.getByRole("radio", { name: title, exact: true })).toBeChecked();
    for (const line of system.policy) {
      // Each policy line is shown as its head (bold) and the rest: check the words, not markup.
      for (const part of line.split(/:\s*/)) await expect(card).toContainText(part.trim());
    }
  });

  test("the theme control switches the page to dark and back", async ({ app }) => {
    await app.open("/settings");
    const theme = app.page.getByRole("radiogroup", { name: "Theme" });
    await theme.getByRole("radio", { name: /dark/i }).click();
    await expect(app.page.locator("html")).toHaveAttribute("data-theme", "dark");
    await app.axe("Settings, dark");
    // Following the system again: the page shows the system's theme (light here).
    await theme.getByRole("radio", { name: /system/i }).click();
    await expect(app.page.locator("html")).toHaveAttribute("data-theme", "light");
    expect(await app.page.evaluate(() => localStorage.getItem("qpilot.theme"))).toBeNull();
  });
});

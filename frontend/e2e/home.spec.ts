/**
 * Open (#/) and Settings (#/settings): what the page shows comes from /api/system, /api/workspaces
 * and /api/model of the server under test.
 */
import { literal, workspaces } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

interface SystemView {
  version: string;
  method: string;
  model: { reason: string; outbound: string };
  autonomy: string;
  policy: string[];
  never: string[];
}

test.describe("Open", () => {
  test.beforeEach(() => test.fixme(!LANDED.home, notLanded("home")));

  test("Recent lists every workspace in the store, the demo marked", async ({ app, api }) => {
    const all = await workspaces(api);
    await app.open("/");
    for (const w of all) {
      const card = app.page.getByRole("link", { name: literal(w.title) }).first();
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
    await expect(app.page.getByText(system.version, { exact: false }).first()).toBeVisible();
    await expect(app.page.getByText(system.method, { exact: false }).first()).toBeVisible();
    await expect(app.page.getByText(system.model.outbound, { exact: false }).first()).toBeVisible();
  });

  test("a Recent card opens its workspace", async ({ app, api }) => {
    const [first] = await workspaces(api);
    test.skip(!first, "the store is empty");
    await app.open("/");
    await app.page
      .getByRole("link", { name: literal(first!.title) })
      .first()
      .click();
    await app.settle();
    expect(new URL(app.page.url()).hash).toContain(`/${first!.key}/`);
    await expect(app.page.getByText(first!.title).first()).toBeVisible();
  });

  test("keyboard only: Tab reaches a Recent card and Enter opens it", async ({ app, api }) => {
    const [first] = await workspaces(api);
    test.skip(!first, "the store is empty");
    await app.open("/");
    const card = app.page.getByRole("link", { name: literal(first!.title) }).first();
    for (let i = 0; i < 40 && !(await card.evaluate((el) => el === document.activeElement)); i++) {
      await app.page.keyboard.press("Tab");
    }
    await expect(card, "reachable with Tab").toBeFocused();
    await app.page.keyboard.press("Enter");
    await app.settle();
    expect(new URL(app.page.url()).hash).toContain(`/${first!.key}/`);
  });
});

test.describe("Settings", () => {
  test.beforeEach(() => test.fixme(!LANDED.settings, notLanded("settings")));

  test("shows the model's status in words, the autonomy and the never-does lines", async ({
    app,
    api,
  }) => {
    const system = (await (await api.get("/api/system")).json()) as SystemView;
    await app.open("/settings");
    await expect(app.page.getByText(system.model.reason, { exact: false }).first()).toBeVisible();
    for (const line of system.never) await expect(app.page.getByText(line).first()).toBeVisible();
    await expect(app.page.getByText(system.version, { exact: false }).first()).toBeVisible();
    await app.axe("Settings");
  });

  test("the autonomy switch shows the server's setting", async ({ app, api }) => {
    const system = (await (await api.get("/api/system")).json()) as SystemView;
    await app.open("/settings");
    const label = system.autonomy === "suggest" ? /suggest/i : /decide and tell me/i;
    await expect(app.page.getByRole("radio", { name: label }).first()).toBeChecked();
  });
});

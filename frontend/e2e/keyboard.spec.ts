/**
 * Keyboard-only paths (docs/app.md §5, Keyboard): ⌘K palette, `?` shortcut sheet, g then a
 * letter for a section, ⌘J the Ask drawer, and a visible focus ring on every Tab stop.
 */
import { demoSession, route } from "./support/data";
import { expect, test } from "./support/fixtures";
import { LANDED, notLanded } from "./support/sections";

const MOD = process.platform === "darwin" ? "Meta" : "Control";

test.describe("keyboard", () => {
  test.beforeEach(() => test.fixme(!LANDED.shellKeys, notLanded("shellKeys")));

  test("⌘K opens the palette; typing a section and Enter goes there", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await app.page.keyboard.press(`${MOD}+k`);
    const palette = app.page.getByRole("dialog");
    await expect(palette).toBeVisible();
    await expect(
      palette.getByRole("combobox").or(palette.getByRole("textbox")).first(),
    ).toBeFocused();
    await app.axe("command palette");
    await app.page.keyboard.type("Results");
    await app.page.keyboard.press("Enter");
    await app.settle();
    expect(new URL(app.page.url()).hash).toBe(`#${route(demo, "results")}`);
    await expect(palette).toBeHidden();
  });

  test("? shows the shortcut sheet; Escape closes it and focus returns", async ({ app }) => {
    await app.open("/");
    await app.page.locator("body").press("?");
    const sheet = app.page.getByRole("dialog", { name: /shortcut|keyboard/i });
    await expect(sheet).toBeVisible();
    await expect(
      sheet
        .getByText("⌘K")
        .or(sheet.getByText(/ctrl\s*k/i))
        .first(),
    ).toBeVisible();
    await app.axe("shortcut sheet");
    await app.page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });

  test("g then r / e / a goes to Results / Record / Audit", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "agents"));
    for (const [key, section] of [
      ["r", "results"],
      ["e", "record"],
      ["a", "audit"],
    ] as const) {
      await app.page.locator("body").press("g");
      await app.page.locator("body").press(key);
      await app.settle();
      expect(new URL(app.page.url()).hash).toBe(`#${route(demo, section)}`);
    }
  });

  test("⌘J opens the Ask drawer with its question box focused", async ({ app, api }) => {
    test.fixme(!LANDED.askDrawer, notLanded("askDrawer"));
    const demo = await demoSession(api);
    await app.open(route(demo, "results"));
    await app.page.keyboard.press(`${MOD}+j`);
    const drawer = app.page.getByRole("dialog", { name: /ask/i });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("textbox").first()).toBeFocused();
    await app.axe("Ask drawer");
    await app.page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  });

  test("every Tab stop on Results shows a focus ring", async ({ app, api }) => {
    test.fixme(!LANDED.results, notLanded("results"));
    const demo = await demoSession(api);
    await app.open(route(demo, "results"));
    const missing: string[] = [];
    for (let i = 0; i < 30; i++) {
      await app.page.keyboard.press("Tab");
      const ring = await app.page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const visible =
          (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
        return visible
          ? ""
          : `${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 40)}"`;
      });
      if (ring) missing.push(ring);
    }
    expect(missing, "Tab stops without a visible focus ring").toEqual([]);
  });
});

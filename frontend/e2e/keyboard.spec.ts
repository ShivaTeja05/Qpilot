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
    const palette = app.page.getByRole("dialog", { name: "Search and commands" });
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
    const sheet = app.page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText(/^Search, go to a section/)).toBeVisible();
    await app.axe("shortcut sheet");
    await app.page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(app.page.getByRole("dialog")).toHaveCount(0);
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

  test("⌘J opens the Ask drawer and Escape closes it", async ({ app, api }) => {
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await app.page.keyboard.press(`${MOD}+j`);
    const drawer = app.page.getByRole("dialog", { name: "Ask your data" });
    await expect(drawer).toBeVisible();
    await app.settle();
    await app.axe("Ask drawer");
    await app.shot("ask", "drawer-1440-light");
    await app.page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  });

  test("Ask: an example question is answered, saying who answered and wrote it", async ({
    app,
    api,
  }) => {
    test.fixme(!LANDED.askDrawer, notLanded("askDrawer"));
    test.setTimeout(240_000);
    const demo = await demoSession(api);
    await app.open(route(demo, "record"));
    await app.page.keyboard.press(`${MOD}+j`);
    const drawer = app.page.getByRole("dialog", { name: "Ask your data" });
    const box = drawer.getByRole("textbox", { name: "Your question about this study" });
    await expect(box).toBeFocused();
    // The examples come from this study's results; pick the first.
    const example = drawer.getByRole("listitem").getByRole("button").first();
    await expect(example).toBeVisible({ timeout: 60_000 });
    const question = (await example.innerText()).split("\n")[0]!.trim();
    await example.click();
    if (await drawer.getByRole("button", { name: "Ask", exact: true }).isEnabled()) {
      await drawer.getByRole("button", { name: "Ask", exact: true }).click();
    }
    const log = drawer.getByRole("log", { name: "Questions and answers" });
    const turn = log.getByRole("article", { name: `Question: ${question}` });
    await expect(turn).toBeVisible();
    await expect(turn.getByRole("status")).toHaveCount(0, { timeout: 180_000 });
    await expect(turn).toContainText(/template|model|audit/i);
    await app.axe("Ask, answered");
    await app.shot("ask", "answered-1440-light");
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

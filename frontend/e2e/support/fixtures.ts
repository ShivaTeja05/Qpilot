/**
 * The test fixtures every spec uses:
 *
 * * `api`: the real API of the server under test, with the launch key. Tests read what the page
 *   must show from here (gene names, proposal counts, …); nothing is ever hand-written.
 * * `app`: the page, opened through the printed link, with `settle()`, `axe()`, `shot()` and
 *   `noSideScroll()`. It records console errors, uncaught errors and every request that leaves
 *   this server; a test fails on any of them (docs/app.md §1.5: nothing leaves the machine).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import {
  test as base,
  expect,
  type APIRequestContext,
  type Page,
  type Request,
  type TestInfo,
} from "@playwright/test";
import { E2E } from "./env";

/** axe rule sets: WCAG 2.2 A and AA (docs/app.md §5, Accessibility). */
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
/** Impacts that fail a test; moderate and minor ones are attached to the report. */
const FAILING_IMPACTS = new Set(["serious", "critical"]);

export interface AxeFinding {
  id: string;
  impact: string;
  help: string;
  /** Up to eight offending elements: selector, markup and axe's reason (colours, ratio, …). */
  nodes: { target: string; html: string; why: string }[];
}

export class App {
  readonly consoleErrors: string[] = [];
  readonly outbound: string[] = [];
  /** Responses with a 4xx/5xx status, as "404 GET http://…". */
  readonly failedResponses: string[] = [];
  /** 409 "loading" answers seen (the browser logs each as a failed load). */
  private expectedFailures = 0;
  private allowedConsole: RegExp[] = [];
  private inflight = new Set<Request>();
  private keyed = false;

  constructor(
    readonly page: Page,
    private readonly info: TestInfo,
  ) {
    page.on("console", (msg) => {
      if (msg.type() === "error") this.consoleErrors.push(msg.text());
    });
    page.on("pageerror", (error) => this.consoleErrors.push(`uncaught: ${error.message}`));
    // A failed load shows in the console without its address: record which request it was.
    page.on("response", (res) => {
      if (res.status() < 400) return;
      const what = `${res.status()} ${res.request().method()} ${res.url()}`;
      if (res.status() === 409) {
        // 409 "loading" is the API's "a job is preparing this view, ask again": expected.
        void res
          .json()
          .then((b: { error?: { code?: string } }) => {
            if (b?.error?.code === "loading") this.expectedFailures += 1;
            else this.failedResponses.push(what);
          })
          .catch(() => this.failedResponses.push(what));
        return;
      }
      this.failedResponses.push(what);
    });
    page.on("request", (req) => {
      const url = req.url();
      if (!url.startsWith(E2E.origin) && !url.startsWith("data:") && !url.startsWith("blob:")) {
        this.outbound.push(`${req.method()} ${url}`);
      }
      if (!url.includes("/api/events")) this.inflight.add(req);
    });
    const done = (req: Request) => this.inflight.delete(req);
    page.on("requestfinished", done);
    page.on("requestfailed", done);
  }

  /** Expect these console errors (e.g. the 401 of the needs-key screen). */
  allowConsole(...patterns: RegExp[]): void {
    this.allowedConsole.push(...patterns);
  }

  /** Console errors not allowed by {@link allowConsole}. */
  unexpectedConsole(): string[] {
    let loading = this.expectedFailures;
    return this.consoleErrors.filter((t) => {
      if (this.allowedConsole.some((p) => p.test(t))) return false;
      if (loading > 0 && /status of 409/.test(t)) {
        loading -= 1;
        return false;
      }
      return true;
    });
  }

  /**
   * Open the page at a hash route (`/`, `/settings`, `/s/<key>/results`). The first call in a
   * test opens the printed link, which sets the launch cookie and drops the key from the address.
   */
  async open(route = "/"): Promise<void> {
    if (!this.keyed) {
      await this.page.goto(E2E.link);
      this.keyed = true;
    }
    if (route !== "/" || !this.page.url().endsWith("/")) {
      await this.page.goto(`${E2E.origin}/#${route}`);
    }
    await this.settle();
  }

  /**
   * Wait until the page has nothing loading: no request in flight (the event stream aside), no
   * skeleton, fonts loaded, two frames painted.
   */
  async settle(timeout = 20_000): Promise<void> {
    const until = Date.now() + timeout;
    let quietSince = 0;
    while (Date.now() < until) {
      const loading = await this.page
        .locator(".qp-skeleton, [role=status]:has(.qp-skeleton)")
        .count()
        .catch(() => 0);
      if (this.inflight.size === 0 && loading === 0) {
        if (!quietSince) quietSince = Date.now();
        if (Date.now() - quietSince >= 300) break;
      } else {
        quietSince = 0;
      }
      await this.page.waitForTimeout(50);
    }
    await this.page.evaluate(async () => {
      await document.fonts.ready;
      // Let transitions and animations finish (a sheet sliding in, a theme fading): axe reads
      // colours as painted, so a half-faded layer is not a contrast problem of the page.
      const until = Date.now() + 3000;
      while (
        Date.now() < until &&
        document.getAnimations().some((a) => a.playState === "running")
      ) {
        await new Promise((r) => setTimeout(r, 50));
      }
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    });
  }

  /**
   * Check the current page state with axe. Serious and critical violations fail the test (soft:
   * the test goes on so every state gets checked); all findings are attached to the report.
   */
  async axe(state: string): Promise<AxeFinding[]> {
    await this.settle();
    const results = await new AxeBuilder({ page: this.page }).withTags(AXE_TAGS).analyze();
    const findings: AxeFinding[] = results.violations.map((v) => ({
      id: v.id,
      impact: v.impact ?? "unknown",
      help: v.help,
      nodes: v.nodes.slice(0, 8).map((n) => ({
        target: n.target.join(" "),
        html: n.html.slice(0, 200),
        why: [...n.any, ...n.all, ...n.none].map((c) => c.message).join(" / "),
      })),
    }));
    if (findings.length) {
      const body = JSON.stringify({ state, url: this.page.url(), findings }, null, 2);
      await this.info.attach(`axe-${slug(state)}.json`, { body, contentType: "application/json" });
      // One file per state, for the owners (gitignored with the screenshots).
      const path = join(E2E.screenshotDir, "axe", `${slug(state)}.json`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, body);
    }
    const failing = findings.filter((f) => FAILING_IMPACTS.has(f.impact));
    expect
      .soft(failing.length, `axe (serious/critical) on ${state}:\n${formatAxe(failing)}`)
      .toBe(0);
    return findings;
  }

  /** Save a full-page screenshot under e2e/screenshots/<group>/<name>.png (gitignored). */
  async shot(group: string, name: string): Promise<string> {
    const path = join(E2E.screenshotDir, slug(group), `${slug(name)}.png`);
    mkdirSync(dirname(path), { recursive: true });
    await this.page.screenshot({ path, fullPage: true, animations: "disabled" });
    return path;
  }

  /** The page itself never scrolls sideways (plate maps scroll inside their own box). */
  async noSideScroll(state: string): Promise<void> {
    const { scroll, client } = await this.page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect
      .soft(scroll, `${state}: the page scrolls sideways (${scroll} px wide in ${client} px)`)
      .toBeLessThanOrEqual(client + 1);
  }
}

export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export function formatAxe(findings: AxeFinding[]): string {
  return findings
    .map(
      (f) =>
        `  [${f.impact}] ${f.id}: ${f.help}\n` +
        f.nodes.map((n) => `      ${n.target}\n        ${n.why}`).join("\n"),
    )
    .join("\n");
}

export const test = base.extend<{ api: APIRequestContext; app: App }>({
  api: async ({ playwright }, provide) => {
    const ctx = await playwright.request.newContext({
      baseURL: E2E.origin,
      extraHTTPHeaders: { "x-qpilot-token": E2E.token },
    });
    await provide(ctx);
    await ctx.dispose();
  },
  app: async ({ page }, provide, info) => {
    const app = new App(page, info);
    await provide(app);
    expect(app.outbound, "requests that left this machine").toEqual([]);
    expect(
      app.unexpectedConsole(),
      `console errors (failed responses: ${app.failedResponses.join(", ") || "none"})`,
    ).toEqual([]);
  },
});

export { expect };

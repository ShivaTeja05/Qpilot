/**
 * End-to-end tests of the one page (frontend/e2e). They start nothing: they run against a
 * `qpilot app` that is already serving the built page over a real study store.
 *
 *   E2E_URL   the link qPilot printed (default http://127.0.0.1:$APP_PORT/?token=qpilot-dev)
 *
 * See e2e/README.md for the run (fresh store copy, build, server, `npm run e2e`).
 */
import { defineConfig, devices } from "@playwright/test";
import { E2E } from "./e2e/support/env";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  globalSetup: "./e2e/support/global-setup.ts",
  // One server, one store: a few workers at most, so slow jobs keep their usual timings.
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : 3,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: E2E.origin,
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
    locale: "en-GB",
    timezoneId: "Europe/London",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  projects: [{ name: "chromium" }],
});

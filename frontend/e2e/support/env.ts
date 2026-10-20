/**
 * Where the page under test is. `E2E_URL` is the link `qpilot app` printed (it carries the
 * launch key as `?token=`); without it, this agent's own server on `$APP_PORT` with the fixed
 * dev key.
 */
const DEFAULT_PORT = process.env.APP_PORT ?? "7860";
const raw =
  process.env.E2E_URL ??
  `http://127.0.0.1:${DEFAULT_PORT}/?token=${process.env.QPILOT_APP_TOKEN ?? "qpilot-dev"}`;
const url = new URL(raw);

export const E2E = {
  /** The link as given (opening it sets the launch cookie). */
  link: url.toString(),
  /** `http://127.0.0.1:7888` */
  origin: url.origin,
  /** The launch key, sent as `x-qpilot-token` by the API fixture. */
  token: url.searchParams.get("token") ?? process.env.QPILOT_APP_TOKEN ?? "",
  /** Writing tests (decide + undo, exports, jobs) are skipped when set. */
  readOnly: process.env.E2E_READONLY === "1",
  /** Where screenshots go (gitignored). */
  screenshotDir: process.env.E2E_SCREENSHOTS ?? "e2e/screenshots",
};

/** The widths every section is checked at (docs/app.md §5, Responsive). */
export const WIDTHS = [1440, 1024, 768, 390] as const;
export type Width = (typeof WIDTHS)[number];

export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

/** A viewport height that looks like a real window at each width. */
export function viewportFor(width: Width): { width: number; height: number } {
  return { width, height: width >= 1024 ? 900 : width >= 768 ? 1024 : 844 };
}

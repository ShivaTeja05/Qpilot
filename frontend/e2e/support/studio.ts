/**
 * Walking a Studio session through the page as a person does: open files on Open, wait for the
 * jobs, decide what waits in a stage, confirm it. Shared by the walk of the demo and the specs
 * that open a lab's own files (tests/fixtures/corpus).
 */
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { APIRequestContext } from "@playwright/test";
import type { components } from "../../src/api/schema";
import { proposals, workspaces, type Workspace } from "./data";
import { expect, type App } from "./fixtures";

type S = components["schemas"];

/** The repository's real lab files (each folder has a MANIFEST.yaml with its source). */
export const CORPUS = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "tests",
  "fixtures",
  "corpus",
);

/** The workspace opened from a file of this name, if the store has one. */
export async function sessionOf(
  api: APIRequestContext,
  fileName: string,
): Promise<Workspace | undefined> {
  return (await workspaces(api)).find((w) => w.kind === "session" && w.file_name === fileName);
}

/** Wait until the session has no job running (a proposal job fills the inbox as it goes). */
export async function jobsDone(api: APIRequestContext, sid: string): Promise<void> {
  await expect
    .poll(
      async () => {
        const res = await api.get(`/api/sessions/${sid}`, { timeout: 60_000 });
        const frame = (await res.json()) as { active_jobs?: unknown[] };
        return frame.active_jobs?.length ?? 0;
      },
      { timeout: 600_000, intervals: [1000, 2000] },
    )
    .toBe(0);
}

/**
 * Open files on Open as a person does (choose them, then Open), and wait for the session's first
 * section. Returns the session id.
 */
export async function openFiles(app: App, files: string[], sheet?: string): Promise<string> {
  await app.open("/");
  const page = app.page;
  await page.locator("input[type=file][multiple]").setInputFiles(files);
  if (sheet) {
    await page.locator("input[type=file]:not([multiple])").first().setInputFiles(sheet);
  }
  await page
    .getByRole("main")
    .getByRole("button", { name: /^Open( this file| these files)?$/ })
    .click();
  await page.waitForURL(/#\/s\/[0-9a-f]{12}\//, { timeout: 300_000 });
  await app.settle(120_000);
  return new URL(page.url()).hash.split("/")[2]!;
}

/**
 * Go to a section of a session (the hash route) and let it settle; the first page of a test
 * opens the printed link first (it sets the launch cookie).
 */
export async function goTo(app: App, sid: string, section: string, rest = ""): Promise<void> {
  await app.open(`/s/${sid}/${section}${rest}`);
  await app.settle(120_000);
}

/**
 * Decide every waiting proposal of the stage: accept what the engine finds consistent (one
 * reason for all of them), reject what it contradicts, then the rest one by one, as the walk of
 * the demo does. Then confirm the stage.
 */
export async function reviewStage(
  app: App,
  api: APIRequestContext,
  sid: string,
  stage: "design" | "curves",
  reason: string,
): Promise<void> {
  const page = app.page;
  const bulk = async (button: RegExp, go: RegExp) => {
    const open = page.getByRole("main").getByRole("button", { name: button });
    if (!(await open.count()) || (await open.isDisabled())) return;
    await open.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // The dialog lists exactly what it will do; wait for that list (a non-zero count).
    const goButton = dialog.getByRole("button", { name: go });
    const nothing = dialog.getByText(/^No waiting proposal/);
    await expect(goButton.or(nothing).first()).toBeVisible({ timeout: 120_000 });
    if (!(await goButton.count())) {
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      return;
    }
    const why = dialog.getByRole("textbox", { name: "One reason for all of them" });
    if (await why.count()) await why.fill(reason);
    await app.axe(`${stage}, bulk dialog`);
    await expect(goButton).toBeEnabled({ timeout: 60_000 });
    await goButton.click();
    await expect(dialog).toBeHidden({ timeout: 300_000 });
    await app.settle(120_000);
  };
  await bulk(/^Accept all consistent/, /^Accept these [1-9]/);
  await bulk(/^Reject contradicted AI calls/, /^Reject these [1-9]/);

  // What is left one by one: contradicted → Reject, the rest → Accept (with a reason).
  const waiting = page.getByRole("list", { name: /proposals waiting for you$/ });
  for (let i = 0; i < 60 && (await waiting.count()); i++) {
    const card = waiting.getByRole("article").first();
    const contradicted = (await card.getByRole("button", { name: "Accept anyway…" }).count()) > 0;
    if (contradicted) {
      await card.getByRole("button", { name: "Reject…" }).click();
      await card.getByRole("textbox", { name: /Why do you reject it/ }).fill(reason);
      await card.getByRole("button", { name: "Reject", exact: true }).click();
    } else {
      await card.getByRole("button", { name: /^Accept(…)?$/ }).click();
      const why = card.getByRole("textbox", { name: /Why you accept it/ });
      if (await why.count()) {
        await why.fill(reason);
        await card.getByRole("button", { name: "Accept", exact: true }).click();
      }
    }
    await app.settle(60_000);
  }
  await expect(page.getByText("Nothing is waiting in this stage")).toBeVisible({ timeout: 60_000 });
  // …and the server agrees.
  const waitingOnServer = async () =>
    (await proposals(api, sid, stage)).proposals.filter((p) => p.status === "proposed").length;
  await expect.poll(waitingOnServer, { timeout: 60_000 }).toBe(0);
  await confirmStage(app, stage);
}

/** Confirm a stage through its dialog (it shows what it covers first). */
export async function confirmStage(app: App, stage: "design" | "curves"): Promise<void> {
  const page = app.page;
  await page
    .getByRole("main")
    .getByRole("button", { name: /^(Confirm this stage|Review the confirm step)…$/ })
    .first()
    .click();
  const confirm = page.getByRole("dialog", { name: `Confirm the ${stage}` });
  await expect(confirm).toBeVisible();
  await app.axe(`${stage}, confirm dialog`);
  await confirm.getByRole("button", { name: "Yes, confirm" }).click();
  await expect(confirm).toBeHidden({ timeout: 300_000 });
  await app.settle(120_000);
}

/** A study's results, once the analysis the confirm started is done. */
export async function resultsOf(
  api: APIRequestContext,
  studyId: string,
): Promise<S["ResultsView"]> {
  const res = await api.get(`/api/studies/${studyId}/results`, { timeout: 300_000 });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()) as S["ResultsView"];
}

/** The session's current study, once results are visible (the analysis may take a moment). */
export async function studyOf(api: APIRequestContext, sid: string): Promise<string> {
  let study: string | null | undefined = null;
  await expect
    .poll(
      async () => {
        const frame = (await (await api.get(`/api/sessions/${sid}`)).json()) as S["WorkspaceView"];
        study = frame.results_visible ? frame.study_id : null;
        return Boolean(study);
      },
      { timeout: 600_000, intervals: [1000, 2000] },
    )
    .toBe(true);
  return study!;
}

/**
 * GET a JSON view that a job may be preparing (`409 loading` / `503 warming`): follow its job,
 * ask again. The page does the same with `Prefer: respond-async` (it sees 202).
 */
export async function settledJson<T>(api: APIRequestContext, path: string): Promise<T> {
  for (let i = 0; i < 200; i++) {
    const res = await api.get(path, { timeout: 300_000 });
    if (res.status() === 200) return (await res.json()) as T;
    const body = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; details?: { job?: { id?: string } } };
    };
    const code = body.error?.code;
    expect(
      [409, 503].includes(res.status()) && (code === "loading" || code === "warming"),
      `GET ${path}: ${res.status()} ${JSON.stringify(body)}`,
    ).toBe(true);
    const job = body.error?.details?.job?.id;
    if (job) {
      await expect
        .poll(
          async () =>
            ((await (await api.get(`/api/jobs/${job}`)).json()) as { status: string }).status,
          { timeout: 600_000, intervals: [500, 1000, 2000] },
        )
        .toMatch(/^(done|failed)$/);
    } else {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  throw new Error(`GET ${path}: still being prepared`);
}

/** Run e2e/support/files.py (the venv's python3 -I: openpyxl, lxml) and parse its JSON. */
export function checkFile<T>(command: string, ...args: string[]): T {
  const script = join(dirname(fileURLToPath(import.meta.url)), "files.py");
  const out = execFileSync(
    process.env.QPILOT_PYTHON ?? "python3",
    ["-I", script, command, ...args],
    {
      encoding: "utf8",
    },
  );
  return JSON.parse(out) as T;
}

/**
 * Click a link that downloads a file and save it; returns its path and the name the server gave
 * it. The link must download (not navigate): `Content-Disposition: attachment`.
 */
export async function download(
  app: App,
  link: import("@playwright/test").Locator,
  dir: string,
): Promise<{ path: string; name: string }> {
  const [file] = await Promise.all([app.page.waitForEvent("download"), link.click()]);
  const name = file.suggestedFilename();
  const path = join(dir, name);
  await file.saveAs(path);
  expect(await file.failure()).toBeNull();
  return { path, name };
}

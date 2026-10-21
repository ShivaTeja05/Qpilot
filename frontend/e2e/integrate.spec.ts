/**
 * origin/main's features on the one page (INTEGRATION.md): the Evidence Ledger on Results, Where
 * to look and Decide… in Trace, the Run Review sign-off in Report, the Sheet check and the
 * Instruments sections. What the page must show is read from the server's API; the two files a
 * test needs (an analysis sheet, an agent's proposed incident) are made by the engine's own
 * helpers through Python (QPILOT_PYTHON, default python3, with the repository on PYTHONPATH).
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { APIRequestContext } from "@playwright/test";
import { demoSession, literal, route, type Workspace } from "./support/data";
import { E2E } from "./support/env";
import { expect, test } from "./support/fixtures";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

interface Fact {
  plain: string;
}
interface Evidence {
  available: boolean;
  items: { id: string; title: string; status_word: string; cannot_tell: boolean }[];
}
interface WherePlace {
  rank: number;
  sample: string;
  can_decide: boolean;
  card_id: string;
}
interface Where {
  head: string;
  places: WherePlace[];
  text: Fact[];
}
interface Review {
  head: string;
  outcomes: { id: string; label: string }[];
  sign_offs: { reviewer: string }[];
}

async function getJson<T>(api: APIRequestContext, path: string, tries = 20): Promise<T> {
  for (let i = 0; ; i += 1) {
    const res = await api.get(path, { timeout: 110_000 });
    if (res.status() === 409 && i < tries) {
      const body = (await res.json()) as { error?: { code?: string } };
      if (body.error?.code === "loading") {
        await new Promise((r) => setTimeout(r, 1500)); // Trace reads the wells once (a job)
        continue;
      }
    }
    expect(res.status(), `GET ${path}`).toBe(200);
    return (await res.json()) as T;
  }
}

/** Run a few lines of Python from the repository (the engine's own helpers), with arguments. */
function python(code: string, ...args: string[]): string {
  return execFileSync(process.env.QPILOT_PYTHON ?? "python3", ["-c", code, ...args], {
    cwd: REPO,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: REPO },
  });
}

/** A gene whose Where to look has a place to decide, read from the API (none: skip). */
async function decidableGene(
  api: APIRequestContext,
  demo: Workspace,
): Promise<{ gene: string; where: Where } | null> {
  const results = await getJson<{ genes: { gene: string; conclusion: string }[] }>(
    api,
    `/api/studies/${demo.study_id}/results`,
  );
  const genes = [...results.genes].sort(
    (a, b) => Number(a.conclusion !== "none") - Number(b.conclusion !== "none"),
  );
  for (const { gene } of genes.slice(0, 30)) {
    const where = await getJson<Where>(
      api,
      `/api/studies/${demo.study_id}/where-to-look?gene=${encodeURIComponent(gene)}`,
    );
    if (where.places.some((p) => p.can_decide)) return { gene, where };
  }
  return null;
}

test.describe("Results: what this study cannot tell you", () => {
  test("every ledger item is shown, the ones it cannot tell first", async ({ app, api }) => {
    const demo = await demoSession(api);
    const ledger = await getJson<Evidence>(api, `/api/studies/${demo.study_id}/evidence`);
    await app.open(route(demo, "results"));
    const cannot = app.page.getByRole("list", { name: "What this study cannot tell you" });
    if (!ledger.available) {
      await expect(app.page.getByText(/not available for this study/).first()).toBeVisible();
      return;
    }
    for (const item of ledger.items.filter((i) => i.cannot_tell))
      await expect(cannot).toContainText(item.title);
    await app.axe("results evidence");
  });
});

test.describe("Trace: where to look and Decide…", () => {
  test("a gene's places come from the API, and Decide… opens the card on Results", async ({
    app,
    api,
  }) => {
    const demo = await demoSession(api);
    const found = await decidableGene(api, demo);
    test.skip(!found, "no gene of this study has a place whose option changes a call");
    const { gene, where } = found!;
    await app.open(route(demo, "trace", gene));
    const places = app.page.getByRole("list", { name: "Places to look" });
    await expect(places).toBeVisible({ timeout: 60_000 });
    const place = where.places.find((p) => p.can_decide)!;
    await expect(places).toContainText(place.sample);
    await app.axe("trace where to look");
    test.skip(E2E.readOnly, "E2E_READONLY: Decide… writes to the store");
    await places
      .getByRole("button", { name: /^Decide/ })
      .first()
      .click();
    await app.page.getByRole("button", { name: "Go to the card" }).click();
    await expect(app.page.getByText("Opened from Trace").first()).toBeVisible();
    const cards = await getJson<{ cards: { card: { id: string } }[] }>(
      api,
      `/api/studies/${demo.study_id}/cards`,
    );
    expect(cards.cards.map((c) => c.card.id)).toContain(place.card_id);
  });
});

test.describe("Report: the Run Review", () => {
  test("a person signs off; the chain names it", async ({ app, api }) => {
    const demo = await demoSession(api);
    const review = await getJson<Review>(api, `/api/studies/${demo.study_id}/review`);
    await app.open(route(demo, "report"));
    for (const o of review.outcomes)
      await expect(app.page.getByText(literal(o.label)).first()).toBeVisible();
    await expect(app.page.getByRole("button", { name: "Sign off" })).toBeDisabled();
    await app.axe("report run review");
    test.skip(E2E.readOnly, "E2E_READONLY: a sign-off writes to the store");
    await app.page.getByText(literal(review.outcomes[2]!.label)).first().click();
    await app.page.getByLabel("Comment").fill("Checked by the end-to-end test.");
    await app.page.getByLabel("Your name").fill("e2e");
    await app.page.getByRole("button", { name: "Sign off" }).click();
    await expect(app.page.getByText(/^Signed off/).first()).toBeVisible();
    const after = await getJson<Review>(api, `/api/studies/${demo.study_id}/review`);
    expect(after.sign_offs.map((s) => s.reviewer)).toContain("e2e");
    const chain = await getJson<{ entries: { card_title: string }[] }>(
      api,
      `/api/studies/${demo.study_id}/decisions`,
    );
    expect(chain.entries.at(-1)?.card_title).toBe("Run Review sign-off");
  });
});

test.describe("Sheet check", () => {
  test("a sheet is recomputed; the mapping is a guess until confirmed", async ({ app }) => {
    await app.open("/sheetcheck");
    await expect(app.page.getByRole("heading", { level: 1 })).toHaveText("Sheet check");
    await app.axe("sheet check empty");
    const dir = mkdtempSync(join(tmpdir(), "qpilot-e2e-sheet-"));
    try {
      python(
        "import sys; from pathlib import Path; from tests.engine.test_sheetcheck import clean_sheet;" +
          " clean_sheet(Path(sys.argv[1]))",
        dir,
      );
    } catch (err) {
      test.skip(true, `no Python to build a sheet: ${String(err).slice(0, 120)}`);
    }
    await app.page.locator('input[type="file"]').setInputFiles(join(dir, "clean.csv"));
    await expect(app.page.getByText(/mapping guessed, not confirmed/).first()).toBeVisible();
    await expect(app.page.getByRole("heading", { name: "What the check found" })).toBeVisible();
    await app.axe("sheet check guessed");
    await app.page.getByRole("button", { name: "Confirm this mapping" }).click();
    await expect(app.page.getByText(/mapping confirmed/).first()).toBeVisible();
  });
});

test.describe("Instruments", () => {
  test("a person registers an instrument and decides an agent's incident", async ({ app, api }) => {
    await app.open("/instruments");
    await expect(app.page.getByRole("heading", { level: 1 })).toHaveText("Instruments");
    await app.axe("instruments list");
    test.skip(E2E.readOnly, "E2E_READONLY: registering writes to the registry");
    const name = `e2e cycler ${Date.now()}`;
    await app.page.getByRole("button", { name: "Register an instrument" }).first().click();
    await app.page.getByLabel("Name").fill(name);
    await app.page
      .getByRole("dialog")
      .getByRole("button", { name: /Register/ })
      .click();
    const listed = await getJson<{
      instruments: { instrument_id: string; display_name: string }[];
    }>(api, "/api/instruments");
    const inst = listed.instruments.find((i) => i.display_name === name);
    expect(inst, "the instrument is registered").toBeTruthy();
    const store = process.env.QPILOT_STUDIES_DIR;
    test.skip(!store, "QPILOT_STUDIES_DIR is not set: no agent proposal can be made");
    python(
      "import sys; from pathlib import Path; from qpilot.core.instruments import Registry, log_incident;" +
        " r = Registry(Path(sys.argv[1]) / 'instruments');" +
        " log_incident(r.logbook(sys.argv[2]), actor='agent', wells=['B3']," +
        " signature={'metric': 'plateau', 'direction': 'low'})",
      store!,
      inst!.instrument_id,
    );
    await app.open(`/instruments/${inst!.instrument_id}`);
    await app.page
      .getByRole("button", { name: /^Confirm the incident/ })
      .first()
      .click();
    await expect
      .poll(async () => {
        const view = await getJson<{ incidents: { status: string; actor: string }[] }>(
          api,
          `/api/instruments/${inst!.instrument_id}`,
        );
        return view.incidents.map((i) => i.status);
      })
      .toContain("confirmed");
    await app.axe("instruments one");
  });
});

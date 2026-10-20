/**
 * Before any test: the server must be answering with the built page, over a store that is not
 * the shared seed (writing tests decide and undo cards). Fails in plain words otherwise.
 */
import { rmSync } from "node:fs";
import { join } from "node:path";
import { E2E } from "./env";

interface SystemView {
  version: string;
  studies_dir: string;
}

export default async function globalSetup(): Promise<void> {
  let system: SystemView;
  try {
    const res = await fetch(`${E2E.origin}/api/system`, {
      headers: { "x-qpilot-token": E2E.token },
    });
    if (res.status === 401) {
      throw new Error(
        `The server at ${E2E.origin} refused the key in E2E_URL (401). Use the link it printed.`,
      );
    }
    if (!res.ok) throw new Error(`GET /api/system answered ${res.status}.`);
    system = (await res.json()) as SystemView;
  } catch (error) {
    throw new Error(
      `No qpilot app answering at ${E2E.origin} (${(error as Error).message}).\n` +
        "Start it first (tests start nothing): see frontend/e2e/README.md.",
    );
  }

  const page = await fetch(`${E2E.origin}/`);
  const html = await page.text();
  if (!page.ok || !html.includes('id="root"')) {
    throw new Error(`${E2E.origin}/ does not serve the built page. Run \`npm run build\` first.`);
  }

  if (!E2E.readOnly && /[\\/]ui-seed[\\/]/.test(system.studies_dir)) {
    throw new Error(
      `The server's store is the shared seed (${system.studies_dir}). Writing tests would change it.\n` +
        "Copy the seed (e2e/reset-store.sh) and point the server at the copy, or set E2E_READONLY=1.",
    );
  }
  // Warm the server: the first read of each session reads its file (its frame has no stages
  // meanwhile). Wait for each frame to settle, then read its views once, so no test is timed
  // against the cold start.
  const headers = { "x-qpilot-token": E2E.token };
  interface Frame {
    key: string;
    kind: string;
    study_id?: string | null;
    results_visible: boolean;
    /** The session is still reading its file (the cold start). */
    warming?: boolean;
    stages: { stage: string; confirmed: boolean }[];
  }
  const list = (await (await fetch(`${E2E.origin}/api/workspaces`, { headers })).json()) as {
    workspaces: Frame[];
  };
  for (const w of list.workspaces) {
    const path = w.kind === "session" ? `/api/sessions/${w.key}` : `/api/studies/${w.key}`;
    let frame: Frame = w;
    for (let i = 0; i < 60; i++) {
      frame = (await (await fetch(`${E2E.origin}${path}`, { headers })).json()) as Frame;
      const confirmed = ["design", "curves"].every(
        (s) => frame.stages?.find((x) => x.stage === s)?.confirmed,
      );
      // Still reading the file: `warming` (older servers: no stages yet).
      const loading = Boolean(frame.warming) || (w.kind === "session" && !frame.stages?.length);
      if (!loading && (w.kind !== "session" || !confirmed || frame.study_id)) break;
      await new Promise((r) => setTimeout(r, 2000));
    }
    if (frame.results_visible && frame.study_id) {
      await fetch(`${E2E.origin}/api/studies/${frame.study_id}/results`, { headers });
      await fetch(`${E2E.origin}/api/studies/${frame.study_id}/cards`, { headers });
    }
  }
  // Each run reports its own axe findings (e2e/axe-summary.mjs reads them).
  rmSync(join(E2E.screenshotDir, "axe"), { recursive: true, force: true });
  process.env.E2E_STUDIES_DIR = system.studies_dir;
  console.log(`e2e: qPilot ${system.version} at ${E2E.origin}, store ${system.studies_dir}`);
}

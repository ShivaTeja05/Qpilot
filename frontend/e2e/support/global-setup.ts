/**
 * Before any test: the server must be answering with the built page, over a store that is not
 * the shared seed (writing tests decide and undo cards). Fails in plain words otherwise.
 */
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
  // Warm the server: the first read of each workspace is slow (it opens the study); do it once
  // here, not inside a test's timeout.
  const headers = { "x-qpilot-token": E2E.token };
  const list = (await (await fetch(`${E2E.origin}/api/workspaces`, { headers })).json()) as {
    workspaces: { key: string; kind: string; study_id?: string | null; results_visible: boolean }[];
  };
  for (const w of list.workspaces) {
    const frame = w.kind === "session" ? `/api/sessions/${w.key}` : `/api/studies/${w.key}`;
    await fetch(`${E2E.origin}${frame}`, { headers });
    if (w.results_visible && w.study_id) {
      await fetch(`${E2E.origin}/api/studies/${w.study_id}/results`, { headers });
      await fetch(`${E2E.origin}/api/studies/${w.study_id}/cards`, { headers });
    }
  }
  process.env.E2E_STUDIES_DIR = system.studies_dir;
  console.log(`e2e: qPilot ${system.version} at ${E2E.origin}, store ${system.studies_dir}`);
}

/**
 * What the page must show, read from the real API of the server under test. Tests compare the
 * page with these answers; they never carry their own numbers, genes or names.
 */
import { expect, type APIRequestContext } from "@playwright/test";
import type { components } from "../../src/api/schema";

type S = components["schemas"];
export type Workspace = S["WorkspaceSummary"];
export type WorkspaceView = S["WorkspaceView"];
export type ProposalList = S["ProposalList"];

async function getJson<T>(api: APIRequestContext, path: string): Promise<T> {
  const res = await api.get(path);
  expect(res.status(), `GET ${path}: ${await res.text().catch(() => "")}`).toBe(200);
  return (await res.json()) as T;
}

/** Every workspace the server lists (Open's "Recent"). */
export async function workspaces(api: APIRequestContext): Promise<Workspace[]> {
  return (await getJson<S["WorkspaceList"]>(api, "/api/workspaces")).workspaces;
}

/** The seeded demo session: design and curves confirmed, results visible, an audit run. */
export async function demoSession(api: APIRequestContext): Promise<Workspace> {
  const all = await workspaces(api);
  const demo =
    all.find((w) => w.is_demo && w.kind === "session") ?? all.find((w) => w.kind === "session");
  expect(
    demo,
    "the store has a Studio session (copy agent-bus/scratch/ui-seed/studies)",
  ).toBeTruthy();
  // On a cold server the list may not name the study yet; the session's own frame does.
  if (!demo!.study_id) demo!.study_id = (await workspaceView(api, demo!)).study_id ?? null;
  return demo!;
}

/** A workspace's frame (title, stages, next step, heads). */
export async function workspaceView(
  api: APIRequestContext,
  w: Pick<Workspace, "key" | "kind">,
): Promise<WorkspaceView> {
  return getJson<WorkspaceView>(
    api,
    w.kind === "session" ? `/api/sessions/${w.key}` : `/api/studies/${w.key}`,
  );
}

/** The Studio inbox of one stage. */
export async function proposals(
  api: APIRequestContext,
  sid: string,
  stage: "design" | "curves" | "prism",
): Promise<ProposalList> {
  return getJson<ProposalList>(api, `/api/sessions/${sid}/proposals?stage=${stage}`);
}

/** The hash route of a section of a workspace (mirrors `sectionPath` in src/shell/sections.ts). */
export function route(
  w: Pick<Workspace, "key" | "kind"> | null,
  section: string,
  ...rest: string[]
): string {
  if (section === "home") return "/";
  if (section === "settings" || !w) return `/${section}`;
  return [
    "",
    w.kind === "session" ? "s" : "r",
    w.key,
    section,
    ...rest.map(encodeURIComponent),
  ].join("/");
}

/** A pattern matching this text literally (names from the store can hold regex characters). */
export function literal(text: string, flags = ""): RegExp {
  return new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), flags);
}

/** GET a JSON route, or null when the server does not serve it (yet). */
export async function maybeJson<T>(api: APIRequestContext, path: string): Promise<T | null> {
  const res = await api.get(path);
  return res.ok() ? ((await res.json()) as T) : null;
}

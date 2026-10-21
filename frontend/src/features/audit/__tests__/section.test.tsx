/**
 * The Audit section end to end on recorded real answers: a running audit re-attaches to its job,
 * a finished one opens on the Study tab, and Verify shows the server's check and the binding.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import overview from "@/test/recorded/audit-overview.json";
import study from "@/test/recorded/audit-study.json";
import { TooltipProvider } from "@/ui";
import Section from "..";
import type { AuditStatus, AuditVerify } from "../types";
import overviewLoading from "./recorded/overview-loading.json";
import running from "./recorded/status-running.json";
import ready from "./recorded/status-ready.json";
import verify from "./recorded/verify.json";

const runningStatus = running as AuditStatus;
const readyStatus = ready as AuditStatus;

// The charts render real data; the shared machine can be slow.
vi.setConfig({ testTimeout: 20_000 });

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Recorded answers by "METHOD /path"; an `{ httpStatus, body }` entry answers with that status. */
const routes = new Map<string, unknown>();
const answered = (value: unknown): value is { httpStatus: number; body: unknown } =>
  typeof value === "object" && value !== null && "httpStatus" in value;

beforeEach(() => {
  routes.clear();
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url, "http://127.0.0.1").pathname;
    const method = init?.method ?? (input instanceof Request ? input.method : "GET");
    const body = routes.get(`${method} ${path}`);
    return Promise.resolve(
      body === undefined
        ? respond(404, { error: { code: "not_found", message: "Not recorded.", details: {} } })
        : answered(body)
          ? respond(body.httpStatus, body.body)
          : respond(200, body),
    );
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(status: AuditStatus, rest: string[] = []) {
  const id = status.study_id!;
  // The frame of a study analysed outside a session (ids only; no numbers).
  const workspace = { key: id, kind: "study", study_id: id } as Schemas["WorkspaceView"];
  routes.set(`GET /api/studies/${id}/audit`, status);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <Section workspace={workspace} rest={rest} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Audit section", () => {
  it("re-attaches to a running audit's job", async () => {
    const job = runningStatus.job!;
    routes.set(`GET /api/jobs/${job.id}`, job);
    show(runningStatus);
    expect(await screen.findByRole("heading", { name: "The audit is running" })).toBeTruthy();
    expect(await screen.findByText(job.title)).toBeTruthy();
    expect(screen.getByText(job.step)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run the audit" })).toBeNull();
  });

  it("opens a finished audit on the Study tab", async () => {
    const id = readyStatus.study_id!;
    routes.set(`GET /api/studies/${id}/audit/overview`, overview);
    routes.set(`GET /api/studies/${id}/audit/study`, study);
    show(readyStatus);
    expect(await screen.findByRole("tab", { name: "Study", selected: true })).toBeTruthy();
    expect(await screen.findByRole("list", { name: "Genes" })).toBeTruthy();
    // no decision since the audit: no notice
    expect(screen.queryByText(/since this audit/)).toBeNull();
  });

  it("shows the load job, not an error, while the views are loading", async () => {
    const id = readyStatus.study_id!;
    const job = overviewLoading.error.details.job;
    routes.set(`GET /api/studies/${id}/audit/overview`, { httpStatus: 409, body: overviewLoading });
    routes.set(`GET /api/jobs/${job.id}`, job);
    // the status no longer names the load (e.g. read before it started): the view's 409 does
    show({ ...readyStatus, views_ready: false, loading: null });
    expect(await screen.findByText(job.title)).toBeTruthy();
    expect(screen.queryByText("The audit's views could not be read")).toBeNull();
  });

  it("Verify shows the server's check and the binding to the record", async () => {
    const id = readyStatus.study_id!;
    const v = verify as AuditVerify;
    routes.set(`GET /api/studies/${id}/audit/overview`, overview);
    routes.set(`POST /api/studies/${id}/audit/verify`, v);
    show(readyStatus, ["verify"]);
    const checks = await screen.findByRole("region", { name: /Is this audit intact/ });
    expect(await within(checks).findByText("Every file matches its checksum")).toBeTruthy();
    expect(within(checks).getByText(new RegExp(`${v.files_checked} files listed`))).toBeTruthy();
    expect(within(checks).getByText("It belongs to this study's record")).toBeTruthy();
    expect(within(checks).getByText("It describes the current decisions")).toBeTruthy();
    // a link inside a sentence is underlined, not told apart by colour alone
    const record = screen.getByRole("link", { name: "Record" });
    expect(record.className.split(/\s+/)).toContain("underline");
    // every file the server listed, each one a download from the audit's own files route
    const files = screen.getByRole("region", { name: "The audit's files" });
    const links = within(files).getAllByRole("link");
    expect(links).toHaveLength(v.files.length);
    expect(links[0]!.getAttribute("href")).toBe(
      `/api/studies/${id}/audit/files/${encodeURIComponent(v.files[0]!.name)}`,
    );
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
import { pathOf } from "@/shell/route";
import { TooltipProvider } from "@/ui";
import plate from "@/charts/plate/__tests__/recorded/plate-CDH5_20080305.json";
import curveE1 from "@/charts/curves/__tests__/recorded/curve-CDH5_20080305-E1.json";
import confirmedFrame from "@/test/recorded/shell-session-frame.json";
import waitingFrame from "./recorded/frame-curves-waiting.json";
import waitingInbox from "./recorded/proposals-curves-waiting.json";

// The API, answered from recordings of the real server (see the recorded/ READMEs).
const routes = vi.hoisted(() => new Map<string, unknown>());
const calls = vi.hoisted(() => [] as { path: string; query: unknown }[]);
vi.mock("@/api/client", async (importActual) => {
  const actual = await importActual<typeof import("@/api/client")>();
  const answer = (path: string, init?: { params?: { query?: unknown } }) => {
    calls.push({ path, query: init?.params?.query });
    const data = routes.get(path);
    const ok = data !== undefined;
    return Promise.resolve({
      data: ok ? data : undefined,
      error: ok ? undefined : { error: { code: "not_found", message: "Not recorded." } },
      response: new Response(null, { status: ok ? 200 : 404 }),
    });
  };
  return { ...actual, api: { GET: vi.fn(answer), POST: vi.fn(answer) } };
});
vi.mock("uplot", () => ({
  default: class {
    static pxRatio = 1;
    width = 600;
    setSize() {}
    destroy() {}
  },
}));

import CurvesSection from "../index";
import { disagreementSentence, disagreementsByPlate } from "../StageBar";

beforeAll(() => {
  // jsdom has no media queries: the page is narrow (one column).
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(() => {
  cleanup();
  routes.clear();
  calls.length = 0;
});

type Frame = Schemas["WorkspaceView"];

function show(workspace: Frame, path: string, rest: string[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook, history } = memoryLocation({ path, record: true });
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <Router hook={hook}>{children}</Router>
      </TooltipProvider>
    </QueryClientProvider>
  );
  return {
    history,
    ...render(<CurvesSection workspace={workspace} rest={rest} />, { wrapper: wrap }),
  };
}

const waiting = waitingFrame as unknown as Frame;
const confirmed = confirmedFrame as unknown as Frame;

describe("the Curve Judge's disagreements in words", () => {
  it("says how many wells, where, and how many the engine refutes", () => {
    const proposals = (waitingInbox as Schemas["ProposalList"]).proposals;
    const rows = disagreementsByPlate(proposals);
    const calls = proposals.filter((p) => p.kind === "curve.well_call" && p.status === "proposed");
    expect(rows.reduce((n, r) => n + r.wells, 0)).toBe(calls.length);
    expect(rows).toHaveLength(
      new Set(calls.map((p) => p.subject.slice(0, p.subject.lastIndexOf("/")))).size,
    );
    const refuted = calls.filter((p) => p.check.status === "contradicted").length;
    const text = disagreementSentence(rows);
    if (rows.length === 1) expect(text).toContain(`all on plate ${rows[0]!.run}`);
    if (refuted === calls.length) expect(text).toContain("the engine’s check refutes all");
  });
});

describe("Curves section", { timeout: 30_000 }, () => {
  it("is locked with a reason until the design is confirmed", () => {
    const stages = waiting.stages.map((s) =>
      s.stage === "design" ? { ...s, confirmed: false } : s,
    );
    show({ ...waiting, stages }, "/s/bc1d233e3866/curves");
    expect(screen.getByText("Confirm the design first")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Go to Design" })).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  it("waits for the file's first read instead of guessing the stages", () => {
    show({ ...waiting, warming: true, stages: [] }, "/s/bc1d233e3866/curves");
    expect(screen.queryByText("Confirm the design first")).toBeNull();
    expect(screen.getByRole("status")).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  it("says there is no curves stage for a study outside Studio", () => {
    show({ ...waiting, kind: "study" }, "/r/bc1d233e3866/curves");
    expect(screen.getByText("Curves belong to a Studio session")).toBeTruthy();
  });

  it("shows the inbox with its bulk actions, and moving to a card opens its well", async () => {
    routes.set("/api/sessions/{sid}/proposals", waitingInbox);
    routes.set("/api/sessions/{sid}/plate", plate);
    const { history } = show(waiting, "/s/bc1d233e3866/curves");
    expect(await screen.findByText(/contradicted first/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Accept all consistent…" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject contradicted AI calls…" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check the curves again" })).toBeTruthy();
    // The disagreements in one sentence, by plate, from the recorded inbox.
    const plates = disagreementsByPlate((waitingInbox as Schemas["ProposalList"]).proposals);
    expect(screen.getByText(disagreementSentence(plates))).toBeTruthy();
    // j focuses the first waiting card (the inbox keeps the server's order: contradicted first).
    const first = (waitingInbox as Schemas["ProposalList"]).proposals.find(
      (p) => p.status === "proposed",
    )!;
    expect(first.kind).toBe("curve.well_call");
    fireEvent.keyDown(document.body, { key: "j" });
    const at = first.subject.lastIndexOf("/");
    const want = pathOf(
      "s",
      "bc1d233e3866",
      "curves",
      first.subject.slice(0, at),
      first.subject.slice(at + 1),
    );
    await waitFor(() => expect(history.at(-1)).toBe(want));
  });

  it("opens the plate and the well named in the address, with its curve", async () => {
    routes.set("/api/sessions/{sid}/proposals", waitingInbox);
    routes.set("/api/sessions/{sid}/plate", plate);
    routes.set("/api/sessions/{sid}/curve", curveE1);
    show(confirmed, "/s/bc1d233e3866/curves/CDH5_20080305/E1", ["CDH5_20080305", "E1"]);
    expect(await screen.findByRole("grid", { name: "Plate CDH5_20080305" })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("img", { name: /Cq 46\.5/ })).toBeTruthy());
    expect(calls.find((c) => c.path === "/api/sessions/{sid}/plate")?.query).toEqual({
      run: "CDH5_20080305",
    });
    expect(calls.find((c) => c.path === "/api/sessions/{sid}/curve")?.query).toEqual({
      well: "CDH5_20080305/E1",
    });
    expect(screen.getByRole("gridcell", { name: /^E1,/ }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(await screen.findByText("Curves confirmed")).toBeTruthy();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
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
  const { hook } = memoryLocation({ path });
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <Router hook={hook}>{children}</Router>
    </QueryClientProvider>
  );
  return render(<CurvesSection workspace={workspace} rest={rest} />, { wrapper: wrap });
}

const waiting = waitingFrame as unknown as Frame;
const confirmed = confirmedFrame as unknown as Frame;

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

  it("says there is no curves stage for a study outside Studio", () => {
    show({ ...waiting, kind: "study" }, "/r/bc1d233e3866/curves");
    expect(screen.getByText("Curves belong to a Studio session")).toBeTruthy();
  });

  it("lists what waits, with each well's curve one click away", async () => {
    routes.set("/api/sessions/{sid}/proposals", waitingInbox);
    routes.set("/api/sessions/{sid}/plate", plate);
    show(waiting, "/s/bc1d233e3866/curves");
    const n = (waitingInbox as Schemas["ProposalList"]).proposals.filter(
      (p) => p.status === "proposed",
    ).length;
    expect(await screen.findByText(`${n} proposals waiting for you.`)).toBeTruthy();
    const wellCalls = (waitingInbox as Schemas["ProposalList"]).proposals.filter(
      (p) => p.kind === "curve.well_call",
    );
    const first = wellCalls[0]!.subject;
    expect(
      screen.getByRole("button", {
        name: `Open the curve of well ${first.slice(first.lastIndexOf("/") + 1)}`,
      }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Check the curves/ })).toBeTruthy();
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
    expect(screen.getByText("Curves confirmed")).toBeTruthy();
  });
});

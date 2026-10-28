import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import cqTable from "./recorded/cq-table-hmuy.json";
import frame from "./recorded/frame-cq-only-hmuy.json";
import plate from "./recorded/plate-cq-only-hmuy.json";
import inbox from "./recorded/proposals-curves-cq-only-hmuy.json";

// The API, answered from recordings of the real server (recorded/README.md).
const routes = vi.hoisted(() => new Map<string, unknown>());
const calls = vi.hoisted(() => [] as string[]);
vi.mock("@/api/client", async (importActual) => {
  const actual = await importActual<typeof import("@/api/client")>();
  const answer = (path: string) => {
    calls.push(path);
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
import { cqTableSummary, setsToLook } from "../CqTablePanel";

beforeAll(() => {
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

const view = cqTable as unknown as Schemas["CqTableView"];

function show() {
  routes.set("/api/sessions/{sid}/proposals", inbox);
  routes.set("/api/sessions/{sid}/plate", plate);
  routes.set("/api/sessions/{sid}/cq-table", cqTable);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook } = memoryLocation({ path: "/s/3e231e2ed42c/curves" });
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <Router hook={hook}>{children}</Router>
      </TooltipProvider>
    </QueryClientProvider>
  );
  return render(
    <CurvesSection workspace={frame as unknown as Schemas["WorkspaceView"]} rest={[]} />,
    { wrapper: wrap },
  );
}

describe("the Cq table in words", () => {
  it("lists what to look at: the replicate set wider than expected", () => {
    const look = setsToLook(view.sets);
    expect(look.map((s) => `${s.sample}/${s.target}`)).toEqual(["DIP_3/hmuYPe"]);
    expect(look[0]!.spread).toBe("outside");
    expect(cqTableSummary(view)).toBe(
      "36 wells on the analysed plates, 36 with a Cq · 0 study wells without a Cq · 1 replicate set wider than expected.",
    );
  });
});

describe("Curves section of a file of Cq values only", { timeout: 30_000 }, () => {
  it("confirms the Cq table in place of curves: no curve viewer, no melt, no group", async () => {
    show();
    const panel = (await screen.findByRole("heading", { name: "Your Cq table" })).closest(
      "section",
    )!;
    const card = within(panel as HTMLElement);
    expect(card.getByText(view.message)).toBeTruthy();
    // Each assay's efficiency, said plainly: no dilution series here, so 2.0 is assumed.
    const efficiencies = card.getByRole("list", { name: "Efficiency of each assay" });
    expect(within(efficiencies).getAllByText("assumed")).toHaveLength(2);
    expect(efficiencies.textContent).toContain("16S rRNA: efficiency assumed to be 2.0 (100 %)");
    // What needs curves says so, in plain words, instead of failing.
    const na = card.getByRole("list", { name: "Checks that do not apply" });
    expect(na.textContent).toContain("Not applicable: this file has Cq values only");
    expect(na.textContent).toContain("Curve Judge");
    // To look at: the one replicate set G-REP finds wider than expected, with its Cq per well.
    const table = card.getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(2); // header + DIP_3 / hmuYPe
    expect(rows[1]!.textContent).toContain("DIP_3");
    expect(rows[1]!.textContent).toContain("wider than expected");
    expect(rows[1]!.textContent).toContain("24.61");
    fireEvent.click(card.getByRole("radio", { name: "All (12)" }));
    expect(within(card.getByRole("table")).getAllByRole("row")).toHaveLength(13);
    // The stage's words follow the file: the rule reads the file's own Cq, not LinRegPCR's.
    expect(screen.getByText(/the file’s own Cq, the engine’s default/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /^Melt/ })).toBeNull();
    expect(calls).not.toContain("/api/sessions/{sid}/curve");
    expect(calls).not.toContain("/api/sessions/{sid}/melt");
    // Blind: nothing on the page pairs a design group with a number.
    expect(document.body.textContent).not.toMatch(/\bgroup (DIP|Hm)\b/);
  });
});

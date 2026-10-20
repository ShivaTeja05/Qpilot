/**
 * The whole History section on the recorded API answers of the seeded demo session
 * (`recorded/`, written by `recorded/record.py`): the server's JSON is served to the page's own
 * requests by a fetch stub; a route not recorded answers 404 in the server's error shape.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import HistorySection from "../index";
import type { HistoryCompare, HistoryView } from "../api";
import sessionJson from "../recorded/session-bc1d233e3866.json";
import afterJson from "../recorded/history-e300000d4f9a.json";
import beforeJson from "../recorded/history-cf49ccd72052.json";
import compareJson from "../recorded/compare-e300000d4f9a-cf49ccd72052.json";
import diffJson from "../recorded/diff-e300000d4f9a-0-1.json";

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs; it answers with the recorded JSON (`answer` below).
const net = vi.hoisted(() => {
  const state = { answer: (_path: string): unknown => null, asked: [] as string[] };
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string" && input.startsWith("/") ? `${location.origin}${input}` : input,
        init,
      );
    }
  } as typeof Request;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    state.asked.push(path);
    const body = state.answer(path);
    const json = { "content-type": "application/json" };
    return body === null
      ? new Response(
          JSON.stringify({ error: { code: "not_found", message: "No such API route." } }),
          { status: 404, headers: json },
        )
      : new Response(JSON.stringify(body), { status: 200, headers: json });
  }) as typeof fetch;
  // jsdom has no media queries: the page is read with reduced motion (the map does not glide)
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduce"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return state;
});

type Workspace = Schemas["WorkspaceView"];
const session = sessionJson as unknown as Workspace;
const after = afterJson as unknown as HistoryView;
const before = beforeJson as unknown as HistoryView;
const compare = compareJson as unknown as HistoryCompare;

net.answer = (path: string) => {
  const url = new URL(path, location.origin);
  const p = url.pathname;
  if (p === `/api/studies/${after.study_id}/history`) return after;
  if (p === `/api/studies/${before.study_id}/history`) return before;
  if (p === `/api/studies/${after.study_id}/history/compare`)
    return url.searchParams.get("other") === before.study_id ? compare : null;
  if (p === `/api/studies/${after.study_id}/history/diff`)
    return url.searchParams.get("from") === "0" && url.searchParams.get("to") === "1"
      ? diffJson
      : null;
  return null;
};

afterEach(cleanup);

function show(workspace: Workspace = session) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <HistorySection workspace={workspace} rest={[]} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const timeline = () => screen.getByRole("list", { name: "History of this analysis" });
const current = () =>
  within(timeline())
    .getAllByRole("button")
    .filter((b) => b.getAttribute("aria-current") === "step");

describe("the History section", () => {
  it("opens at the head of the chain, the earlier analysis and the Studio runs on the track", async () => {
    show();
    await screen.findByRole("list", { name: "History of this analysis" });
    // the earlier analysis joins the track once its own history has loaded
    await waitFor(() =>
      expect(timeline().closest("section")!.textContent).toContain("Point 3 of 3"),
    );
    expect(current()).toHaveLength(1);
    expect(current()[0]!.getAttribute("aria-label")).toMatch(/^Step 1: qPilot \(automatic\) chose/);
    const buttons = within(timeline()).getAllByRole("button");
    expect(
      buttons.some((b) => /earlier analysis of this file/.test(b.getAttribute("aria-label") ?? "")),
    ).toBe(true);
    expect(
      buttons.filter((b) => /^Studio, /.test(b.getAttribute("aria-label") ?? "")),
    ).toHaveLength(after.studio.length);
    expect(screen.getByText("Intact: every hash checks out")).toBeTruthy();
  });

  it("moves along the chain with the arrow keys and says what the round trip changed", async () => {
    show();
    await screen.findByRole("list", { name: "History of this analysis" });
    await waitFor(() =>
      expect(timeline().closest("section")!.textContent).toContain("Point 3 of 3"),
    );
    fireEvent.keyDown(current()[0]!, { key: "ArrowLeft" });
    expect(current()[0]!.getAttribute("aria-label")).toMatch(/^Step 0/);
    await screen.findByText("What changed since the earlier analysis");
    const panel = screen.getByRole("region", { name: "What changed" });
    await within(panel).findByText(compare.summary);
    const odc1 = compare.fold_moves.find((g) => g.gene === "ODC1")!;
    expect(odc1).toBeTruthy();
    expect(within(panel).getAllByRole("button", { name: "ODC1" }).length).toBeGreaterThan(0);
    fireEvent.keyDown(current()[0]!, { key: "Home" });
    expect(current()[0]!.getAttribute("aria-label")).toMatch(/earlier analysis/);
    fireEvent.keyDown(current()[0]!, { key: "End" });
    expect(current()[0]!.getAttribute("aria-label")).toMatch(/^Step 1/);
  });

  it("compares with the other analysis of the file: the design change, item by item", async () => {
    show();
    const card = (await screen.findByText("Compare with another analysis of this file")).closest(
      "section",
    )!;
    await waitFor(() => expect(within(card).getAllByText(compare.summary).length).toBe(1));
    const added = compare.design.flatMap((d) => d.added);
    expect(added.length).toBeGreaterThan(0);
    for (const well of added) expect(within(card).getByText(`+ ${well}`)).toBeTruthy();
  });

  it("opens a Studio run from the timeline in the Studio log", async () => {
    show();
    await screen.findByRole("list", { name: "History of this analysis" });
    const run = after.studio[0]!;
    const chip = within(timeline())
      .getAllByRole("button")
      .find((b) => (b.getAttribute("aria-label") ?? "").startsWith(`Studio, ${run.title}`))!;
    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    const log = screen.getByText("Studio log", { selector: "h2, h3" }).closest("section")!;
    const toggle = within(log).getByRole("button", { name: new RegExp(run.title.slice(0, 20)) });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("asks for nothing while the results are hidden", () => {
    net.asked = [];
    show({ ...session, results_visible: false });
    expect(screen.getByText("Nothing to replay yet")).toBeTruthy();
    expect(net.asked.filter((p) => p.includes("/history"))).toEqual([]);
  });
});

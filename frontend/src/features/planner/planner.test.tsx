/**
 * The planner on the recorded API answers of the seeded demo session (`recorded/`, written by
 * `recorded/record.py` from a running `qpilot app`): the server's JSON is served to the page's own
 * requests by a fetch stub that also keeps every request body, so a test can check what the page
 * asked for. Nothing here is typed-in data.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { count } from "@/lib/format";
import { TooltipProvider } from "@/ui";
import type { PlanLayoutView, PlannerView, PlanView } from "./api";
import { CategoryPlate } from "./CategoryPlate";
import PlannerSection from "./index";
import layoutJson from "./recorded/layout.json";
import plan3Json from "./recorded/plan-fold3.json";
import planJson from "./recorded/plan.json";
import plannerJson from "./recorded/planner.json";
import sessionJson from "./recorded/session.json";
import { FOLD_STOPS, nearestStop } from "./words";

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs.
const net = vi.hoisted(() => {
  const state = {
    answer: (_method: string, _path: string, _body: unknown): [number, unknown] => [404, null],
    sent: [] as { method: string; path: string; body: unknown }[],
  };
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string" && input.startsWith("/") ? `${location.origin}${input}` : input,
        init,
      );
    }
  } as typeof Request;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : null;
    state.sent.push({ method: request.method, path, body });
    const [status, answer] = state.answer(request.method, path, body);
    return new Response(
      JSON.stringify(answer ?? { error: { code: "not_found", message: "No such API route." } }),
      { status: answer === null ? 404 : status, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  return state;
});

const session = sessionJson as unknown as Schemas["WorkspaceView"];
const planner = plannerJson as unknown as PlannerView;
const plan = planJson as unknown as PlanView;
const plan3 = plan3Json as unknown as PlanView;
const layout = layoutJson as unknown as PlanLayoutView;
const study = session.study_id!;

function recorded(method: string, path: string, body: unknown): [number, unknown] {
  if (path === `/api/studies/${study}/planner` && method === "GET") return [200, planner];
  if (path === `/api/studies/${study}/planner` && method === "POST") {
    const fold = (body as { fold?: number } | null)?.fold;
    return [200, fold === 3 ? plan3 : plan];
  }
  if (path === `/api/studies/${study}/planner/layout`) return [200, layout];
  return [404, null];
}

afterEach(() => {
  cleanup();
  net.sent = [];
  net.answer = recorded;
});
net.answer = recorded;

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <PlannerSection workspace={session} rest={[]} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("the planner", () => {
  it("shows what the study measured and the plan's answer, in the server's words", async () => {
    show();
    expect(await screen.findByText(plan.headline)).toBeTruthy();
    for (const g of planner.groups) expect(screen.getAllByText(g.label).length).toBeGreaterThan(0);
    expect(screen.getByText(planner.efficiency.text)).toBeTruthy();
    if (plan.ceiling) expect(screen.getByText(plan.ceiling)).toBeTruthy();
    // every compared gene is in the table's count, the chosen ones in the chosen count
    expect(screen.getByRole("radio", { name: `All ${count(plan.genes.length)}` })).toBeTruthy();
    expect(screen.getByRole("radio", { name: `Chosen ${count(plan.focus.length)}` })).toBeTruthy();
  });

  it("asks for the study's defaults first, then again when the fold moves", async () => {
    show();
    await screen.findByText(plan.headline);
    const first = net.sent.find((s) => s.method === "POST" && s.path.endsWith("/planner"));
    expect(first?.body).toMatchObject({
      fold: planner.defaults.fold,
      genes: planner.defaults.genes,
      refs: planner.defaults.refs,
      wells_per_plate: planner.defaults.wells_per_plate,
      n_per_group: null,
    });
    const slider = screen.getByRole("slider", { name: "Change worth finding" });
    fireEvent.change(slider, { target: { value: String(nearestStop(FOLD_STOPS, 3)) } });
    expect(await screen.findByText(plan3.headline, {}, { timeout: 3000 })).toBeTruthy();
    const last = net.sent.filter((s) => s.method === "POST" && s.path.endsWith("/planner")).at(-1);
    expect((last?.body as { fold: number }).fold).toBe(3);
  });

  it("draws the power curves with a sentence that names the gene in focus", async () => {
    show();
    await screen.findByText(plan.headline);
    const lead = plan.curves[0]!;
    const chart = screen.getByRole("img", { name: new RegExp(`change in ${lead.gene} is called`) });
    expect(chart.querySelectorAll("path").length).toBeGreaterThanOrEqual(2 * plan.curves.length);
  });

  it("lays out the plates with their balance and the CSV to import", async () => {
    show();
    const link = await screen.findByRole("link", { name: /Download CSV/ }, { timeout: 4000 });
    expect(link.getAttribute("href")).toBe(layout.csv_url);
    expect(link.getAttribute("download")).toBe(layout.csv_name);
    expect(screen.getByText("Every group on every plate")).toBeTruthy();
    expect(screen.getByText("Reference genes on every plate")).toBeTruthy();
    const tiles = within(screen.getByRole("list", { name: "Every plate" })).getAllByRole(
      "listitem",
    );
    expect(tiles).toHaveLength(layout.plates.length);
  });

  it("shows a refusal in the server's own words", async () => {
    net.answer = (method, path, body) =>
      method === "POST" && path.endsWith("/planner")
        ? [
            422,
            { error: { code: "bad_request", message: "Fc must be a fold change other than 1." } },
          ]
        : recorded(method, path, body);
    show();
    expect(await screen.findByText("Fc must be a fold change other than 1.")).toBeTruthy();
  });
});

describe("a planned plate", () => {
  const plate = layout.plates[0]!;
  const groups = layout.groups.map((g) => g.label);

  it("reads out every well with its sample, group, gene and replicate", () => {
    render(<CategoryPlate plate={plate} layer="group" groups={groups} />);
    const cells = screen.getAllByRole("gridcell");
    expect(cells).toHaveLength(layout.wells_per_plate);
    const w = plate.wells[0]!;
    expect(
      screen.getByRole("gridcell", {
        name: new RegExp(`^${w.well}: sample ${w.sample} \\(${w.group}\\)`),
      }),
    ).toBeTruthy();
    const empty = cells.filter((c) => c.getAttribute("aria-label")?.endsWith("empty"));
    expect(empty).toHaveLength(plate.wells_free);
  });

  it("moves between wells with the arrow keys", () => {
    render(<CategoryPlate plate={plate} layer="target" groups={groups} />);
    const grid = screen.getByRole("grid", { name: plate.name });
    const first = within(grid).getAllByRole("gridcell")[0]!;
    first.focus();
    fireEvent.keyDown(grid, { key: "ArrowRight" });
    expect(document.activeElement?.getAttribute("data-pos")).toBe("0:1");
    fireEvent.keyDown(grid, { key: "ArrowDown" });
    expect(document.activeElement?.getAttribute("data-pos")).toBe("1:1");
  });

  it("names every gene and control in its legend, with a number or letter", () => {
    render(<CategoryPlate plate={plate} layer="target" groups={groups} />);
    for (const gene of [...plate.genes, ...plate.refs])
      expect(
        screen.getAllByText(new RegExp(`^${gene.replace(/[()]/g, "\\$&")}`)).length,
      ).toBeGreaterThan(0);
  });
});

describe("the planner's stops", () => {
  it("snap a value to the nearest stop on a log scale", () => {
    expect(FOLD_STOPS[nearestStop(FOLD_STOPS, 3)]).toBe(3);
    expect(FOLD_STOPS[nearestStop(FOLD_STOPS, 2.2)]).toBe(2);
    expect(FOLD_STOPS[nearestStop(FOLD_STOPS, 100)]).toBe(10);
  });
});

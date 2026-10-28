/**
 * The Design plate map on a multiplex plate recorded from the real API (LightCycler 96 bACTXY,
 * `src/charts/plate/__tests__/recorded/plate-lc96-bACTXY.json`): a fetch stub serves the plate to
 * the page's own request. Several dyes per well: a badge says so, a picker chooses the target the
 * map shows, and a chosen well lists every curve it holds with its dye.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import recorded from "@/charts/plate/__tests__/recorded/plate-lc96-bACTXY.json";
import { TooltipProvider } from "@/ui";
import { DesignPlate } from "./DesignPlate";

const view = recorded as unknown as Schemas["PlateView"];

// The typed client keeps the `fetch` and `Request` it finds when its module loads.
vi.hoisted(() => {
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
    const { default: plate } =
      await import("@/charts/plate/__tests__/recorded/plate-lc96-bACTXY.json");
    const found = path.endsWith("/plate");
    return new Response(JSON.stringify(found ? plate : { error: { code: "not_found" } }), {
      status: found ? 200 : 404,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
});

beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(cleanup);

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const runs: Schemas["InspectRun"][] = [view.run];
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <DesignPlate sid="s" runs={runs} quotes={() => null} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const cell = (label: string) => screen.getByRole("gridcell", { name: new RegExp(`^${label},`) });

describe("the Design plate map with several dyes per well", () => {
  it("says so, and lists every curve of a chosen well with its dye", async () => {
    show();
    expect(await screen.findByText("several dyes per well")).toBeTruthy();
    fireEvent.click(cell("D3"));
    const list = screen.getByRole("list", { name: "Curves in this well" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "bACT (FAM) · Standard",
      "X (Hex) · Standard",
      "Y (Texas Red) · Standard",
      "IPC (Cy5) · Standard",
    ]);
    expect(screen.getByText("· dye FAM")).toBeTruthy();
  });

  it("shows the target a person picks", async () => {
    show();
    const trigger = await screen.findByRole("combobox", { name: "Target shown" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: /^X/ }));
    expect(cell("D3").getAttribute("aria-label")).toContain("X (Hex)");
    fireEvent.click(cell("D3"));
    expect(screen.getByText("· dye Hex")).toBeTruthy();
  });
});

/**
 * The whole section on the recorded API answers of the seeded demo session (`recorded/`): the
 * server's JSON is served to the page's own requests by a fetch stub; a route not recorded
 * answers 404 in the server's error shape.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/ui";
import type { ProposalList, Workspace } from "./api";
import PrismSection from "./index";
import sessionJson from "./recorded/session.json";
import prismJson from "./recorded/proposals-prism.json";
import roundTripJson from "./recorded/proposals-roundtrip.json";

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs; it answers with the recorded JSON (`answer` below).
const net = vi.hoisted(() => {
  const state = { answer: (_path: string): unknown => null };
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      // same-origin paths, which Node cannot resolve without an origin
      super(
        typeof input === "string" && input.startsWith("/") ? `${location.origin}${input}` : input,
        init,
      );
    }
  } as typeof Request;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = state.answer(path);
    const json = { "content-type": "application/json" };
    return body === null
      ? new Response(
          JSON.stringify({ error: { code: "not_found", message: "No such API route." } }),
          { status: 404, headers: json },
        )
      : new Response(JSON.stringify(body), { status: 200, headers: json });
  }) as typeof fetch;
  return state;
});

const session = sessionJson as unknown as Workspace;
const recorded = import.meta.glob<{ default: unknown }>("./recorded/prism-*.json", { eager: true });

/** The recorded answer for a request path, or null (404). */
function answer(path: string): unknown {
  const url = new URL(path, location.origin);
  const sid = session.key;
  if (url.pathname === `/api/sessions/${sid}/proposals`) {
    return url.searchParams.get("stage") === "roundtrip" ? roundTripJson : prismJson;
  }
  const m = url.pathname.match(new RegExp(`^/api/sessions/${sid}/prism(?:/(\\w+))?$`));
  if (m) return recorded[`./recorded/prism-${m[1] ?? "status"}.json`]?.default ?? null;
  return null;
}
net.answer = answer;

afterEach(cleanup);

function show(workspace: Workspace = session) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <PrismSection workspace={workspace} rest={[]} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("the Prism section", () => {
  it("shows the four steps, the current one marked", () => {
    show();
    const steps = screen.getByRole("navigation", { name: "Steps to Prism and back" });
    expect(within(steps).getAllByRole("button")).toHaveLength(4);
    expect(
      within(steps)
        .getAllByRole("button")
        .filter((b) => b.getAttribute("aria-current") === "step"),
    ).toHaveLength(1);
  });

  it("sends the person to Results while the choices are not confirmed", async () => {
    const choices = session.stages.find((s) => s.stage === "choices")!;
    show();
    if (!choices.confirmed) {
      const link = await screen.findByRole("link", { name: "Go to the choices" });
      expect(link.getAttribute("href")).toBe(`#/s/${session.key}/results/confirm`);
    }
  });

  it("lists the round trip's questions with their words", async () => {
    show();
    const list = roundTripJson as unknown as ProposalList;
    for (const p of list.proposals) {
      const question = (p.payload as { question?: string }).question;
      if (question) expect(await screen.findByText(question)).toBeTruthy();
    }
  });
});

/**
 * The whole section on the recorded API answers of the seeded demo session (`recorded/`): the
 * server's JSON is served to the page's own requests by a fetch stub; a route not recorded
 * answers 404 in the server's error shape.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/ui";
import { fold, ofTotal } from "@/lib/format";
import { describeProposal } from "@/lib/vocab";
import type { PrismBundleView, PrismPreview, PrismRoutes, ProposalList, Workspace } from "./api";
import { summaryOf } from "./PrismFigure";
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

  it("lists the round trip's questions in words, each with the engine's numbers", async () => {
    show();
    const list = roundTripJson as unknown as ProposalList;
    const decided = list.proposals.filter((p) => p.status !== "proposed");
    if (decided.length)
      fireEvent.click(await screen.findByRole("button", { name: /Decided in this stage/ }));
    for (const p of list.proposals) {
      expect(
        (await screen.findAllByText(describeProposal(p), { exact: false })).length,
      ).toBeGreaterThan(0);
    }
    const exclusion = decided.find((p) => p.kind === "prism.exclusion_reason");
    if (exclusion) {
      fireEvent.click(
        screen.getByRole("button", { name: new RegExp(describeProposal(exclusion).slice(0, 30)) }),
      );
      const c = exclusion.consequence as { fc_before: number; fc_after: number };
      expect(
        (await screen.findAllByText(fold(c.fc_before), { exact: false })).length,
      ).toBeGreaterThan(0);
      expect(
        (await screen.findAllByText(fold(c.fc_after), { exact: false })).length,
      ).toBeGreaterThan(0);
    }
  });

  it("says how often the usual routes change a conclusion, from the engine's facts", async () => {
    show();
    const routes = recordedJson<PrismRoutes>("routes");
    const headline = routes.routes.find((r) => r.route === "linear_welch") ?? routes.routes[0]!;
    expect(await screen.findByText(ofTotal(headline.n_differ, headline.n_genes))).toBeTruthy();
    const list = screen.getByRole("list", { name: "Routes into Prism" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .filter((li) => li.parentElement === list),
    ).toHaveLength(routes.routes.length);
  });

  it("previews the first gene's table and figure, and the choices it is exported at", async () => {
    show();
    const preview = recordedJson<PrismPreview>("preview");
    const gene = preview.genes[0]!;
    expect((await screen.findAllByText(`${gene}.csv`)).length).toBeGreaterThan(0);
    const figure = preview.figures[gene];
    if (figure)
      expect(screen.getAllByRole("img", { name: summaryOf(figure) }).length).toBeGreaterThan(0);
    for (const c of preview.choices)
      if (c.option_label) expect(screen.getByText(c.option_label)).toBeTruthy();
  });

  it("offers the bundles this launch wrote for the round trip, with their sent-back folder", async () => {
    show();
    const bundles = recordedJson<{ bundles: PrismBundleView[] }>("bundles").bundles.filter(
      (b) => b.id && b.round_trip,
    );
    const folder = await screen.findByLabelText("Folder Prism sent the tables back to");
    expect((folder as HTMLInputElement).value).toBe(bundles[0]?.sent_back_folder ?? "");
  });
});

function recordedJson<T>(name: string): T {
  return recorded[`./recorded/prism-${name}.json`]!.default as T;
}

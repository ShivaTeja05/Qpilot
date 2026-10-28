/**
 * The Results section's logic and Decision Cards on the API's own views of the demo study,
 * recorded from the real services (src/test/recorded/record.py).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import cardsJson from "@/test/recorded/api-cards.json";
import resultsJson from "@/test/recorded/api-results.json";
import type { CardView, CardsView, ResultsView } from "../api";
import { DecisionCards, cardOrder } from "../DecisionCards";
import { GenesPanel, NO_FILTER, matches } from "../GenesPanel";
import { Summary } from "../Summary";

const cards = cardsJson as unknown as CardsView;
const results = resultsJson as unknown as ResultsView;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("results logic", { timeout: 30_000 }, () => {
  it("the call filter finds exactly the counts the API gives", () => {
    for (const call of ["up", "down", "none"] as const) {
      const n = results.genes.filter((g) => matches(g, { ...NO_FILTER, call })).length;
      expect(n).toBe(results.counts[call]);
    }
    expect(results.genes.filter((g) => matches(g, NO_FILTER))).toHaveLength(results.genes.length);
  });
  it("cards: requests first, then open ones by rank, decided last", () => {
    const order = cardOrder(cards.cards);
    const weight = (s: string, pending: number) =>
      pending || s === "pending_human" ? 0 : s === "open" ? 1 : 2;
    const ws = order.map((c) => weight(c.card.status, c.pending.length));
    expect(ws).toEqual([...ws].sort((a, b) => a - b));
    expect(new Set(order.map((c) => c.card.id))).toEqual(
      new Set(cards.cards.map((c) => c.card.id)),
    );
  });
});

describe("Decision Cards", { timeout: 30_000 }, () => {
  it("say what each option gives the headline genes, and decide only with a reason", async () => {
    // the server's refusal (no data): someone decided since the view was read
    const refusal = () =>
      Promise.resolve({
        error: {
          error: {
            code: "stale",
            message: "Something was decided since you loaded this.",
            details: {},
          },
        },
        response: new Response(null, { status: 409 }),
      });
    const post = vi.spyOn(api, "POST").mockImplementation(refusal as never);
    vi.spyOn(api, "GET").mockImplementation(refusal as never);
    render(wrap(<DecisionCards view={cards} workspaceKey="w" studyId={results.study_id} />));
    const first = cardOrder(cards.cards)[0]!;
    const article = screen.getByRole("article", { name: new RegExp(first.title) });
    // every headline gene's consequence is on the recommended option
    for (const g of first.genes) expect(within(article).getAllByText(g).length).toBeGreaterThan(0);
    const decide = within(article).getByRole("button", { name: /^Decide:/ });
    expect((decide as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(article).getByRole("textbox"), {
      target: { value: "Prespecified in our protocol" },
    });
    expect((decide as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(decide);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [
      string,
      {
        params: { path: { card_id: string } };
        body: { option: string; reason: string; expected_head: string };
      },
    ];
    expect(route).toBe("/api/studies/{study_id}/cards/{card_id}/decide");
    expect(init.params.path.card_id).toBe(first.card.id);
    const sent = init.body;
    expect(sent.reason).toBe("Prespecified in our protocol");
    expect(sent.expected_head).toBe(cards.head);
    expect(first.options.map((o) => o.id)).toContain(sent.option);
  });

  it("mark a choice carried from the earlier analysis, and say why another is asked again", () => {
    const [refset, cutoff, ...rest] = cards.cards as [CardView, CardView, ...CardView[]];
    const carried: CardView = {
      ...cutoff,
      card: { ...cutoff.card, status: "decided", decision: "cut_15", decided_by: "human" },
      status_line:
        "Decided by you: Top 15 %, carried from the earlier analysis cf49ccd72052. Reason: protocol",
      carried: {
        study_id: "cf49ccd72052",
        entry_hash: "ab".repeat(32),
        reason: "protocol",
        found: true,
        decided_at: null,
      },
    };
    const asked: CardView = {
      ...refset,
      asked_again: {
        study_id: "cf49ccd72052",
        option: "top3",
        option_label: "The three most stable",
        why: "in this analysis the choice can change a conclusion",
      },
    };
    const view = { ...cards, cards: [asked, carried, ...rest] };
    render(wrap(<DecisionCards view={view} workspaceKey="w" studyId={results.study_id} />));
    const done = screen.getByRole("article", { name: new RegExp(cutoff.title) });
    expect(within(done).getByText("Carried")).toBeTruthy();
    expect(done.textContent).toContain("carried from the earlier analysis cf49ccd72052");
    const open = screen.getByRole("article", { name: new RegExp(refset.title) });
    expect(open.textContent).toContain(
      "In the earlier analysis cf49ccd72052 a person chose The three most stable. It was not carried here: in this analysis the choice can change a conclusion. Decide it again.",
    );
    expect(within(open).queryByText("Carried")).toBeNull();
  });
});

describe("summary and phone layout", { timeout: 30_000 }, () => {
  it("says how many samples are in neither group, from the API's own counts", () => {
    render(wrap(<Summary view={results} auditHref="#" />));
    const inGroups = results.summary.groups.reduce((n, g) => n + g.n, 0);
    const left = results.summary.n_samples - inGroups;
    expect(left).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(`are in neither`)).textContent).toContain(String(left));
  });
  it("shows every gene as a card on a phone", () => {
    vi.stubGlobal(
      "matchMedia",
      (q: string) =>
        ({
          matches: q.includes("max-width: 639px"),
          media: q,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
          onchange: null,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
    render(
      wrap(
        <GenesPanel
          genes={results.genes}
          filter={NO_FILTER}
          onFilter={() => {}}
          dimLabel={(d) => d}
          selected={null}
          onOpen={() => {}}
        />,
      ),
    );
    const list = screen.getByRole("list", { name: "All genes" });
    expect(within(list).getAllByRole("button")).toHaveLength(results.genes.length);
    expect(screen.queryByRole("table")).toBeNull();
    vi.unstubAllGlobals();
  });
});

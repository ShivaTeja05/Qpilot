/**
 * Decision Cards in a study with several comparisons, on the API's own cards view of a synthetic
 * three-group study where the control genes change a call in Drug B vs Control only (recorded
 * from the real engine by src/test/recorded/record_compare2.py): the card waits for a person,
 * names the comparison it changes, shows each option's effects per comparison and says that a
 * choice applies to the whole study.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import cardsJson from "@/test/recorded/api-cards-compare.json";
import demoCardsJson from "@/test/recorded/api-cards.json";
import type { CardsView } from "../api";
import { DecisionCards } from "../DecisionCards";

const cards = cardsJson as unknown as CardsView;
const demoCards = demoCardsJson as unknown as CardsView;

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

describe("cards with several comparisons", { timeout: 30_000 }, () => {
  it("the recorded view: the reference card waits for a person because of Drug B vs Control", () => {
    const card = cards.cards.find((c) => c.card.id === "card_refset")!;
    expect(card.card.status).toBe("open");
    expect(card.needs_human).toBe(true);
    expect(card.comparisons.map((c) => [c.label, c.flips])).toEqual([
      ["Drug A vs Control", false],
      ["Drug B vs Control", true],
    ]);
    expect(card.impact.plain).toBe("Calls that change with this choice: 1 in Drug B vs Control");
  });

  it("names each comparison, shows the options' effects there and says the choice is the study's", () => {
    vi.spyOn(api, "GET").mockImplementation((() => new Promise(() => {})) as never);
    render(wrap(<DecisionCards view={cards} workspaceKey="w" studyId={cards.study_id} />));
    const article = screen.getByRole("article", { name: /control genes/i });
    const line = within(article).getByTestId("card-comparisons");
    expect(line.textContent).toContain(
      "Drug B vs Control: this choice alone changes the call of TP53",
    );
    expect(line.textContent).toContain("Drug A vs Control (the first): it changes no call");
    expect(line.textContent).toContain("applies to the whole study");
    // every option shows its effects in the second comparison, the changed call marked
    const rows = article.querySelectorAll('[data-comparison="drug_b_vs_control"]');
    expect(rows.length).toBe(cards.cards.find((c) => c.card.id === "card_refset")!.options.length);
    const changed = Array.from(rows).filter((r) => r.textContent?.includes("(changes)"));
    expect(changed).toHaveLength(1);
    expect(changed[0]!.textContent).toContain("TP53");
  });

  it("a study with one comparison shows no per-comparison lines", () => {
    vi.spyOn(api, "GET").mockImplementation((() => new Promise(() => {})) as never);
    render(wrap(<DecisionCards view={demoCards} workspaceKey="w" studyId={demoCards.study_id} />));
    expect(screen.queryByTestId("card-comparisons")).toBeNull();
    expect(document.querySelector("[data-comparison]")).toBeNull();
  });
});

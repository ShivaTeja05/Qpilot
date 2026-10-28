/**
 * Several comparisons outside Results: Trace's call, the gene page's picker, the Run Review and
 * History, on the API's own views of a synthetic three-group study (Control, Drug A, Drug B;
 * ACTB lowered by Drug B) recorded from the real routes by src/test/recorded/record_compare2.py.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import cardsJson from "@/test/recorded/api-cards-compare.json";
import historyJson from "@/test/recorded/api-history-compare-b.json";
import resultsJson from "@/test/recorded/api-results-compare2.json";
import reviewJson from "@/test/recorded/api-review-compare.json";
import traceJson from "@/test/recorded/api-trace-compare-b.json";
import unitsJson from "@/test/recorded/api-units-compare-b.json";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import { GeneComparisons } from "@/features/gene/Comparisons";
import type { GeneUnits } from "@/features/gene/units";
import { Headline } from "@/features/report/RunReview";
import type { RunReviewView } from "@/features/report/api";
import type { GeneView as TraceGeneView } from "@/features/trace/api";
import { CallFacts } from "@/features/trace/GenePieces";
import type { CardsView, ResultsView } from "../api";
import { showComparison, useShownComparison } from "../comparison";

const results = resultsJson as unknown as ResultsView;
const trace = traceJson as unknown as TraceGeneView;
const units = unitsJson as unknown as GeneUnits;
const review = reviewJson as unknown as RunReviewView;
const history = historyJson as unknown as Schemas["HistoryView"];
const cards = cardsJson as unknown as CardsView;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("several comparisons in every section", { timeout: 30_000 }, () => {
  it("Trace's call: the corrected p with its name and q, the uncorrected p only as before correction", () => {
    const call = trace.trace.call;
    expect(trace.trace.comparison).toBe("drug_b_vs_control");
    expect(call.correction).toBe("Holm");
    render(<CallFacts call={call} labels={trace.trace.labels} />);
    expect(screen.getByText(/Corrected p \(Holm\)/)).toBeTruthy();
    const facts = screen.getByText(/p before correction/).textContent ?? "";
    expect(facts).toMatch(/^q /);
    expect(screen.queryByText(/^p · samples$/)).toBeNull();
    expect(trace.texts.summary!.plain).toContain("corrected p");
    expect(trace.texts.summary!.plain).toContain("p before correction");
  });

  it("the gene page's picker names the comparison shown and that the audit audits the first", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <GeneComparisons
        tabs={results.comparisons}
        value="drug_b_vs_control"
        onChange={onChange}
        audited
      />,
    );
    const block = screen.getByTestId("gene-comparisons");
    expect(block.textContent).toContain("Showing Drug B vs Control");
    expect(block.textContent).toContain("audits Drug A vs Control only");
    fireEvent.click(within(block).getByRole("radio", { name: /Drug A vs Control/ }));
    expect(onChange).toHaveBeenCalledWith("drug_a_vs_control");
    rerender(
      <GeneComparisons
        tabs={results.comparisons}
        value="drug_a_vs_control"
        onChange={onChange}
        audited
      />,
    );
    expect(screen.getByTestId("gene-comparisons").textContent).not.toContain("audits");
    // the per-unit view of the comparison shown: its two groups, corrected p and q
    expect(units.comparison).toBe("drug_b_vs_control");
    expect([units.groups.high.label, units.groups.rest.label]).toEqual(["Drug B", "Control"]);
    expect(units.p_adjusted).toBeGreaterThan(units.p ?? 1);
  });

  it("one choice of comparison is shared by every section of a study", async () => {
    function Probe({ study, name }: { study: string; name: string }) {
      const [id] = useShownComparison(study);
      return <span data-testid={name}>{id ?? "first"}</span>;
    }
    render(
      <>
        <Probe study="s1" name="results" />
        <Probe study="s1" name="trace" />
        <Probe study="s2" name="other" />
      </>,
    );
    expect(screen.getByTestId("trace").textContent).toBe("first");
    act(() => showComparison("s1", "drug_b_vs_control"));
    expect(screen.getByTestId("results").textContent).toBe("drug_b_vs_control");
    expect(screen.getByTestId("trace").textContent).toBe("drug_b_vs_control");
    expect(screen.getByTestId("other").textContent).toBe("first");
    act(() => showComparison("s1", null));
    expect(screen.getByTestId("trace").textContent).toBe("first");
  });

  it("the Run Review names every comparison with the p each call used", () => {
    render(
      <TooltipProvider>
        <Headline view={review} />
      </TooltipProvider>,
    );
    const list = screen.getByRole("list", { name: "Comparisons" });
    const items = within(list)
      .getAllByRole("listitem")
      .map((li) => li.textContent ?? "");
    expect(items[0]).toContain("Drug A vs Control (the first comparison)");
    expect(items[1]).toContain("Drug B vs Control: IL6 called up");
    expect(items[1]).toContain("corrected p");
    expect(items.at(-1)).toContain("Holm's correction");
  });

  it("History replays the comparison picked: the person's choice changes a call there", () => {
    expect(history.comparison).toBe("drug_b_vs_control");
    expect(history.comparisons.map((c) => c.id)).toEqual([
      "drug_a_vs_control",
      "drug_b_vs_control",
    ]);
    const last = history.steps.at(-1)!;
    expect(last.conclusions?.changed).toEqual(["TP53"]);
    expect(history.comparison_note).toContain("applies to every one");
    // the same choice is the card that waited for a person because of this comparison
    const card = cards.cards.find((c) => c.card.id === "card_refset")!;
    expect(card.comparisons.find((c) => c.flips)?.genes).toEqual(["TP53"]);
  });
});

/**
 * Several comparisons on the Results page, on the API's own views of a synthetic three-group
 * study (Control, Drug A, Drug B; recorded from the real engine by
 * src/test/recorded/record_compare.py): the picker, the side-by-side table, the gene table's
 * corrected p and q columns, and the proposal's words.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import comparisonsJson from "@/test/recorded/api-comparisons.json";
import resultsBJson from "@/test/recorded/api-results-compare-b.json";
import resultsJson from "@/test/recorded/api-results-compare.json";
import demoJson from "@/test/recorded/api-results.json";
import { comparisonWords } from "@/lib/vocab";
import type { ComparisonsView, ResultsView } from "../api";
import { ComparisonPicker, ComparisonsPanel, callWords } from "../ComparisonsPanel";
import { GenesPanel, NO_FILTER } from "../GenesPanel";

const view = comparisonsJson as unknown as ComparisonsView;
const results = resultsJson as unknown as ResultsView;
const resultsB = resultsBJson as unknown as ResultsView;
const demo = demoJson as unknown as ResultsView;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A media query answer: a phone when `phone`, else a wide screen. */
function screenIs(phone: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (q: string) =>
      ({
        matches: phone && q.includes("max-width: 639px"),
        media: q,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        onchange: null,
        dispatchEvent: () => false,
      }) as MediaQueryList,
  );
}

const genesPanel = (genes: ResultsView["genes"]) => (
  <GenesPanel
    genes={genes}
    filter={NO_FILTER}
    onFilter={() => {}}
    dimLabel={(d) => d}
    selected={null}
    onOpen={() => {}}
  />
);

describe("several comparisons", { timeout: 30_000 }, () => {
  it("the recorded views agree: one picker entry per comparison, the first shown by default", () => {
    expect(results.comparisons.map((c) => c.id)).toEqual(view.comparisons.map((c) => c.id));
    expect(results.comparison).toBe(view.comparisons[0]!.id);
    expect(resultsB.comparison).toBe("drug_b_vs_control");
    // the second comparison's table is its own: its groups and its calls
    expect(resultsB.summary.groups.map((g) => g.label)).toEqual(["Drug B", "Control"]);
    const calls = Object.fromEntries(resultsB.genes.map((g) => [g.gene, g.conclusion]));
    const fromView = Object.fromEntries(
      view.genes.map((g) => [g.gene, g.cells[1]?.conclusion ?? null]),
    );
    expect(calls).toEqual(Object.fromEntries(Object.entries(fromView).filter(([, c]) => c)));
    // the correction is the engine's: a corrected p is never below the uncorrected one
    for (const g of view.genes)
      for (const c of g.cells) if (c) expect(c.p_adjusted).toBeGreaterThanOrEqual(c.p - 1e-12);
  });

  it("the picker lists every comparison and switches", () => {
    const onChange = vi.fn();
    render(
      <ComparisonPicker
        tabs={results.comparisons}
        value={results.comparison!}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("radiogroup", { name: "Comparison shown" })).toBeTruthy();
    const tabs = screen.getAllByRole("radio");
    expect(tabs.map((t) => t.textContent)).toEqual(
      results.comparisons.map((c) => `${c.label}${c.n_up + c.n_down}`),
    );
    expect(tabs[0]!.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(tabs[1]!);
    expect(onChange).toHaveBeenCalledWith(results.comparisons[1]!.id);
  });

  it("no picker for a study with one comparison", () => {
    const { container } = render(
      <ComparisonPicker tabs={demo.comparisons ?? []} value="" onChange={() => {}} />,
    );
    expect(container.textContent).toBe("");
  });

  it("the side-by-side table shows every gene in every comparison, and says why", () => {
    const onShow = vi.fn();
    const onOpen = vi.fn();
    render(
      <ComparisonsPanel
        view={view}
        shown={view.comparisons[0]!.id}
        onShow={onShow}
        onOpen={onOpen}
      />,
    );
    const table = screen.getByRole("table");
    for (const c of view.comparisons) expect(within(table).getByText(c.label)).toBeTruthy();
    for (const g of view.genes) expect(within(table).getByText(g.gene)).toBeTruthy();
    // the header says the sizes and the calls of each comparison
    for (const c of view.comparisons)
      expect(
        within(table).getAllByText(new RegExp(`${callWords(c).replace(/,/g, ",")}`)).length,
      ).toBeGreaterThan(0);
    // the correction, the q-value and the unit not measured for one gene are said in words
    expect(screen.getByText(/corrected with Holm's method/)).toBeTruthy();
    expect(screen.getByText(/never used for a call/)).toBeTruthy();
    expect(screen.getByText(/Not measured for/)).toBeTruthy();
    // three groups, unpaired: Welch's ANOVA per gene, for orientation only
    expect(view.omnibus_groups).toHaveLength(3);
    expect(within(table).getByRole("columnheader", { name: /Any difference/ })).toBeTruthy();
    expect(screen.getByText(/for orientation only/)).toBeTruthy();
    fireEvent.click(within(table).getByRole("button", { name: /Drug B vs Control/ }));
    expect(onShow).toHaveBeenCalledWith("drug_b_vs_control");
    fireEvent.click(within(table).getByRole("button", { name: /IL6/ }));
    expect(onOpen).toHaveBeenCalledWith("IL6");
  });

  it("the gene table adds the corrected p and the q-value when the study has them", () => {
    screenIs(false);
    render(genesPanel(results.genes));
    expect(screen.getByRole("columnheader", { name: /Corrected p/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /q \(FDR\)/ })).toBeTruthy();
    expect(results.genes.every((g) => g.p_adjusted != null && g.q != null)).toBe(true);
    cleanup();
    render(genesPanel(demo.genes)); // recorded before q-values: no empty columns
    expect(screen.queryByRole("columnheader", { name: /Corrected p/ })).toBeNull();
  });

  it("on a phone each gene's card says its corrected p and q", () => {
    screenIs(true);
    render(genesPanel(results.genes));
    const list = screen.getByRole("list", { name: "All genes" });
    expect(within(list).getAllByText(/corrected p/)).toHaveLength(results.genes.length);
    expect(within(list).getAllByText(/^q /)).toHaveLength(results.genes.length);
  });

  it("a plan proposal reads as words, with the correction and the pairing", () => {
    const text = comparisonWords({
      group_a: "Drug A",
      group_b: "Control",
      comparisons: [
        { group_a: "Drug A", group_b: "Control" },
        { group_a: "Drug B", group_b: "Control" },
      ],
      pattern: "vs_control",
      control: "Control",
      correction: "holm",
      pair_by: "donor",
    });
    expect(text).toBe(
      "Compare each group with the control “Control” (2 comparisons: Drug A vs Control; " +
        "Drug B vs Control; the first is Drug A vs Control), with Holm's correction across " +
        "each gene's comparisons, paired by donor (a paired test within each donor)",
    );
    expect(comparisonWords({ group_a: "KO", group_b: "WT" })).toBe(
      "Compare group “KO” with group “WT” (fold change = KO relative to WT)",
    );
  });
});

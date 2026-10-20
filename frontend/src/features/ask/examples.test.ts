/** Example questions name only the study's own genes, firmest call first, audit questions only with an audit. */
import { describe, expect, it } from "vitest";
import results from "./__recorded__/results-examples.json";
import { exampleQuestions, MAX_EXAMPLES } from "./examples";
import { readResults, type ResultsForExamples } from "./useExamples";

// The demo study's results view, as GET /api/studies/{id}/results served it.
const { genes, references } = readResults(results as ResultsForExamples);
const holds = new Map(genes.map((g) => [g.gene, g.holds]));

function named(question: string): string[] {
  return genes
    .map((g) => g.gene)
    .filter((g) => question.includes(` ${g} `) || question.includes(` ${g}?`));
}

describe("exampleQuestions", () => {
  it("reads every gene and the references in use from the results view", () => {
    expect(genes).toHaveLength(results.genes.length);
    expect(references).toEqual(results.references.used);
  });

  it("asks about the firmest and the shakiest called gene of the study", () => {
    const [firm, shaky] = exampleQuestions({ genes, references, hasAudit: false }).map(
      (e) => e.question,
    );
    const [a] = named(firm!);
    const [b] = named(shaky!);
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    expect(a).not.toBe(b);
    expect(holds.get(a!)!).toBeGreaterThanOrEqual(holds.get(b!)!);
    // Both are called genes (up or down), never a no-call gene.
    for (const g of [a, b]) expect(genes.find((x) => x.gene === g)!.conclusion).not.toBe("none");
    // The shakiest is the called gene that holds least often.
    const least = Math.min(...genes.filter((g) => g.conclusion !== "none").map((g) => g.holds!));
    expect(holds.get(b!)).toBe(least);
  });

  it("adds the audit's questions, with a reference gene in use, only when there is an audit", () => {
    const without = exampleQuestions({ genes, references, hasAudit: false });
    const withAudit = exampleQuestions({ genes, references, hasAudit: true });
    expect(without.some((e) => e.source === "audit")).toBe(false);
    const whatIf = withAudit.find((e) => e.question.startsWith("What if I normalise to"));
    expect(whatIf?.source).toBe("audit");
    const ref = references.find((r) => whatIf!.question.includes(` ${r} alone`));
    expect(ref).toMatch(/^[A-Za-z][A-Za-z0-9-]*$/);
    expect(withAudit.length).toBeLessThanOrEqual(MAX_EXAMPLES);
  });

  it("falls back to a question about the study when no gene is known yet", () => {
    const qs = exampleQuestions({ genes: [], references: [], hasAudit: false });
    expect(qs).toHaveLength(1);
    expect(qs[0]!.question).toMatch(/this study/);
  });
});

/** Example questions name only the study's own genes, firmest call first, audit questions only with an audit. */
import { describe, expect, it } from "vitest";
import results from "@/test/recorded/results.json";
import { exampleQuestions, MAX_EXAMPLES, type GeneLine } from "./examples";

// The recorded StudyResult of the demo study (real engine output), as gene lines.
const genes: GeneLine[] = Object.entries(results.contrasts).map(([gene, c]) => ({
  gene,
  conclusion: c.conclusion === "up" || c.conclusion === "down" ? c.conclusion : "none",
  holds: (results.robustness as Record<string, { holds?: number }>)[gene]?.holds ?? null,
}));
const references = results.design.refs_primary;
const holds = new Map(genes.map((g) => [g.gene, g.holds]));

function named(question: string): string[] {
  return genes
    .map((g) => g.gene)
    .filter((g) => question.includes(` ${g} `) || question.includes(` ${g}?`));
}

describe("exampleQuestions", () => {
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
  });

  it("adds the audit's questions, with a reference gene of the study, only when there is an audit", () => {
    const without = exampleQuestions({ genes, references, hasAudit: false });
    const withAudit = exampleQuestions({ genes, references, hasAudit: true });
    expect(without.some((e) => e.source === "audit" || e.question.includes(references[0]!))).toBe(
      false,
    );
    const whatIf = withAudit.find((e) =>
      e.question.includes(`normalise to ${references[0]} alone`),
    );
    expect(whatIf?.source).toBe("audit");
    expect(withAudit.length).toBeLessThanOrEqual(MAX_EXAMPLES);
  });

  it("falls back to questions about the study when no gene is known yet", () => {
    const qs = exampleQuestions({ genes: [], references: [], hasAudit: false });
    expect(qs).toHaveLength(1);
    expect(qs[0]!.question).toMatch(/this study/);
  });
});

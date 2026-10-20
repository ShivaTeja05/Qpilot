/**
 * Example questions drawn from the open study: gene names come from its results, never from
 * this file. Each one is a question qPilot's templates can answer without a model.
 */

export interface GeneLine {
  gene: string;
  conclusion: "up" | "down" | "none";
  /** Share of the analyses qPilot checks (its choice grid) with the same call (0–1), when known. */
  holds: number | null;
}

export interface ExampleInput {
  genes: GeneLine[];
  /** Reference genes in use. */
  references: string[];
  /** The robustness audit has run on this study (what-if and "check first" questions). */
  hasAudit: boolean;
}

export const MAX_EXAMPLES = 4;

/** A question and the engine to ask it of (`auto`: qPilot picks). */
export interface Example {
  question: string;
  source: "auto" | "study" | "audit";
}

/** Up to {@link MAX_EXAMPLES} questions worth asking about this study, best first. */
export function exampleQuestions({ genes, references, hasAudit }: ExampleInput): Example[] {
  const called = genes.filter((g) => g.conclusion !== "none" && g.holds != null);
  const byHolds = [...called].sort(
    (a, b) => (b.holds ?? 0) - (a.holds ?? 0) || a.gene.localeCompare(b.gene),
  );
  const firm = byHolds[0];
  const shaky = byHolds.length > 1 ? byHolds[byHolds.length - 1] : undefined;
  const out: Example[] = [];
  const ask = (question: string, source: Example["source"] = "auto") =>
    out.push({ question, source });
  if (firm) ask(`Is the ${firm.gene} result robust?`);
  if (shaky && shaky.gene !== firm?.gene) ask(`What could change the call for ${shaky.gene}?`);
  const any = genes[0];
  if (!firm && any) ask(`Is the ${any.gene} result robust?`);
  if (hasAudit) {
    ask("What should I check first in this data?", "audit");
    // A reference named by a plain gene symbol reads best in a question (HMBS, not "SDHA(1)").
    const ref = references.find((r) => /^[A-Za-z][A-Za-z0-9-]*$/.test(r)) ?? references[0];
    if (ref) ask(`What if I normalise to ${ref} alone?`, "audit");
  }
  ask("How many plates, samples and genes are in this study?", "study");
  return out.slice(0, MAX_EXAMPLES);
}

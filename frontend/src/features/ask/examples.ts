/**
 * Example questions drawn from the open study: gene names come from its results, never from
 * this file. Each one is a question qPilot's templates can answer without a model.
 */

export interface GeneLine {
  gene: string;
  conclusion: "up" | "down" | "none";
  /** Share of reasonable analyses with the same call (0–1), when known. */
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

/** Up to {@link MAX_EXAMPLES} questions worth asking about this study, best first. */
export function exampleQuestions({ genes, references, hasAudit }: ExampleInput): string[] {
  const called = genes.filter((g) => g.conclusion !== "none" && g.holds != null);
  const byHolds = [...called].sort(
    (a, b) => (b.holds ?? 0) - (a.holds ?? 0) || a.gene.localeCompare(b.gene),
  );
  const firm = byHolds[0];
  const shaky = byHolds.length > 1 ? byHolds[byHolds.length - 1] : undefined;
  const out: string[] = [];
  if (firm) out.push(`Is the ${firm.gene} result robust?`);
  if (shaky && shaky.gene !== firm?.gene) out.push(`What could change the call for ${shaky.gene}?`);
  const any = genes[0];
  if (!firm && any) out.push(`Is the ${any.gene} result robust?`);
  if (hasAudit) {
    out.push("What should I check first in this data?");
    const ref = references[0];
    if (ref) out.push(`What if I normalise to ${ref} alone?`);
  }
  out.push("How many plates, samples and genes are in this study?");
  return out.slice(0, MAX_EXAMPLES);
}

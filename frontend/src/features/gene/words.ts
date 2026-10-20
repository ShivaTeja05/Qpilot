/**
 * The Gene section's words: decision dimensions and card kinds in plain words, the confidence
 * checks' names, and the sentence that says which way a gene moved. Numbers go through
 * `@/lib/format`; nothing here types a number.
 */
import { fold } from "@/lib/format";
import { asConclusion } from "@/lib/vocab";
import type { GeneRow, ResultsView } from "./api";

/** qPilot's decision dimensions (robustness impact keys) in words. */
export const DIMENSION: Record<string, { name: string; short: string }> = {
  refs: { name: "Which control genes to normalise to", short: "Control genes" },
  cut: { name: "Where to cut the comparison groups", short: "Group cut-off" },
  amp_call: { name: "Which curves count as amplified", short: "Amplification call" },
  undetermined: { name: "What to do with wells that never amplified", short: "Wells that never amplified" },
  efficiency: { name: "Which amplification efficiency to use", short: "Efficiency" },
  nondetect: { name: "What to do with a missing Cq", short: "Missing Cq" },
};

/** A Decision Card's kind → the dimension its choice changes (qpilot/mcp_server.py KIND_TO_DIMENSION). */
export const KIND_DIMENSION: Record<string, string> = {
  reference_set: "refs",
  group_cutoff: "cut",
  undetermined: "undetermined",
  amp_call: "amp_call",
};

export function dimensionName(dim: string): string {
  return DIMENSION[dim]?.name ?? dim.replace(/[_.]/g, " ");
}

/** A card's title: the server's, else its kind in words. */
export function cardTitle(card: { kind: string; title?: string | null }): string {
  if (card.title) return card.title;
  const dim = KIND_DIMENSION[card.kind];
  return dim ? dimensionName(dim) : card.kind.replace(/[_.]/g, " ");
}

/** The confidence checks (qpilot/core/confidence.py) by id. */
export const CHECK_NAME: Record<string, string> = {
  precision: "Precision",
  robustness: "Robustness",
  fragility: "Fragility",
  normalisation: "Normalisation",
  assay: "Assay",
  design_sensitivity: "Design",
};

export function checkName(id: string): string {
  return CHECK_NAME[id] ?? id.replace(/_/g, " ");
}

/** The two groups' labels: the high group first, then the rest. */
export function groupLabels(results: Pick<ResultsView, "summary"> | null | undefined): { hi: string; lo: string } {
  const groups = results?.summary?.groups ?? [];
  return { hi: groups[0]?.label ?? "the high group", lo: groups[1]?.label ?? "the rest" };
}

/** "3.32× higher in MYCN-high than in the rest" / "3.40× lower …" / "no change called". */
export function directionWords(gene: Pick<GeneRow, "fc" | "conclusion">, labels: { hi: string; lo: string }): string {
  const fc = gene.fc;
  if (!(fc > 0)) return "";
  const higher = fc >= 1;
  const size = fold(higher ? fc : 1 / fc);
  return `${size} ${higher ? "higher" : "lower"} in ${labels.hi} than in ${labels.lo}`;
}

/** The planned call in a short sentence. */
export function callSentence(gene: Pick<GeneRow, "conclusion">): string {
  const c = asConclusion(gene.conclusion);
  if (c === "up") return "Called up with the planned analysis";
  if (c === "down") return "Called down with the planned analysis";
  return "No change called with the planned analysis";
}

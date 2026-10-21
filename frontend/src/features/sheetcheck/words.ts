/**
 * The Sheet check's words: the known slips and methods a finding can match (path ids of
 * `qpilot/qpcr/sheetcheck.PATHS`), what a hand-over's causes mean (`CAUSE_LABELS`), and the
 * statuses of findings, columns and mapping guesses, in short plain phrases (methods/sheetcheck.md).
 */
import type { SheetColumnCheckView, SheetColumnView, SheetFindingView, SheetRole } from "./api";

/** A known slip (or method) that reproduces a column, in a few words. */
export const SLIP_WORDS: Record<string, string> = {
  sign_inverted: "the sign of ΔΔCq inverted in the exponent",
  exponent_twice: "the exponent applied twice (a fold change used as an exponent again)",
  no_reference: "no reference gene subtracted",
  wrong_reference: "a reference gene other than the one declared",
  arith_mean_fc: "the arithmetic mean of fold changes, not the geometric mean",
  stats_on_fc: "the t test run on fold changes, not on ΔCq",
  wells_as_n: "technical wells counted as biological replicates",
  row_shift: "values taken from a neighbouring row (a copy-paste offset)",
  pfaffl: "the Pfaffl ratio with the efficiencies given (a method, not a slip)",
  livak_per_unit: "the textbook Livak path",
};

/** A path id in words (an id the page does not know reads as its own words). */
export function slipWords(id: string): string {
  return SLIP_WORDS[id] ?? id.replaceAll("_", " ");
}

/** What visibly differs between the sheet and qPilot's analysis of the study. */
export const CAUSE_WORDS: Record<string, string> = {
  efficiency: "each well's own efficiency in qPilot",
  normaliser: "another set of reference genes",
  sample_set: "other group sizes",
};

export function causeWords(id: string): string {
  return CAUSE_WORDS[id] ?? id.replaceAll("_", " ");
}

type FindingStatus = SheetFindingView["status"];
type ColumnStatus = SheetColumnCheckView["status"];

/** A finding's status: how many known paths reproduce it. */
export const FINDING_STATUS: Record<FindingStatus, { word: string; detail: string }> = {
  explained: {
    word: "Named cause",
    detail: "One known slip reproduces every cell that differs here.",
  },
  ambiguous: {
    word: "More than one cause fits",
    detail: "Several known slips reproduce it; the sheet alone cannot tell which.",
  },
  unexplained: {
    word: "No known cause",
    detail: "No known slip reproduces it; look at the cells by hand.",
  },
};

/** A recomputed column's status. */
export const COLUMN_STATUS: Record<ColumnStatus, string> = {
  reproduced: "Reproduced",
  differs: "Differs",
  follows: "Follows an earlier difference",
  not_checked: "Not checked",
};

/** Where a column's guess came from. */
export const BASIS_WORDS: Record<SheetColumnView["basis"], string> = {
  header: "its header",
  content: "its values",
  user: "set by you",
};

/** How the sheet is laid out. */
export const LAYOUT_WORDS: Record<"wide" | "long", string> = {
  wide: "wide: one Cq column per gene",
  long: "long: a gene column, one row per gene and sample",
};

/** Roles that belong to one gene (the column's gene is kept when its role changes). */
const GENE_ROLES = new Set<SheetRole>([
  "cq",
  "mean_cq",
  "dcq",
  "ddcq",
  "fc",
  "mean_fc",
  "sd",
  "sem",
  "p",
]);

export function roleHasGene(role: SheetRole): boolean {
  return GENE_ROLES.has(role);
}

/** "MYC, GAPDH and ACTB". */
export function listWords(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

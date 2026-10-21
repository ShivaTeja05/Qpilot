/**
 * The card's own words: where a quoted text came from, what its flags mean, what each engine
 * rule can refute, and plain labels for the numbers a check reports. Taken from qPilot's own
 * wording (`qpilot/qpcr/design_checks.py`, `qpilot/core/firewall.py`, `qpilot/studio_state.py`).
 */
import { count, MINUS, MISSING } from "@/lib/format";

/** One piece of quarantined file text (`GET /api/sessions/{sid}/quarantine`). */
export interface QuarantineEntry {
  text_id: string;
  /** e.g. `rdml:sample.id`, `sheet:samples.xlsx!Sheet1!B2`, `prism:ODC1.csv!A3`. */
  origin: string;
  /** The original text. Rendered as text only; never obeyed, never computed with. */
  value: string;
  /** `instruction_like`, `date_like`, `email_like`, `long`, `control_chars`. */
  flags: string[];
}

const RDML_ORIGIN: Record<string, string> = {
  "sample.id": "the name of a sample in the RDML file",
  "sample.description": "a sample's description in the RDML file",
  "target.id": "the name of a target (assay) in the RDML file",
  "target.description": "a target's description in the RDML file",
  "run.id": "the name of a run (plate) in the RDML file",
  "experiment.id": "the name of an experiment in the RDML file",
};

/** Where a quoted text came from, in words: "the name of a sample in the RDML file". */
export function originWords(origin: string): string {
  const colon = origin.indexOf(":");
  const source = colon >= 0 ? origin.slice(0, colon) : origin;
  const where = colon >= 0 ? origin.slice(colon + 1) : "";
  if (source === "rdml") return RDML_ORIGIN[where] ?? `the RDML file (${where})`;
  if (source === "sheet") {
    const [file, sheet, cell] = where.split("!");
    if (file && sheet && cell) return `cell ${cell} of sheet “${sheet}” in ${file}`;
    return `the sample sheet (${where})`;
  }
  if (source === "prism") {
    const [file, cell] = where.split("!");
    return cell ? `cell ${cell} of ${file} that Prism sent back` : `${where}, sent back from Prism`;
  }
  if (source === "sentence") return "the sentence you gave about the experiment";
  return origin;
}

/** What a firewall flag means, for the person reading the quote. */
export const FLAG_WORDS: Record<string, string> = {
  instruction_like: "reads like an instruction",
  date_like: "looks like a date",
  email_like: "looks like an email address",
  long: "unusually long",
  control_chars: "contains invisible control characters (shown as ⟨U+…⟩)",
};

export const INSTRUCTION_TEXT =
  "This text reads like an instruction. It is shown as data and is never obeyed: no model, agent or rule acts on it.";

// Control characters and bidirectional overrides can hide or reorder what a text says.
// eslint-disable-next-line no-control-regex
const INVISIBLE =
  /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/g;

/** A quoted text with invisible and direction-changing characters made visible. */
export function visibleText(value: string): string {
  return value.replace(
    INVISIBLE,
    (c) => `⟨U+${c.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}⟩`,
  );
}

/** What each engine rule can refute (the method card's one line). */
export const RULE_WORDS: Record<string, string> = {
  "D-SERIES":
    "A dilution series must fall on a line of Cq against log10 quantity (R² of at least 0.98), and a standard needs wells that amplified. Efficiency outside 90–110 % is only a warning.",
  "D-NTC":
    "A no-template, no-RT or no-amplification control must not amplify within five cycles of the plate's study samples for that target.",
  "D-REP":
    "Technical replicates must agree within the Poisson-aware tolerance 2.1/ln(E) · √(0.15² + 1/N); only a warning when the copy number is unknown.",
  "D-SYMBOL": "A gene symbol must be the approved HGNC symbol for the target's name.",
  "D-COVER":
    "Every well must end up with exactly one role, and a role must name a sample or well that exists.",
  "D-NGUARD":
    "Each group of a comparison needs at least two biological units (otherwise no p-value is given).",
  "D-CURVE":
    "The well's curve as LinRegPCR fitted it (an exponential phase, a plateau, a quantity).",
};

/** A rule's short name, shown on its chip next to the id. */
export const RULE_TITLE: Record<string, string> = {
  "D-SERIES": "Dilution series",
  "D-NTC": "Negative controls",
  "D-REP": "Replicates",
  "D-SYMBOL": "Gene symbol",
  "D-COVER": "One role per well",
  "D-NGUARD": "Group sizes",
  "D-CURVE": "The curve",
};

/** Plain labels for the numbers and fields engine checks report (`ProposalCheck.details`). */
const DETAIL_LABEL: Record<string, string> = {
  amplification_factor: "amplification factor (E)",
  class: "what was found",
  copies: "copies",
  copies_known: "copy number known",
  cq: "Cq",
  eff_indiv: "efficiency of this well",
  efficiency: "efficiency",
  efficiency_fraction_of_doubling: "efficiency (share of a doubling)",
  efficiency_range: "expected efficiency",
  efficiency_warning: "efficiency outside 90–110 %",
  error: "error",
  family_series: "series of the same family",
  gap_cycles: "cycles after the study samples",
  fits: "standard-curve fits",
  intercept: "intercept",
  invalid_quantities: "invalid quantities",
  judged_at_known_copies: "judged at a known copy number",
  k_cycles: "cycles a control must stay behind",
  levels: "dilution levels",
  levels_used: "levels used",
  levels_without_amplification: "levels without amplification",
  linregpcr_amplification: "LinRegPCR saw amplification",
  linregpcr_plateau: "LinRegPCR saw a plateau",
  linregpcr_quantity: "LinRegPCR gave a quantity",
  min_gap_cycles: "smallest gap to the study samples (cycles)",
  min_units: "biological units needed per group",
  missing_samples: "samples not found",
  n: "replicates",
  n_amplified: "wells amplified",
  n_amplified_no_reference: "wells amplified with nothing to compare to",
  n_clean: "clean wells",
  n_cq_without_amplification_call: "wells with a late Cq but no amplification",
  n_fits: "fits",
  n_fits_contradicted: "fits that refute it",
  n_late: "wells amplifying late (fine for a control)",
  n_late_cq_not_counted: "late Cqs not counted",
  n_level_amplified: "wells of its dilution level amplified",
  n_level_wells: "wells of its dilution level",
  n_like_sample: "wells amplifying like a study sample",
  n_over_tolerance: "replicate sets wider than the tolerance",
  n_over_tolerance_at_known_copies: "of those, at a known copy number",
  n_sets: "replicate sets",
  n_sets_at_known_copies: "replicate sets at a known copy number",
  n_subject_wells: "wells of this subject",
  n_units_a: "biological units in the first group",
  n_units_b: "biological units in the second group",
  n_wells: "wells",
  n_wells_used: "wells used",
  n_with_cq: "wells with a Cq",
  n_with_several_roles: "wells with more than one role",
  n_without_role: "wells without a role",
  name_candidates: "symbols matching the target's name",
  name_status: "the target's name",
  non_gene: "not a gene",
  over_tolerance: "replicate sets wider than the tolerance",
  r2: "R²",
  r2_max: "best R² of a plate",
  r2_min_required: "smallest R² accepted",
  range: "Cq range",
  run_id: "plate",
  sample: "sample",
  sample_found: "sample found in the file",
  sample_type: "declared type",
  slope: "slope",
  status: "result",
  std: "standard",
  symbol_candidates: "approved symbols for this name",
  symbol_status: "the symbol",
  target: "target",
  tolerance: "tolerance",
  tolerance_formula: "tolerance formula",
  unknown_median_cq: "median Cq of the study samples",
  warning: "a warning only",
  well: "well",
  wells_with_several_roles: "wells with more than one role",
  wells_with_signal: "wells with a signal",
};

/** A check's field name in words (`n_with_cq` → "wells with a Cq"). */
export function detailLabel(key: string): string {
  const known = DETAIL_LABEL[key];
  if (known) return known;
  const words = key.replace(/_/g, " ").trim();
  return words.startsWith("n ") ? `number of ${words.slice(2)}` : words;
}

/** A value from a check or a consequence, as text: numbers to 4 significant digits, yes/no. */
export function detailValue(value: unknown): string {
  if (value === null || value === undefined) return MISSING;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return detailNumber(value);
  if (typeof value === "string") return value.replace(/_/g, " ");
  if (Array.isArray(value)) {
    const shown = value.slice(0, 12).map(detailValue).join(", ");
    return value.length > 12 ? `${shown} … (${count(value.length)} in all)` : shown || MISSING;
  }
  return JSON.stringify(value);
}

/** A number from a check: integers grouped, others to 4 significant digits, tiny ones as ×10⁻ⁿ. */
export function detailNumber(x: number): string {
  if (!Number.isFinite(x)) return MISSING;
  if (Number.isInteger(x)) return count(x);
  const a = Math.abs(x);
  if (a !== 0 && a < 1e-3) {
    const [mantissa = "", exponent = "0"] = x.toExponential(1).split("e");
    return `${mantissa.replace("-", MINUS)} × 10${superscript(Number(exponent))}`;
  }
  const text = a >= 1000 ? x.toFixed(1) : String(Number(x.toPrecision(4)));
  return text.replace("-", MINUS);
}

const SUPER = "⁰¹²³⁴⁵⁶⁷⁸⁹";
function superscript(n: number): string {
  const digits = String(Math.abs(n))
    .split("")
    .map((d) => SUPER[Number(d)])
    .join("");
  return (n < 0 ? "⁻" : "") + digits;
}

/** The `class` values engine checks give a control well, in words. */
export const SIGNAL_CLASS: Record<string, string> = {
  clean: "no signal",
  late: "amplified late (fine for a control)",
  like_sample: "amplified like a study sample",
  cq_without_amplification_call: "a late Cq, but no amplification",
  amplified_no_reference: "amplified, with nothing to compare to",
};

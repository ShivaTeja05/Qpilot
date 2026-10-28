/**
 * The Audit section's fixed wording: what the audit is, its steps, what each refusal means and
 * what to do, and its limits. Method words only: every number on the screen comes from the API.
 * Wording follows qsim's own (`app.py`, `app_lab.py`) and docs/integration.md.
 */

/**
 * The analysis decisions the audit varies, in lab order (ids as the engine names them): eight, and
 * a ninth (`replicates`, how a unit's replicate wells are combined) for a design with three or
 * more wells per unit and gene.
 */
export const DECISION_ORDER = [
  "efficiency",
  "flagged",
  "late_cq",
  "nondetect",
  "replicates",
  "refs",
  "cut",
  "test",
  "multiplicity",
] as const;

/** The decisions in words, for the "not run" explanation (before any view is available). */
export const DECISION_WORDS = [
  "the efficiency model",
  "flagged wells",
  "the late-Cq cut-off",
  "non-detects",
  "the reference genes",
  "the group cut-off",
  "the statistical test",
  "the multiple-testing correction",
];

/** The ninth decision, varied only for a design with three or more wells per unit and gene. */
export const REPLICATE_DECISION_WORDS = "how replicate wells are combined";

/** The decisions a study's audit varies, in words, and how many ("eight" or "nine"). */
export function decisionWords(replicates: boolean): { count: string; words: string } {
  const list = replicates
    ? [...DECISION_WORDS.slice(0, 4), REPLICATE_DECISION_WORDS, ...DECISION_WORDS.slice(4)]
    : DECISION_WORDS;
  return {
    count: replicates ? "nine" : "eight",
    words: list.join(", ").replace(/, ([^,]*)$/, " and $1"),
  };
}

/** How the audit treats technical replicates (the method; the study's own numbers come from the API). */
export const REPLICATES_METHOD =
  "Technical replicates are combined per biological unit exactly as qPilot combines them (the mean of the wells' log2 amounts, wells without a value left out) and are never counted as samples. With three or more wells per value, the audit also tries the middle well and leaving out one well outside the expected replicate spread (the Run Gate's G-REP rule).";

/** The option tiers, in the order the what-if lab groups them. */
export const TIERS = [
  { key: "your planned analysis", raw: "prespecified", label: "Your planned analysis" },
  { key: "reasonable alternative", raw: "defensible", label: "Reasonable alternatives" },
  { key: "common shortcut", raw: "common_practice", label: "Common shortcuts" },
] as const;

/** A tier from either spelling the views use ("defensible" or "reasonable alternative"). */
export function tierOf(tier: string): (typeof TIERS)[number] | undefined {
  return TIERS.find((t) => t.key === tier || t.raw === tier);
}

/**
 * The audit, from the stored study to the bound folder (docs/integration.md "The simulator
 * adapter"). Each step can stop it, and says so.
 */
export const AUDIT_STEPS = [
  {
    title: "Rebuild",
    text: "Your confirmed study is rebuilt read-only from the store: the per-well table after the design, the wells a person excluded, the amplification rule and the groups.",
  },
  {
    title: "Reproduce qPilot",
    text: "With every choice as planned, the audit must give qPilot's own fold change, p-value and call for every gene. If any gene differs, it refuses rather than describe other numbers.",
  },
  {
    title: "Lock the plan",
    text: "The planned analysis is written down (lock.json) before any alternative is run.",
  },
  {
    title: "Every combination",
    text: "Every combination of the decisions' options is run, and each gene's call is read in each.",
  },
  {
    title: "Verdicts",
    text: "Each gene gets a verdict from how often the audit's reasonable set gives the same call, how few samples change the call and how close it is to the line a call needs.",
  },
  {
    title: "Bind",
    text: "The audit is written beside the record (never inside it) with a checksum for every file, the study, the input file and the decision chain it describes.",
  },
] as const;

/** Stated limits (the old screen's, with the integration's). */
export const LIMITS = [
  "A verdict is only as broad as the choices varied: the Cq method, baseline correction and paired designs are not varied.",
  "Analysis choices are audited exhaustively; the plate itself is not re-simulated. Agreement across analyses does not fix small-sample noise.",
  REPLICATES_METHOD,
  "The audit describes the study as it was when it ran. A decision made after it is not in it until the audit is run again.",
  "Research use only. Common shortcuts are shown but kept out of the verdicts.",
];

/** Why each method check may be missing from an audit, and what it would show. */
export const NOT_RUN_WORDS: Record<string, string> = {
  "planted faults":
    "Planted faults: faults put into real data on purpose, to see whether the audit catches the ones that change a call.",
  "small experiments drawn from the data":
    "Small experiments drawn from the data: how often small studies with no real difference get a call, with one analysis against requiring the call to hold across the audit's reasonable set.",
  "known answers":
    "Known answers: a dilution series with known ratios, to measure each efficiency choice's error against the truth.",
};

export const STATUS_WORDS = {
  not_applicable: {
    title: "The audit does not apply to this study",
    todo: "Your results and Decision Cards are unaffected. The Results section still shows how often each gene's call holds across qPilot's choice grid.",
  },
  refused: {
    title: "The audit refused this study",
    todo: "Nothing is wrong with your results: the audit stops when it cannot reproduce them exactly, rather than describe other numbers. Open Results to re-read the study, then run the audit again. If it still refuses, keep the Analysis Record and report it.",
  },
  unavailable: {
    title: "The Decision Simulator is not installed",
    todo: "The audit runs in the Decision Simulator, an optional part of qPilot. Install it in qPilot's environment from a clone of the repository, then restart qpilot app.",
  },
} as const;

export const INSTALL_COMMAND = "pip install -e '.[sim]'";

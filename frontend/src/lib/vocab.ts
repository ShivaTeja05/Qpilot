/**
 * The page's words for the engine's vocabularies: conclusions, audit verdicts, confidence
 * levels, Studio stages, engine checks, sample roles, and proposals in plain words. They follow
 * qPilot's own wording (`qpilot/studio_state.py`, `sim/src/qsim/app.py`) so the page, the CLI
 * and the record say the same thing.
 */
import type { Schemas } from "@/api/client";

export type Conclusion = "up" | "down" | "none";
export type Level = "High" | "Moderate" | "Low" | "Very low";
export type Verdict =
  | "solid"
  | "holds with caveats"
  | "depends on your choices"
  | "fragile"
  | "check data first"
  | "no call";
export type StageName = Schemas["StageView"]["stage"];
export type Proposal = Schemas["Proposal"];
export type CheckStatus = Schemas["ProposalCheck"]["status"];

/**
 * A mark: a shape, a colour token and a word, so meaning is never carried by colour alone
 * (docs/app.md §5). Drawn by `Glyph` / `GlyphMark` from `@/ui` in tags, legends and charts.
 */
export type Shape =
  | "circle"
  | "half"
  | "diamond"
  | "triangle"
  | "square-alert"
  | "ring"
  | "up"
  | "down"
  | "dash"
  | "cross";

export interface Mark {
  shape: Shape;
  /** A CSS colour from the tokens (`var(--up)`), never a raw hex. */
  tone: string;
  /** The word the mark stands for ("Up", "Fragile", "Moderate"). */
  label: string;
}

// ---- conclusions (qPilot's call rule: up or down only if p < 0.05 and at least 2-fold) --------

export const CONCLUSION: Record<
  Conclusion,
  Mark & { glyph: string; word: string; long: string; token: string }
> = {
  up: {
    shape: "up",
    tone: "var(--up)",
    label: "Up",
    glyph: "▲",
    word: "up",
    long: "called up",
    token: "up",
  },
  down: {
    shape: "down",
    tone: "var(--down)",
    label: "Down",
    glyph: "▼",
    word: "down",
    long: "called down",
    token: "down",
  },
  none: {
    shape: "dash",
    tone: "var(--none)",
    label: "No call",
    glyph: "—",
    word: "no call",
    long: "no change called",
    token: "none",
  },
};
export const CONCLUSIONS: Conclusion[] = ["up", "down", "none"];

/**
 * A conclusion from any spelling the engine or the audit uses: "up", "down", "none", "no call",
 * "called up (higher in …)", "called down", "no change called".
 */
export function asConclusion(value: unknown): Conclusion {
  const v = String(value ?? "")
    .trim()
    .toLowerCase();
  if (v === "up" || v.startsWith("called up")) return "up";
  if (v === "down" || v.startsWith("called down")) return "down";
  return "none";
}

// ---- confidence levels (ordinal, never a probability) -----------------------------------------

export const LEVELS: Level[] = ["High", "Moderate", "Low", "Very low"];
export const LEVEL: Record<Level, Mark & { bars: number; token: string }> = {
  High: { shape: "circle", tone: "var(--l-high)", label: "High", bars: 4, token: "l-high" },
  Moderate: {
    shape: "half",
    tone: "var(--l-moderate)",
    label: "Moderate",
    bars: 3,
    token: "l-moderate",
  },
  Low: { shape: "ring", tone: "var(--l-low)", label: "Low", bars: 2, token: "l-low" },
  "Very low": {
    shape: "cross",
    tone: "var(--l-verylow)",
    label: "Very low",
    bars: 1,
    token: "l-verylow",
  },
};

export function asLevel(value: unknown): Level | null {
  const v = String(value ?? "")
    .toLowerCase()
    .replace(/[_-]/g, " ");
  return LEVELS.find((l) => l.toLowerCase() === v) ?? null;
}

// ---- the audit's verdicts ---------------------------------------------------------------------

/** The audit's six verdicts, in reading order (best first). */
export const VERDICTS: Verdict[] = [
  "solid",
  "holds with caveats",
  "depends on your choices",
  "fragile",
  "check data first",
  "no call",
];
/** The verdicts most urgent first (qsim.verdict.ORDER): for queues and strips. */
export const VERDICT_ORDER: Verdict[] = [
  "check data first",
  "fragile",
  "depends on your choices",
  "holds with caveats",
  "solid",
  "no call",
];
/** Each verdict's mark (the old audit page's shapes) and token. */
export const VERDICT: Record<Verdict, Mark & { token: string }> = {
  solid: { shape: "circle", tone: "var(--v-solid)", label: "Solid", token: "v-solid" },
  "holds with caveats": {
    shape: "half",
    tone: "var(--v-caveats)",
    label: "Holds with caveats",
    token: "v-caveats",
  },
  "depends on your choices": {
    shape: "diamond",
    tone: "var(--v-depends)",
    label: "Depends on your choices",
    token: "v-depends",
  },
  fragile: { shape: "triangle", tone: "var(--v-fragile)", label: "Fragile", token: "v-fragile" },
  "check data first": {
    shape: "square-alert",
    tone: "var(--v-check)",
    label: "Check data first",
    token: "v-check",
  },
  "no call": {
    shape: "ring",
    tone: "var(--v-nocall)",
    label: "No change called",
    token: "v-nocall",
  },
};

export function isVerdict(v: unknown): v is Verdict {
  return typeof v === "string" && v in VERDICT;
}

export function asVerdict(value: unknown): Verdict | null {
  const v = String(value ?? "")
    .toLowerCase()
    .replace(/_/g, " ");
  if ((VERDICTS as string[]).includes(v)) return v as Verdict;
  const alias: Record<string, Verdict> = {
    caveats: "holds with caveats",
    depends: "depends on your choices",
    check: "check data first",
    nocall: "no call",
    "no change called": "no call",
  };
  return alias[v] ?? null;
}

export const STAGE_LABEL: Record<StageName, string> = {
  design: "Design",
  curves: "Curves",
  choices: "Choices",
  prism: "Prism draft",
  roundtrip: "Round trip",
};

export const CHECK: Record<
  CheckStatus,
  { word: string; meaning: string; tone: "ok" | "danger" | "neutral" }
> = {
  consistent: {
    word: "Consistent",
    meaning: "The engine found nothing that refutes it (a check can refute, never prove).",
    tone: "ok",
  },
  contradicted: {
    word: "Contradicted",
    meaning: "The engine's check refutes it; accepting it anyway needs a reason.",
    tone: "danger",
  },
  cannot_check: {
    word: "Cannot check",
    meaning: "No engine check applies; decide it on the evidence.",
    tone: "neutral",
  },
};

export const STATUS_WORDS: Record<Proposal["status"], string> = {
  proposed: "Waiting for you",
  accepted: "Accepted",
  edited: "Edited and accepted",
  rejected: "Rejected",
  superseded: "Replaced by a newer proposal",
};

/** RDML sample types, in words. */
export const ROLE_WORDS: Record<string, string> = {
  unkn: "a study sample",
  std: "a standard of known quantity",
  ntc: "a no-template control",
  nrt: "a no-reverse-transcription control",
  nac: "a no-amplification control",
  pos: "a positive control",
  opt: "an optical calibrator",
  ntp: "a no-target-present control",
};

/** Short role labels for legends and chips. */
export const ROLE_SHORT: Record<string, string> = {
  unkn: "Sample",
  std: "Standard",
  ntc: "NTC",
  nrt: "No-RT",
  nac: "NAC",
  pos: "Positive",
  opt: "Calibrator",
  ntp: "NTP",
};

export const PRESET_WORDS: Record<string, string> = {
  vermeulen_expression_defined:
    "the published design of the Vermeulen neuroblastoma dataset: tumours compared by MYCN expression (an expression-defined split, not a clinical call), normalised to the original study's five reference genes",
};

/** An amplification-call rule id in words. */
export function ruleWords(rule: unknown): string {
  const r = String(rule);
  if (r === "linregpcr") return "LinRegPCR's call (it found an exponential phase and a quantity)";
  if (r === "learned") return "the Curve Judge's call (a model that reads the curve's shape)";
  const m = /^cq_le_(\d+(?:\.\d+)?)$/.exec(r);
  if (m) return `a Cq cut-off: a Cq above ${m[1]} counts as not amplified`;
  return `the rule “${r}”`;
}

/** Short label of an amplification-call rule: `LinRegPCR`, `Cq ≤ 35`, `Curve Judge`. */
export function ruleLabel(rule: unknown): string {
  const r = String(rule);
  if (r === "linregpcr") return "LinRegPCR";
  if (r === "learned") return "Curve Judge";
  const m = /^cq_le_(\d+(?:\.\d+)?)$/.exec(r);
  return m ? `Cq ≤ ${m[1]}` : r;
}

/** The Import Trust card's options in words (`qpilot/io/trust.py` LABELS, lower-cased). */
export const TRUST_WORDS: Record<string, string> = {
  reexport_raw: "re-export the raw curves",
  analyse_as_is: "analyse the curves as they are",
  cq_only: "use the instrument's Cq values only",
};

/** The efficiency models (`qpilot/qpcr/axes`, the `efficiency` choice) in words. */
export const EFFICIENCY_MODEL_WORDS: Record<string, string> = {
  linregpcr: "LinRegPCR's mean efficiency of the amplicon on each plate",
  per_well: "each well's own efficiency",
  amplicon_mean: "one efficiency per amplicon over all its plates",
  assumed_2: "efficiency assumed to be 2.0 (100 %)",
  standard_curve: "efficiency from the plate's dilution series",
};
const AXIS_QUESTION: Record<string, string> = {
  efficiency: "which efficiency turns Cq into quantity",
};

type Payload = Record<string, unknown>;
const str = (v: unknown) => String(v ?? "?");

/**
 * A comparison proposal in words: one comparison, or several (each group vs a control, every
 * pair, or a person's list) with the correction and any pairing. Mirrors qpilot/studio_state.py.
 */
export function comparisonWords(d: Payload): string {
  const a = str(d.group_a);
  const b = str(d.group_b);
  let text = `Compare group “${a}” with group “${b}” (fold change = ${a} relative to ${b})`;
  const listed = Array.isArray(d.comparisons) ? (d.comparisons as Payload[]) : [];
  const others = listed.filter((c) => c && !(c.group_a === d.group_a && c.group_b === d.group_b));
  if (others.length) {
    const head =
      d.pattern === "vs_control" && d.control
        ? `Compare each group with the control “${str(d.control)}”`
        : d.pattern === "all_pairs"
          ? "Compare every pair of groups"
          : "Compare these groups";
    const pairs = [{ group_a: a, group_b: b }, ...others]
      .map((c) => `${str(c.group_a)} vs ${str(c.group_b)}`)
      .join("; ");
    text = `${head} (${others.length + 1} comparisons: ${pairs}; the first is ${a} vs ${b})`;
    text +=
      (d.correction ?? "holm") === "holm"
        ? ", with Holm's correction across each gene's comparisons"
        : ", with no correction for several comparisons";
  }
  if (d.pair_by)
    text += `, paired by ${str(d.pair_by)} (a paired test within each ${str(d.pair_by)})`;
  return text;
}

const DESCRIBERS: Record<string, (subject: string, d: Payload) => string> = {
  "design.preset": (_s, d) => {
    const preset = str(d.preset);
    const known = PRESET_WORDS[preset];
    return `Use the built-in design “${preset}”${known ? `: ${known}` : ""}`;
  },
  "design.well_role": (s, d) => {
    const role = str(d.role);
    return `Treat sample ${s} as ${ROLE_WORDS[role] ?? `role “${role}”`}`;
  },
  "design.group": (s, d) => `Put sample ${s} in group “${str(d.group)}”`,
  "design.bio_unit": (s, d) =>
    `Sample ${s} belongs to biological unit “${str(d.biological_unit)}”: its wells are technical replicates of that unit and are never counted as separate n`,
  "design.target_role": (s, d) =>
    d.role === "ref"
      ? `Use target ${s} as a reference gene (other genes are normalised to it)`
      : d.role === "toi"
        ? `Treat target ${s} as a gene of interest`
        : `Give target ${s} the role “${str(d.role)}”`,
  "design.gene_symbol": (s, d) => `Target ${s} is the gene with the HGNC symbol ${str(d.symbol)}`,
  "design.comparison": (_s, d) => comparisonWords(d),
  "design.pair": (s, d) =>
    d.pair
      ? `Sample ${s} belongs to ${str(d.by ?? "pair")} “${str(d.pair)}”: it is paired with that ${str(d.by ?? "pair")}'s samples in the other groups`
      : `Sample ${s} is not paired with samples of the other groups`,
  "design.dilution_series": (s, d) => {
    const samples =
      d.samples && typeof d.samples === "object" ? (d.samples as Record<string, unknown>) : {};
    const names = Object.keys(samples);
    if (!names.length) throw new Error("no samples");
    const q = Object.values(samples)
      .map(Number)
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
    const span = names.length > 1 ? `${names[0]} … ${names[names.length - 1]}` : names.join(", ");
    const quantities = q.length ? `, quantities ${q[0]} to ${q[q.length - 1]}` : "";
    return `Samples ${span} (${names.length} in all, experiment ${str(d.experiment_id)}) form a dilution series ${s}${quantities}`;
  },
  "curve.call_rule": (_s, d) => `Count a well as amplified by ${ruleWords(d.rule)}`,
  "choice.axis": (s, d) => {
    const question = AXIS_QUESTION[s];
    if (!question || !Array.isArray(d.options) || !d.options.length) throw new Error("not an axis");
    const words = (o: unknown) => EFFICIENCY_MODEL_WORDS[String(o)] ?? String(o);
    const [primary, ...others] = d.options;
    if (!others.length) return `Stop testing ${question}; keep ${words(primary)} only`;
    return `Also test ${question}: ${others.map(words).join("; ")} (besides ${words(primary)}, the analysis in use)`;
  },
  "curve.well_call": (s, d) => {
    if (typeof d.amplified !== "boolean") throw new Error("amplified must be boolean");
    return `Count well ${s} as ${d.amplified ? "amplified" : "not amplified (no usable curve)"}`;
  },
  "curve.exclude_well": (s, d) => {
    if (typeof d.excluded !== "boolean") throw new Error("excluded must be boolean");
    return d.excluded
      ? `Leave well ${s} out of the analysis`
      : `Put well ${s} back into the analysis`;
  },
  "curve.import_trust": (_s, d) => {
    const words = TRUST_WORDS[String(d.option)];
    if (!words) throw new Error("not an option of the Import Trust card");
    return `Import Trust: ${words}`;
  },
  "prism.project": (_s, d) => {
    const genes =
      Array.isArray(d.genes) && d.genes.length
        ? d.genes.map(String).join(", ")
        : "the headline genes";
    const extras = ["test", "graph"]
      .filter((k) => typeof d[k] === "string")
      .map((k) => `${k}: ${str(d[k])}`);
    return `Prism project from template ${str(d.template_id ?? "two_groups_log2")}: one table each for ${genes}${extras.length ? ` (${extras.join("; ")})` : ""}`;
  },
  "prism.exclusion_reason": (_s, d) => {
    const sample = d.sample ? str(d.sample) : "an unknown sample";
    return d.action === "restore"
      ? `Keep sample ${sample} in ${str(d.gene)} (restore it in the analysis)`
      : `Exclude sample ${sample} from ${str(d.gene)}, as it is in the table Prism sent back`;
  },
  "prism.value_edit": (_s, d) => {
    const sample = d.sample ? str(d.sample) : "an unknown sample";
    const what =
      d.action === "keep" ? "keep the edited value as a manual edit" : "restore qPilot's value";
    return `The value of sample ${sample} for ${str(d.gene)} was changed in Prism: ${what}`;
  },
  "stage.confirm": (s, d) => {
    const label = STAGE_LABEL[s as StageName] ?? s;
    const covers = Array.isArray(d.covers) ? d.covers.length : 0;
    return s === "choices"
      ? `Confirm the ${label} stage: the Decision Cards of this analysis`
      : `Confirm the ${label} stage: it covers ${covers} accepted proposal${covers === 1 ? "" : "s"}`;
  },
};

/**
 * A proposal (or another reading of it: an alternative, an edit) in plain words. A payload
 * that does not have its kind's shape (an agent's, say) is shown as JSON.
 */
export function describeProposal(
  p: Pick<Proposal, "kind" | "subject" | "payload">,
  payload?: Payload,
): string {
  const data = payload ?? (p.payload as Payload);
  const describer = DESCRIBERS[p.kind];
  if (describer) {
    try {
      return describer(p.subject, data);
    } catch {
      /* fall through to JSON */
    }
  }
  const json = JSON.stringify(data);
  return `${p.kind} for ${p.subject}: ${json.length > 300 ? `${json.slice(0, 300)}…` : json}`;
}

/** The payload the engine reads once accepted: the proposal's payload with a person's edits. */
export function effectivePayload(p: Pick<Proposal, "payload" | "edits">): Payload {
  return { ...(p.payload as Payload), ...((p.edits as Payload | null) ?? {}) };
}

/** A short title for a kind of proposal (card eyebrow). */
export const KIND_TITLE: Record<Proposal["kind"], string> = {
  "design.preset": "Design preset",
  "design.well_role": "Sample role",
  "design.group": "Group",
  "design.bio_unit": "Biological unit",
  "design.target_role": "Target role",
  "design.gene_symbol": "Gene symbol",
  "design.comparison": "Comparison",
  "design.pair": "Pairing",
  "design.dilution_series": "Dilution series",
  "curve.call_rule": "Amplification rule",
  "curve.well_call": "Well call",
  "curve.exclude_well": "Well exclusion",
  "curve.import_trust": "Import Trust",
  "choice.axis": "Further choice to test",
  "prism.project": "Prism project",
  "prism.exclusion_reason": "Exclusion in Prism",
  "prism.value_edit": "Value changed in Prism",
  "stage.confirm": "Confirm stage",
};

export const CURVE_JUDGE = "qpilot-curve-judge";

/** Who made a proposal, in words. */
export function makerText(m: Schemas["MadeBy"]): string {
  if (m.kind === "rule") return "Made by a fixed rule in qPilot (no model).";
  if (m.kind === "agent") return `Proposed by an agent over MCP (${m.agent || "unnamed"}).`;
  if (m.provider === CURVE_JUDGE)
    return `Made by the Curve Judge, a local curve classifier (model ${m.model ?? "?"}); it reads only the curve's fluorescence values.`;
  return `Made by the model ${m.provider || "?"} · ${m.model || "?"}${m.prompt_sha256 ? ` · prompt sha256 ${m.prompt_sha256.slice(0, 12)}` : ""}.`;
}

/** Blind-stage consequence wording (docs/studio.md). */
export const MATTERS_TEXT = "This matters for at least one conclusion; decide on the evidence.";
export const NOT_MATTERS_TEXT = "Neither reading changes any conclusion.";
export const BLIND_TEXT =
  "Hidden in the blind stages: no gene, direction or number is shown before the design and the curves are confirmed.";

/** A proposal of the design or curves stage (its consequence is never shown in full). */
export function isBlindKind(p: Pick<Proposal, "kind" | "subject">): boolean {
  if (p.kind === "stage.confirm") return p.subject === "design" || p.subject === "curves";
  return p.kind.startsWith("design.") || p.kind.startsWith("curve.");
}

/** Actor in words. */
export const ACTOR_WORDS: Record<string, string> = {
  human: "a person",
  agent: "an agent",
  system: "qPilot (automatic)",
};

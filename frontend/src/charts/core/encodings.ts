/**
 * What each mark means: a shape, a colour token and a word, so meaning is never carried by colour
 * alone (docs/app.md §5). Conclusions are arrows, verdicts the audit's glyphs, levels their own
 * glyphs plus a bar count in tags.
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
  /** The word the mark stands for ("Called up", "Fragile", "Moderate"). */
  label: string;
}

// ---- conclusions (qPilot's call rule) ---------------------------------------------------------

export type CallKey = "up" | "down" | "none";

export const CALLS: Record<CallKey, Mark & { arrow: string; short: string }> = {
  up: { shape: "up", tone: "var(--up)", label: "Up", short: "up", arrow: "▲" },
  down: { shape: "down", tone: "var(--down)", label: "Down", short: "down", arrow: "▼" },
  none: { shape: "dash", tone: "var(--none)", label: "No call", short: "no call", arrow: "—" },
};

export const CALL_ORDER: CallKey[] = ["up", "down", "none"];

/**
 * The call of an audit row: its `call_key` when the API sends one, else read from the audit's own
 * words ("called up (higher in …)", "called down", "no change called", "no call").
 */
export function callKey(row: { call_key?: string | null; call?: string | null } | string): CallKey {
  const key = typeof row === "string" ? undefined : row.call_key;
  if (key === "up" || key === "down" || key === "none") return key;
  const words = (typeof row === "string" ? row : (row.call ?? "")).trim().toLowerCase();
  if (words === "up" || words.startsWith("called up")) return "up";
  if (words === "down" || words.startsWith("called down")) return "down";
  return "none";
}

// ---- audit verdicts ---------------------------------------------------------------------------

export type VerdictKey =
  | "check data first"
  | "fragile"
  | "depends on your choices"
  | "holds with caveats"
  | "solid"
  | "no call";

/** The audit's verdicts, most urgent first (qsim.verdict.ORDER). */
export const VERDICT_ORDER: VerdictKey[] = [
  "check data first",
  "fragile",
  "depends on your choices",
  "holds with caveats",
  "solid",
  "no call",
];

export const VERDICTS: Record<VerdictKey, Mark & { token: string }> = {
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
  "no call": { shape: "ring", tone: "var(--v-nocall)", label: "No change called", token: "v-nocall" },
};

export function isVerdict(v: unknown): v is VerdictKey {
  return typeof v === "string" && v in VERDICTS;
}

// ---- confidence levels (ordinal, never a probability) -----------------------------------------

export type LevelKey = "High" | "Moderate" | "Low" | "Very low";

export const LEVEL_ORDER: LevelKey[] = ["High", "Moderate", "Low", "Very low"];

export const LEVELS: Record<LevelKey, Mark & { bars: number; token: string }> = {
  High: { shape: "circle", tone: "var(--l-high)", label: "High", bars: 4, token: "l-high" },
  Moderate: { shape: "half", tone: "var(--l-moderate)", label: "Moderate", bars: 3, token: "l-moderate" },
  Low: { shape: "ring", tone: "var(--l-low)", label: "Low", bars: 2, token: "l-low" },
  "Very low": { shape: "cross", tone: "var(--l-verylow)", label: "Very low", bars: 1, token: "l-verylow" },
};

export function isLevel(v: unknown): v is LevelKey {
  return typeof v === "string" && v in LEVELS;
}

// ---- option tiers in the audit ----------------------------------------------------------------

export const TIER_WORDS: Record<string, string> = {
  prespecified: "your planned analysis",
  defensible: "reasonable alternative",
  common_practice: "common shortcut",
};

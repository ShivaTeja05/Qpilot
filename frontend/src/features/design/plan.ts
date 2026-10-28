/**
 * Several comparisons on the Design page: the person's choice of pattern (each group against a
 * control, every pair, or their own list), control group, correction and pairing, written as the
 * person's own `design.comparison` item (the payload the engine's ComparisonPlan reads:
 * qpilot/schemas_studio.py). Pure: the panel renders it; the engine checks it when it is set.
 */
import type { EditItem } from "./draft";
import { comparisonItem } from "./draft";

export type Pattern = "vs_control" | "all_pairs" | "chosen";
export type Correction = "holm" | "dunnett" | "tukey" | "none";
export type Pair = readonly [string, string];

export interface PlanChoice {
  pattern: Pattern;
  control: string | null;
  /** The person's own list (pattern `chosen`): [compared, reference] each. */
  pairs: Pair[];
  correction: Correction;
  paired: boolean;
}

const CONTROL_LIKE =
  /(^|[^a-z])(ctrl|control|vehicle|veh|pbs|wt|wild.?type|untreated|baseline|sham|mock|naive)([^a-z]|$)|(^|[^a-z0-9])(0 ?h|day ?0|t ?=? ?0|time ?0)([^a-z0-9]|$)/i;

/** A control-like group name (control, vehicle, WT, untreated, 0 h, day 0...), when one. */
export function guessControl(names: readonly string[]): string | null {
  const like = names.filter((g) => CONTROL_LIKE.test(g));
  return like.length === 1 ? like[0]! : null;
}

/** The comparisons a choice makes, the first first: [compared group, reference group] each. */
export function planPairs(names: readonly string[], choice: PlanChoice): Pair[] {
  if (choice.pattern === "vs_control") {
    const control = choice.control;
    if (!control || !names.includes(control)) return [];
    return names.filter((g) => g !== control).map((g) => [g, control] as const);
  }
  if (choice.pattern === "all_pairs") {
    const out: Pair[] = [];
    names.forEach((b, i) => names.slice(i + 1).forEach((a) => out.push([a, b] as const)));
    return out;
  }
  return choice.pairs.filter(([a, b]) => a !== b && names.includes(a) && names.includes(b));
}

export interface CorrectionOption {
  value: Correction;
  label: string;
  hint: string;
  /** Why it cannot be chosen with this pattern (null: it can). */
  unavailable: string | null;
}

/** The corrections a person may choose for a choice, each with what it means in plain words. */
export function corrections(choice: PlanChoice): CorrectionOption[] {
  const paired = choice.paired ? "It pools unpaired groups, so not with a pairing." : null;
  return [
    {
      value: "holm",
      label: "Holm",
      hint: "Each gene's p-values are corrected across its comparisons; each comparison keeps its own Welch test (no equal-spread assumption).",
      unavailable: null,
    },
    {
      value: "dunnett",
      label: "Dunnett",
      hint: "For each group against one control: one t-test with the spread pooled over every group (assumes equal spread on the log2 scale), corrected for comparing several groups with the same control.",
      unavailable:
        choice.pattern !== "vs_control" ? "Only for each group against one control." : paired,
    },
    {
      value: "tukey",
      label: "Tukey",
      hint: "For every pair of groups: one t-test with the spread pooled over every group (Tukey–Kramer), corrected for comparing every pair.",
      unavailable: choice.pattern !== "all_pairs" ? "Only for every pair of groups." : paired,
    },
    {
      value: "none",
      label: "No correction",
      hint: "Each call uses its own p-value; with several comparisons per gene some calls are expected by chance alone.",
      unavailable: null,
    },
  ];
}

/** The correction a choice keeps: the one asked for when it fits, else Holm's. */
export function fittingCorrection(choice: PlanChoice): Correction {
  const found = corrections(choice).find((c) => c.value === choice.correction);
  return found && !found.unavailable ? choice.correction : "holm";
}

/**
 * The person's design item for a choice, or what is missing in words. One unpaired comparison is
 * the plain comparison (no plan: one spelling per analysis, as the engine requires).
 */
export function planItem(
  names: readonly string[],
  choice: PlanChoice,
  pairBy: string | null,
): EditItem | string {
  const pairs = planPairs(names, choice);
  if (choice.pattern === "vs_control" && !choice.control) return "Choose the control group.";
  if (!pairs.length) return "Choose at least one comparison.";
  const keys = new Set(pairs.map(([a, b]) => [a, b].sort().join("\u0000")));
  if (keys.size !== pairs.length) return "Each pair of groups can be compared once.";
  const paired = choice.paired && Boolean(pairBy);
  const [first] = pairs;
  if (pairs.length === 1 && !paired) return comparisonItem(first![0], first![1]);
  return {
    kind: "design.comparison",
    subject: "comparison",
    payload: {
      group_a: first![0],
      group_b: first![1],
      comparisons: pairs.map(([a, b]) => ({ group_a: a, group_b: b })),
      pattern: choice.pattern,
      ...(choice.pattern === "vs_control" ? { control: choice.control } : {}),
      correction: fittingCorrection({ ...choice, paired }),
      ...(paired ? { pair_by: pairBy } : {}),
    },
  };
}

/** The choice a person set before (the accepted comparison's plan), else a starting guess. */
export function planNow(
  names: readonly string[],
  plan: Record<string, unknown> | null | undefined,
): PlanChoice {
  const listed = Array.isArray(plan?.comparisons)
    ? (plan!.comparisons as { group_a?: unknown; group_b?: unknown }[]).map(
        (c) => [String(c.group_a), String(c.group_b)] as const,
      )
    : [];
  const pattern = (plan?.pattern as Pattern | undefined) ?? null;
  const control = (plan?.control as string | undefined) ?? guessControl(names);
  return {
    pattern: pattern ?? (control ? "vs_control" : "all_pairs"),
    control: control ?? null,
    pairs: listed,
    correction: ((plan?.correction as Correction | undefined) ?? "holm") as Correction,
    paired: Boolean(plan?.pair_by),
  };
}

/** The comparisons in words: "Drug A vs Control; Drug B vs Control". */
export function pairsWords(pairs: readonly Pair[]): string {
  return pairs.map(([a, b]) => `${a} vs ${b}`).join("; ");
}

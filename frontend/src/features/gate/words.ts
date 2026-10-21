/**
 * The Controls section's words: the four status words of a rule (never "valid", "validated",
 * "compliant" or "diagnostic"), what a consequence class means, where a finding sits, and the
 * filters of the rule list. Pure functions, tested on the recorded answers.
 */
import type { Tone } from "@/ui";
import type { ConsequenceClass, Consequence, Evaluation, Plate, Verdict } from "./api";

export const VERDICTS: Verdict[] = ["fail", "warn", "pass", "not_applicable"];

export const VERDICT_WORD: Record<Verdict, string> = {
  fail: "Fail",
  warn: "Warn",
  pass: "Pass",
  not_applicable: "Not applicable",
};

export const VERDICT_TONE: Record<Verdict, Tone> = {
  fail: "danger",
  warn: "warn",
  pass: "ok",
  not_applicable: "neutral",
};

export const CLASS_WORD: Record<ConsequenceClass, string> = {
  flip: "Changes a call",
  magnitude: "Moves the numbers",
  none: "Changes no call",
  unknown: "Could not be checked",
};

export const CLASS_TONE: Record<ConsequenceClass, Tone> = {
  flip: "danger",
  magnitude: "warn",
  none: "neutral",
  unknown: "info",
};

/** A plate's run id without the date the demo's exporter appends (`CAMTA2_20080227` → `CAMTA2`). */
export function plateLabel(run: string | null | undefined): string {
  if (!run) return "";
  return run.replace(/_\d{8}$/, "");
}

/** Where a finding sits, in words: plate · target · sample (the target when it is not the plate's name). */
export function whereText(e: Pick<Evaluation, "plate" | "target" | "sample">): string {
  const plate = plateLabel(e.plate);
  const parts = [plate ? `Plate ${plate}` : ""];
  if (e.target && e.target !== plate) parts.push(e.target);
  if (e.sample) parts.push(`sample ${e.sample}`);
  return parts.filter(Boolean).join(" · ") || "The study";
}

/** A well key (`run/well`) in words: `CAMTA2 · F24`. */
export function wellText(key: string): string {
  const cut = key.lastIndexOf("/");
  if (cut < 0) return key;
  return `${plateLabel(key.slice(0, cut))} · ${key.slice(cut + 1)}`;
}

export type VerdictFilter = "attention" | "all" | Verdict;

export interface RuleFilter {
  verdict: VerdictFilter;
  /** A rule id, or "all". */
  rule: string;
  /** A plate (run id), or null for every plate. */
  plate: string | null;
}

export const DEFAULT_FILTER: RuleFilter = { verdict: "attention", rule: "all", plate: null };

/** The evaluations a filter keeps, problems first (fail, warn), then in the pack's order. */
export function filterEvaluations(evals: readonly Evaluation[], f: RuleFilter): Evaluation[] {
  const kept = evals.filter(
    (e) =>
      (f.verdict === "all" ||
        (f.verdict === "attention"
          ? e.verdict === "fail" || e.verdict === "warn"
          : e.verdict === f.verdict)) &&
      (f.rule === "all" || e.rule_id === f.rule) &&
      (f.plate === null || e.plate === f.plate),
  );
  const rank = (v: Verdict) => VERDICTS.indexOf(v);
  return kept
    .map((e, i) => ({ e, i }))
    .sort((a, b) => rank(a.e.verdict) - rank(b.e.verdict) || a.i - b.i)
    .map(({ e }) => e);
}

/** Evaluations per verdict (all four keys). */
export function verdictCounts(
  evals: readonly Pick<Evaluation, "verdict">[],
): Record<Verdict, number> {
  const out = { fail: 0, warn: 0, pass: 0, not_applicable: 0 } as Record<Verdict, number>;
  for (const e of evals) out[e.verdict] += 1;
  return out;
}

/** A plate in words (its name first, as the button shows it): status, then verdict counts. */
export function plateSummary(p: Plate): string {
  const counts = VERDICTS.filter((v) => (p.counts[v] ?? 0) > 0)
    .map((v) => `${p.counts[v]} ${VERDICT_WORD[v].toLowerCase()}`)
    .join(", ");
  return `${plateLabel(p.plate)}: ${p.status}${counts ? `; ${counts}` : ""}`;
}

/** The consequence's most telling option: the one that changes most, else the first. */
export function leadOption(c: Consequence): Consequence["options"][number] | undefined {
  return [...c.options].sort(
    (a, b) =>
      b.n_flipped - a.n_flipped ||
      b.n_flipped_elsewhere - a.n_flipped_elsewhere ||
      b.max_delta_log2fc - a.max_delta_log2fc,
  )[0];
}

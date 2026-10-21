/**
 * The Controls section's words: the four status words of a rule (never "valid", "validated",
 * "compliant" or "diagnostic"), what a consequence class means, where a finding sits, and the
 * filters of the rule list. Pure functions, tested on the recorded answers.
 */
import { count, plural } from "@/lib/format";
import type { Tone } from "@/ui";
import type { ConsequenceClass, Consequence, Evaluation, Plate, RunFile, Verdict } from "./api";

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

/**
 * Where a finding sits, in words: plate · unit · target · sample (the target when it is not the
 * plate's name; a biological unit for G-RT, whose wells can be on several plates).
 */
export function whereText(e: Pick<Evaluation, "plate" | "target" | "sample" | "unit">): string {
  const plate = plateLabel(e.plate);
  const parts = [plate ? `Plate ${plate}` : "", e.unit ? `Unit ${e.unit}` : ""];
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

/** What a run file is, in words (the reader's `source_kind`). */
export const RUN_KIND_WORD: Record<string, string> = {
  eds: "an .eds file",
  quantstudio_export: "a QuantStudio results export",
  cfx_run_information: "CFX run information",
  rdml: "RDML",
};

/** Which run file G-INSTR read for a plate, in one phrase. */
export function runSourceText(r: Pick<RunFile, "source" | "kind" | "name" | "problem">): string {
  const kind = r.kind ? (RUN_KIND_WORD[r.kind] ?? r.kind) : "a run file";
  if (r.source === "linked") {
    if (r.problem === "missing") return "A linked run file that is no longer where qPilot kept it";
    if (r.problem === "changed") return "A linked run file that has changed since it was linked";
    if (r.problem) return "A linked run file that cannot be read any more";
    return `${r.name ?? "A run file"} (${kind}), linked by a person`;
  }
  if (r.source === "export")
    return `${r.name ?? "The plate's run file"} (${kind}), in the instrument export this study was opened from`;
  if (r.source === "study_file")
    return "The study's own file (RDML: the instrument and the run date at most)";
  return "No run file";
}

/** What each source of run file is called in the Run files card's sentence. */
const RUN_SOURCE_PHRASE: Partial<Record<RunFile["source"], string>> = {
  linked: "a run file a person linked",
  export: "the run file in the instrument export",
  study_file: "the study's own file",
};

/** Which run files G-INSTR reads across the plates, in one sentence. */
export function runFilesSentence(runs: Pick<RunFile, "source">[]): string {
  const parts = (["linked", "export", "study_file"] as const)
    .map((source) => [source, runs.filter((r) => r.source === source).length] as const)
    .filter(([, n]) => n > 0);
  const plates =
    runs.length === 1 ? "the plate" : `every one of the ${plural(runs.length, "plate")}`;
  if (parts.length === 1 && parts[0]![1] === runs.length)
    return `G-INSTR reads ${RUN_SOURCE_PHRASE[parts[0]![0]]} for ${plates}.`;
  const said = parts.map(
    ([source, n], i) =>
      `${RUN_SOURCE_PHRASE[source]} for ${count(n)}${i === 0 ? ` of the ${plural(runs.length, "plate")}` : ""}`,
  );
  return `G-INSTR reads ${said.join(", ")}.`;
}

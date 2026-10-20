/**
 * From the API's views to the charts' props. The audit views are qsim's `Screen` dicts as the API
 * returns them (docs/app.md §4 Audit); the results rows are the API's `GeneRow`. Types here are
 * structural (only the fields the charts read), so the generated schema types fit them.
 */
import type { AnalysisDot } from "./AnalysesStrip";
import type { SampleGroup, SamplePoint } from "./Beeswarm";
import type { ChoiceRow } from "./ChoiceDotPlot";
import type { DumbbellRow } from "./Dumbbell";
import type { BarRow } from "./HBars";
import type { MapPoint } from "./RobustnessMap";
import { fmtFoldLog2, fmtPct, plural } from "./core/format";
import {
  CALLS,
  LEVELS,
  VERDICTS,
  callKey,
  isLevel,
  isVerdict,
  type CallKey,
  type Mark,
} from "./core/encodings";

// ---- audit views (qsim Screen) ------------------------------------------------------------------

export interface AuditScale {
  line_log2: number;
  line: string;
}

export interface AuditAnalyses extends AuditScale {
  gene: string;
  n: number;
  n_same: number;
  n_other: number;
  base_call: string;
  rows: {
    log2: number;
    fold: string;
    call: string;
    call_key?: string | null;
    same: boolean;
    choices: string[];
    planned: boolean;
  }[];
}

export function analysesDots(a: AuditAnalyses): AnalysisDot[] {
  return a.rows.map((r) => ({
    log2: r.log2,
    call: callKey(r),
    same: r.same,
    planned: r.planned,
    choices: r.choices,
    foldText: r.fold,
    callText: r.call,
  }));
}

export interface AuditEffects extends AuditScale {
  gene: string;
  planned_log2: number;
  planned: string;
  decisions: {
    id: string;
    name: string;
    n_change: number;
    options: {
      label: string;
      tier: string;
      log2: number;
      fold: string;
      call: string;
      call_key?: string | null;
      changes_call: boolean;
      planned: boolean;
    }[];
  }[];
}

export function choiceRows(e: AuditEffects): ChoiceRow[] {
  return e.decisions.map((d) => ({
    id: d.id,
    name: d.name,
    options: d.options.map((o) => ({
      label: o.label,
      tier: o.tier,
      log2: o.log2,
      call: callKey(o),
      changesCall: o.changes_call,
      planned: o.planned,
      foldText: o.fold,
      callText: o.call,
    })),
  }));
}

export interface AuditSamples extends AuditScale {
  gene: string;
  fold: string;
  fold_log2: number;
  late_cut: string;
  changes: string[];
  groups: Record<string, { label: string; n: number; missing: number; mean: number }>;
  points: {
    x: number;
    group: string;
    sample: string;
    plate: string;
    well: string;
    cq: string | null;
    late: boolean;
    nondetect: boolean;
    flagged: boolean;
    carries: boolean;
    value: string;
  }[];
}

export function sampleGroups(s: AuditSamples): SampleGroup[] {
  return Object.entries(s.groups).map(([key, g]) => ({
    key,
    label: g.label,
    n: g.n,
    missing: g.missing,
    mean: g.mean,
  }));
}

export function samplePoints(s: AuditSamples): SamplePoint[] {
  return s.points.map((p) => ({
    sample: p.sample,
    group: p.group,
    x: p.x,
    plate: p.plate,
    well: p.well,
    cq: p.cq,
    late: p.late,
    nondetect: p.nondetect,
    flagged: p.flagged,
    carries: p.carries,
    valueText: p.value,
  }));
}

export interface AuditStudy extends AuditScale {
  map: {
    gene: string;
    log2: number;
    fold: string;
    holds: number;
    verdict: string;
    headline: boolean;
  }[];
  choices: { id: string; name: string; alone: number; spread: number; question: boolean }[];
  references: { gene: string; m: string; differs: boolean }[];
  stable_below: string;
}

/** The audit's map: holds is "of 100" there; verdict glyphs. */
export function auditMapPoints(s: AuditStudy, verdictLabel?: (v: string) => string): MapPoint[] {
  return s.map.map((g) => {
    const mark: Mark = isVerdict(g.verdict)
      ? VERDICTS[g.verdict]
      : { ...VERDICTS["no call"], label: g.verdict };
    return {
      gene: g.gene,
      log2: g.log2,
      holds: g.holds / 100,
      mark: verdictLabel ? { ...mark, label: verdictLabel(g.verdict) } : mark,
      headline: g.headline,
      foldText: g.fold,
    };
  });
}

/** "Calls changed by one choice alone", most first. */
export function choicesAloneBars(s: AuditStudy): BarRow[] {
  return [...s.choices]
    .sort((a, b) => b.alone - a.alone)
    .map((c) => ({
      key: c.id,
      label: c.name,
      value: c.alone,
      valueText: plural(c.alone, "call"),
      note: c.question ? "changes the question asked" : undefined,
      strong: c.alone > 0,
    }));
}

/** "Share of the spread in fold change" across reasonable analyses, largest first. */
export function choicesSpreadBars(s: AuditStudy): BarRow[] {
  return [...s.choices]
    .sort((a, b) => b.spread - a.spread)
    .map((c) => ({
      key: c.id,
      label: c.name,
      value: c.spread,
      valueText: fmtPct(c.spread),
      strong: c.spread >= 10,
    }));
}

export interface AuditWhatif extends AuditScale {
  changes: string[];
  n_changed: number;
  n_genes: number;
  changed_genes: string[];
  rows: {
    gene: string;
    headline: boolean;
    picked: boolean;
    verdict: string;
    base: string;
    base_call: string;
    base_call_key?: string | null;
    new: string;
    new_call: string;
    new_call_key?: string | null;
    base_log2: number;
    new_log2: number;
    changed: boolean;
  }[];
}

export function whatifRows(w: AuditWhatif): DumbbellRow[] {
  return w.rows.map((r) => ({
    gene: r.gene,
    baseLog2: r.base_log2,
    newLog2: r.new_log2,
    baseCall: callKey({ call_key: r.base_call_key, call: r.base_call }),
    newCall: callKey({ call_key: r.new_call_key, call: r.new_call }),
    headline: r.headline,
    baseText: r.base,
    newText: r.new,
  }));
}

// ---- results (the API's GeneRow) ----------------------------------------------------------------

export interface GeneRowLike {
  gene: string;
  headline?: boolean;
  conclusion: string;
  fc: number;
  p?: number | null;
  holds: number;
  level?: string | null;
  verdict?: string | null;
  verdict_label?: string | null;
}

export type MapEncoding = "conclusion" | "level" | "verdict";

/** The mark a results gene gets under an encoding (falls back to the conclusion). */
export function geneMark(g: GeneRowLike, by: MapEncoding): Mark {
  if (by === "level" && isLevel(g.level))
    return { ...LEVELS[g.level], label: `Confidence: ${g.level}` };
  if (by === "verdict" && isVerdict(g.verdict))
    return {
      ...VERDICTS[g.verdict],
      label: `Audit: ${g.verdict_label ?? VERDICTS[g.verdict].label}`,
    };
  const c = (["up", "down", "none"].includes(g.conclusion) ? g.conclusion : "none") as CallKey;
  return { ...CALLS[c], label: `Call: ${CALLS[c].label}` };
}

export function resultsMapPoints(genes: readonly GeneRowLike[], by: MapEncoding): MapPoint[] {
  return genes.map((g) => ({
    gene: g.gene,
    log2: Math.log2(g.fc),
    holds: g.holds,
    mark: geneMark(g, by),
    headline: g.headline,
    foldText: fmtFoldLog2(Math.log2(g.fc)),
    details: [
      by !== "conclusion"
        ? `Call: ${CALLS[(g.conclusion as CallKey) in CALLS ? (g.conclusion as CallKey) : "none"].label}`
        : null,
      by !== "level" && isLevel(g.level) ? `Confidence: ${g.level}` : null,
      by !== "verdict" && g.verdict ? `Audit: ${g.verdict_label ?? g.verdict}` : null,
    ].filter((x): x is string => Boolean(x)),
  }));
}

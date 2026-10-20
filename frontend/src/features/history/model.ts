/**
 * The History timeline as data: which points the map can show (the analysis this one replaced,
 * then every step of the chain), where the Studio's stage runs sit between them, and the map's
 * points tweened between two analyses. Pure functions over the API's answers; no numbers of
 * their own.
 */
import { CALLS, type CallKey, type MapPoint } from "@/charts";
import { fold, pValue } from "@/lib/format";
import type {
  HistoryAnalysis,
  HistoryStep,
  HistoryView,
  RelatedStudy,
  StudioMilestone,
} from "./api";

/** A point of the timeline the map can show: an analysis in force. */
export type Point =
  | {
      kind: "earlier";
      id: string;
      study: RelatedStudy;
      analysis: HistoryAnalysis | null;
      genes: string[];
      /** The step of the earlier analysis' own chain this is (its head). */
      seq: number | null;
    }
  | {
      kind: "step";
      id: string;
      step: HistoryStep;
      analysis: HistoryAnalysis | null;
      genes: string[];
    };

export type TrackItem =
  | { kind: "milestone"; id: string; milestone: StudioMilestone }
  | { kind: "point"; id: string; point: Point }
  | { kind: "later"; id: string; study: RelatedStudy };

export const stepId = (seq: number) => `s${seq}`;
export const EARLIER_ID = "earlier";

/** The analysis of this file made just before this one (the one it replaced), if any. */
export function earlierStudy(view: HistoryView): RelatedStudy | null {
  const made = view.created_at ?? "";
  const before = view.related.filter((r) => (r.created_at ?? "") <= made);
  return before.length ? before[before.length - 1]! : null;
}

/** Analyses of this file made after this one. */
export function laterStudies(view: HistoryView): RelatedStudy[] {
  const made = view.created_at ?? "";
  return view.related.filter((r) => (r.created_at ?? "") > made);
}

/** The analysis in force at a step, or null when the step cannot be replayed. */
export function analysisOf(view: HistoryView, step: HistoryStep): HistoryAnalysis | null {
  return step.analysis == null ? null : (view.analyses[step.analysis] ?? null);
}

/**
 * Every item of the timeline in order: the Studio's stage runs before this analysis (with the
 * analysis it replaced right after the run that led to it), then each step with the runs that
 * came after it, then any later analysis of the file.
 */
export function buildTrack(view: HistoryView, earlier: HistoryView | null): TrackItem[] {
  const items: TrackItem[] = [];
  const before = view.studio.filter((m) => m.before);
  const prior = earlierStudy(view);
  const earlierPoint: TrackItem | null =
    prior && earlier
      ? {
          kind: "point",
          id: EARLIER_ID,
          point: {
            kind: "earlier",
            id: EARLIER_ID,
            study: prior,
            analysis: earlier.steps.length
              ? analysisOf(earlier, earlier.steps[earlier.steps.length - 1]!)
              : null,
            genes: earlier.genes,
            seq: earlier.steps.length ? earlier.steps[earlier.steps.length - 1]!.seq : null,
          },
        }
      : null;
  let led = earlierPoint ? before.findIndex((m) => m.led_to === prior!.study_id) : -1;
  if (earlierPoint && led < 0) {
    const made = prior!.created_at ?? "";
    led = before.filter((m) => m.at_last <= made).length - 1;
  }
  if (earlierPoint && led < 0) items.push(earlierPoint);
  before.forEach((m, i) => {
    items.push({ kind: "milestone", id: `m${m.first_seq}`, milestone: m });
    if (earlierPoint && i === led) items.push(earlierPoint);
  });
  const after = view.studio.filter((m) => !m.before);
  for (const step of view.steps) {
    items.push({
      kind: "point",
      id: stepId(step.seq),
      point: {
        kind: "step",
        id: stepId(step.seq),
        step,
        analysis: analysisOf(view, step),
        genes: view.genes,
      },
    });
    for (const m of after.filter((x) => (x.after_seq ?? 0) === step.seq)) {
      items.push({ kind: "milestone", id: `m${m.first_seq}`, milestone: m });
    }
  }
  const last = view.steps.length ? view.steps[view.steps.length - 1]!.seq : 0;
  for (const m of after.filter((x) => (x.after_seq ?? 0) > last)) {
    items.push({ kind: "milestone", id: `m${m.first_seq}`, milestone: m });
  }
  for (const study of laterStudies(view)) {
    items.push({ kind: "later", id: `later-${study.study_id}`, study });
  }
  return items;
}

/** The points of a track, in order (what ←/→ moves between). */
export function pointsOf(track: TrackItem[]): Point[] {
  return track.flatMap((t) => (t.kind === "point" ? [t.point] : []));
}

/** A call as one of the three keys (an unknown or missing call reads as no call). */
export function callOf(c: string | null | undefined): CallKey {
  return c === "up" || c === "down" ? c : "none";
}

/** The map's points for one analysis: genes with a fold and a share only. */
export function mapPoints(
  analysis: HistoryAnalysis | null,
  genes: readonly string[],
  headline: readonly string[],
): MapPoint[] {
  if (!analysis) return [];
  const lead = new Set(headline);
  const out: MapPoint[] = [];
  analysis.genes.forEach((g, i) => {
    const gene = genes[i] ?? g.gene;
    if (g.log2fc == null || g.holds == null || !Number.isFinite(g.log2fc)) return;
    const call = callOf(g.conclusion);
    out.push({
      gene,
      log2: g.log2fc,
      holds: g.holds,
      mark: { ...CALLS[call], label: `Call: ${CALLS[call].label}` },
      headline: lead.has(gene),
      foldText: fold(g.fc ?? 2 ** g.log2fc),
      details: g.p == null ? [] : [`p ${pValue(g.p)}`],
    });
  });
  return out;
}

export const easeOut = (t: number) => 1 - (1 - t) ** 3;

/**
 * The map between two analyses at time `t` (0 → `from`, 1 → `to`): every gene glides from where
 * it was to where it is; its mark (the call) turns over half-way. Genes only in `to` appear at
 * their place.
 */
export function tween(from: readonly MapPoint[], to: readonly MapPoint[], t: number): MapPoint[] {
  if (t >= 1 || !from.length) return [...to];
  const was = new Map(from.map((p) => [p.gene, p]));
  const k = easeOut(Math.max(0, t));
  return to.map((p) => {
    const f = was.get(p.gene);
    if (!f) return p;
    return {
      ...p,
      log2: f.log2 + (p.log2 - f.log2) * k,
      holds: f.holds + (p.holds - f.holds) * k,
      mark: k < 0.5 ? f.mark : p.mark,
    };
  });
}

/** Genes whose call or place differs between two sets of map points. */
export function movedGenes(from: readonly MapPoint[], to: readonly MapPoint[]): Set<string> {
  const was = new Map(from.map((p) => [p.gene, p]));
  const out = new Set<string>();
  for (const p of to) {
    const f = was.get(p.gene);
    if (!f) continue;
    if (
      f.mark.label !== p.mark.label ||
      Math.abs(f.log2 - p.log2) > 1e-9 ||
      Math.abs(f.holds - p.holds) > 1e-12
    )
      out.add(p.gene);
  }
  return out;
}

/** Genes whose call differs between two sets of map points. */
export function flippedGenes(from: readonly MapPoint[], to: readonly MapPoint[]): Set<string> {
  const was = new Map(from.map((p) => [p.gene, p.mark.label]));
  return new Set(
    to.filter((p) => was.has(p.gene) && was.get(p.gene) !== p.mark.label).map((p) => p.gene),
  );
}

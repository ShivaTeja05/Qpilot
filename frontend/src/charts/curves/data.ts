/** The curve viewer's data: series aligned on one cycle axis, the log-scale rule, and words. */
import { count, fixed } from "@/lib/format";

export interface CurveSeries {
  /** Unique id (the well key, `run_id/well`). */
  id: string;
  /** The legend label (`A1 · 1495`). */
  label: string;
  cycles: readonly number[];
  values: readonly (number | null)[];
  /** Cq, drawn as a marker on the cycle axis when known. */
  cq?: number | null;
  /** Baseline in the same units as `values`, drawn as a line when known. */
  baseline?: number | null;
  /** `focus`: a chosen well (coloured, with its Cq and baseline); `context`: a neighbour (faint). */
  role?: "focus" | "context";
}

export type CurveScale = "linear" | "log";

export interface Aligned {
  x: number[];
  ys: (number | null)[][];
  /** Values not drawn on the log scale (zero or below), per series. */
  hidden: number[];
}

/** Every series on the union of their cycles; on the log scale, values ≤ 0 become gaps. */
export function align(series: readonly CurveSeries[], scale: CurveScale): Aligned {
  const xs = new Set<number>();
  for (const s of series) for (const c of s.cycles) if (Number.isFinite(c)) xs.add(c);
  const x = [...xs].sort((a, b) => a - b);
  const index = new Map(x.map((c, i) => [c, i]));
  const hidden: number[] = [];
  const ys = series.map((s) => {
    const y: (number | null)[] = new Array<number | null>(x.length).fill(null);
    let h = 0;
    s.cycles.forEach((c, i) => {
      const at = index.get(c);
      const v = s.values[i];
      if (at === undefined || v == null || !Number.isFinite(v)) return;
      if (scale === "log" && v <= 0) {
        h += 1;
        return;
      }
      y[at] = v;
    });
    hidden.push(h);
    return y;
  });
  return { x, ys, hidden };
}

/** Decimals that suit a set of values: raw counts in whole numbers, ratios to three places. */
export function decimalsFor(series: readonly CurveSeries[]): number {
  let max = 0;
  for (const s of series)
    for (const v of s.values) if (v != null && Number.isFinite(v)) max = Math.max(max, Math.abs(v));
  return max >= 1000 ? 0 : max >= 100 ? 1 : max >= 10 ? 2 : 3;
}

/** One sentence about the curves on show (the chart's accessible summary). */
export function curvesSummary(series: readonly CurveSeries[], yLabel: string): string {
  if (!series.length) return "No curve to show.";
  const focus = series.filter((s) => s.role !== "context");
  const context = series.length - focus.length;
  const cycles = series.flatMap((s) => s.cycles).filter(Number.isFinite);
  const span = cycles.length ? ` over cycles ${Math.min(...cycles)} to ${Math.max(...cycles)}` : "";
  const parts = focus.map((s) =>
    s.cq != null && Number.isFinite(s.cq)
      ? `${s.label} (Cq ${fixed(s.cq, 1)})`
      : `${s.label} (no Cq)`,
  );
  const head = `${yLabel} by cycle for ${focus.length === 1 ? "one well" : `${count(focus.length)} wells`}${span}: ${parts.join("; ")}`;
  const tail = context
    ? `; ${context === 1 ? "one other well" : `${count(context)} other wells`} of the same sample shown faint`
    : "";
  return `${head}${tail}.`;
}

/** The palette for focus series: tokens, in order (context series are always faint). */
export const SERIES_TOKENS = [
  "--accent",
  "--info",
  "--v-depends",
  "--v-check",
  "--down",
  "--up",
  "--v-solid",
  "--v-fragile",
] as const;

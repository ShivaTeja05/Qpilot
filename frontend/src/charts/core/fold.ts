/**
 * The fold-change axis every science chart shares: log2 underneath, labelled in × (½×, 1×, 2×, 4×),
 * always wide enough to show the call line on both sides (the 2× lines of "at least 2-fold").
 */
import { scaleLinear, type ScaleLinear } from "d3-scale";

export interface FoldScale {
  /** log2 fold → x pixels. */
  x: ScaleLinear<number, number>;
  lo: number;
  hi: number;
  ticks: FoldTick[];
}

export interface FoldTick {
  log2: number;
  label: string;
}

/** The label of a whole-number log2 tick: `1×`, `2×`, `16×`, `1/2×`, `1/4×`, `1/8×`. */
export function foldTickLabel(k: number): string {
  if (k === 0) return "1×";
  if (k > 0) return `${2 ** k}×`;
  return `1/${2 ** -k}×`;
}

/**
 * The domain of a fold axis (log2), with a little air. `line` is the call rule's minimum |log2 fold|
 * (1 for "at least 2-fold"); 0 means no lines. With `zero` (the default) 1× and both call lines are
 * always inside; without it, only the call line on the data's side is (a one-gene chart whose
 * analyses all sit above 2× then uses its width for the data).
 */
export function foldDomain(values: readonly number[], line = 0, pad = 0.1, zero = true): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [-Math.max(1, line) * 1.2, Math.max(1, line) * 1.2];
  const dmin = Math.min(...finite);
  const dmax = Math.max(...finite);
  let lo: number;
  let hi: number;
  if (zero) {
    lo = Math.min(0, -line, dmin);
    hi = Math.max(0, line, dmax);
  } else {
    lo = dmin;
    hi = dmax;
    if (line && dmax > 0) hi = Math.max(hi, line);
    if (line && dmin < 0) lo = Math.min(lo, -line);
    if (line && dmax > 0 && dmin > 0) lo = Math.min(lo, line);
    if (line && dmax < 0 && dmin < 0) hi = Math.max(hi, -line);
  }
  const span = Math.max(0.5, hi - lo);
  lo -= pad * span;
  hi += pad * span;
  return [lo, hi];
}

/**
 * Ticks at whole log2 steps (½×, 1×, 2×, 4×), thinned so labels are at least `minGap` pixels apart.
 * A zoomed-in axis (fewer than three whole steps in view) gets evenly spaced fold values instead
 * (2×, 2.2×, 2.4×, …), still placed on the log2 scale.
 */
export function foldTicks(lo: number, hi: number, pxPerUnit: number, minGap = 44): FoldTick[] {
  let step = 1;
  while (step * pxPerUnit < minGap && step < 64) step++;
  const out: FoldTick[] = [];
  for (let k = Math.ceil(lo); k <= Math.floor(hi); k++) {
    if (k % step === 0) out.push({ log2: k, label: foldTickLabel(k) });
  }
  if (out.length >= 3) return out;
  const n = Math.max(2, Math.floor(((hi - lo) * pxPerUnit) / (minGap * 2)));
  const fine = scaleLinear().domain([2 ** lo, 2 ** hi]).ticks(n);
  const ticks = fine.filter((v) => v > 0).map((v) => ({ log2: Math.log2(v), label: `${Number(v.toPrecision(3))}×` }));
  // keep the labels apart where the log scale squeezes them
  const kept: FoldTick[] = [];
  for (const t of ticks) if (!kept.length || (t.log2 - kept[kept.length - 1]!.log2) * pxPerUnit >= minGap) kept.push(t);
  return kept.length >= 2 ? kept : out;
}

/** A fold scale over [x0, x1] pixels for these log2 values. */
export function foldScale(
  values: readonly number[],
  line: number,
  x0: number,
  x1: number,
  minGap = 44,
  zero = true,
): FoldScale {
  const [lo, hi] = foldDomain(values, line, 0.1, zero);
  const x = scaleLinear().domain([lo, hi]).range([x0, Math.max(x0 + 1, x1)]);
  return { x, lo, hi, ticks: foldTicks(lo, hi, (x1 - x0) / (hi - lo), minGap) };
}

/** Which side of the call lines a log2 fold is on: beyond up, beyond down, or between. */
export function sideOfLine(log2: number, line: number): "up" | "down" | "between" {
  if (log2 >= line) return "up";
  if (log2 <= -line) return "down";
  return "between";
}

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

/** The label of a whole-number log2 tick: `1×`, `2×`, `16×`, `½×`, `¼×`, `1/8×`. */
export function foldTickLabel(k: number): string {
  if (k === 0) return "1×";
  if (k > 0) return `${2 ** k}×`;
  if (k === -1) return "½×";
  if (k === -2) return "¼×";
  return `1/${2 ** -k}×`;
}

/**
 * The domain of a fold axis (log2): the data, the call lines and 1× all inside, with a little air.
 * `line` is the call rule's minimum |log2 fold| (1 for "at least 2-fold"); 0 means no lines.
 */
export function foldDomain(values: readonly number[], line = 0, pad = 0.1): [number, number] {
  const finite = values.filter(Number.isFinite);
  let lo = Math.min(0, -line, ...finite);
  let hi = Math.max(0, line, ...finite);
  const span = Math.max(0.5, hi - lo);
  lo -= pad * span;
  hi += pad * span;
  return [lo, hi];
}

/** Whole-number log2 ticks, thinned so labels are at least `minGap` pixels apart. */
export function foldTicks(lo: number, hi: number, pxPerUnit: number, minGap = 44): FoldTick[] {
  let step = 1;
  while (step * pxPerUnit < minGap && step < 64) step++;
  const out: FoldTick[] = [];
  for (let k = Math.ceil(lo); k <= Math.floor(hi); k++) {
    if (k % step === 0) out.push({ log2: k, label: foldTickLabel(k) });
  }
  return out;
}

/** A fold scale over [x0, x1] pixels for these log2 values. */
export function foldScale(
  values: readonly number[],
  line: number,
  x0: number,
  x1: number,
  minGap = 44,
): FoldScale {
  const [lo, hi] = foldDomain(values, line);
  const x = scaleLinear().domain([lo, hi]).range([x0, Math.max(x0 + 1, x1)]);
  return { x, lo, hi, ticks: foldTicks(lo, hi, (x1 - x0) / (hi - lo), minGap) };
}

/** Which side of the call lines a log2 fold is on: beyond up, beyond down, or between. */
export function sideOfLine(log2: number, line: number): "up" | "down" | "between" {
  if (log2 >= line) return "up";
  if (log2 <= -line) return "down";
  return "between";
}

/** Deterministic layouts: the beeswarm, the dot histogram and collision-free direct labels. */

export interface Placed<T> {
  item: T;
  x: number;
  /** Offset from the row's centre line (beeswarm) or from the baseline (histogram). */
  dy: number;
}

/**
 * A beeswarm along x: each dot as close to the centre line as it can sit without touching
 * another (diameter `2r + gap`). If the swarm is taller than `maxHalf`, offsets are squeezed to
 * fit (dots may then touch; the table view keeps every value reachable).
 */
export function beeswarm<T>(items: readonly T[], xOf: (t: T) => number, r: number, maxHalf: number, gap = 1): Placed<T>[] {
  const d = 2 * r + gap;
  const sorted = items.map((item) => ({ item, x: xOf(item) })).sort((a, b) => a.x - b.x);
  const placed: Placed<T>[] = [];
  let start = 0;
  for (const p of sorted) {
    while (start < placed.length && placed[start]!.x < p.x - d) start++;
    const near = placed.slice(start);
    // candidate offsets: 0, then just above / below each neighbour, closest first
    const cands = [0];
    for (const q of near) {
      const dx = p.x - q.x;
      const h = Math.sqrt(Math.max(0, d * d - dx * dx));
      cands.push(q.dy + h, q.dy - h);
    }
    cands.sort((a, b) => Math.abs(a) - Math.abs(b) || a - b);
    let dy = 0;
    for (const c of cands) {
      const ok = near.every((q) => (p.x - q.x) ** 2 + (c - q.dy) ** 2 >= d * d - 1e-6);
      if (ok) {
        dy = c;
        break;
      }
    }
    placed.push({ item: p.item, x: p.x, dy });
  }
  const tallest = Math.max(0, ...placed.map((p) => Math.abs(p.dy)));
  if (tallest > maxHalf && tallest > 0) {
    const k = maxHalf / tallest;
    for (const p of placed) p.dy *= k;
  }
  return placed;
}

/**
 * A dot histogram: dots stacked upward in pixel bins one diameter wide (`dy` = level × diameter).
 * Within a bin, items keep the order of `rank` (so colours group), lowest first.
 */
export function dotStack<T>(items: readonly T[], xOf: (t: T) => number, r: number, rank: (t: T) => number = () => 0, gap = 1.5): Placed<T>[] {
  const d = 2 * r + gap;
  const bins = new Map<number, T[]>();
  for (const it of items) {
    const b = Math.round(xOf(it) / d);
    const list = bins.get(b);
    if (list) list.push(it);
    else bins.set(b, [it]);
  }
  const out: Placed<T>[] = [];
  for (const [b, list] of bins) {
    list.sort((a, c) => rank(a) - rank(c));
    list.forEach((item, level) => out.push({ item, x: b * d, dy: level * d }));
  }
  return out;
}

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface LabelSpot {
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
}

/** Approximate width of a label at 11 px (Inter): enough to keep labels apart. */
export function textWidth(text: string, size = 11): number {
  return text.length * size * 0.6 + 2;
}

/**
 * Direct labels that never overlap a mark, another label or the edge: candidates are tried
 * right, left, above, below; a label that cannot fit is left out (its value stays in the
 * tooltip and the table).
 */
export function placeLabels<T>(
  wanted: readonly { item: T; x: number; y: number; text: string }[],
  obstacles: Box[],
  bounds: Box,
  gap = 8,
): { item: T; text: string; spot: LabelSpot }[] {
  const taken = [...obstacles];
  const hits = (b: Box) => taken.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0);
  const out: { item: T; text: string; spot: LabelSpot }[] = [];
  for (const w of wanted) {
    const tw = textWidth(w.text);
    const spots: LabelSpot[] = [
      { x: w.x + gap, y: w.y + 4, anchor: "start" },
      { x: w.x - gap, y: w.y + 4, anchor: "end" },
      { x: w.x, y: w.y - gap - 2, anchor: "middle" },
      { x: w.x, y: w.y + gap + 10, anchor: "middle" },
      { x: w.x + gap - 2, y: w.y - gap, anchor: "start" },
      { x: w.x - gap + 2, y: w.y + gap + 8, anchor: "end" },
    ];
    for (const s of spots) {
      const x0 = s.anchor === "start" ? s.x : s.anchor === "end" ? s.x - tw : s.x - tw / 2;
      const box = { x0, x1: x0 + tw, y0: s.y - 10, y1: s.y + 2 };
      if (box.x0 < bounds.x0 || box.x1 > bounds.x1 || box.y0 < bounds.y0 || box.y1 > bounds.y1) continue;
      if (hits(box)) continue;
      taken.push(box);
      out.push({ item: w.item, text: w.text, spot: s });
      break;
    }
  }
  return out;
}

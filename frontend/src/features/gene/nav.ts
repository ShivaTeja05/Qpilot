/** Moving between genes: the study's order, and the gene before and after the open one. */

export interface GeneNeighbours {
  prev: string | null;
  next: string | null;
  /** 1-based position of the open gene (0 when it is not in the list). */
  position: number;
  total: number;
}

/** The gene before and after `gene` in `order` (no wrap-around: the ends have no neighbour). */
export function neighbours(order: readonly string[], gene: string | null): GeneNeighbours {
  const i = gene == null ? -1 : order.indexOf(gene);
  if (i < 0) return { prev: null, next: order[0] ?? null, position: 0, total: order.length };
  return {
    prev: i > 0 ? (order[i - 1] ?? null) : null,
    next: i < order.length - 1 ? (order[i + 1] ?? null) : null,
    position: i + 1,
    total: order.length,
  };
}

/** The gene named in the route, matched to the study's spelling (case-insensitive). */
export function resolveGene(order: readonly string[], wanted: string | undefined): string | null {
  if (!wanted) return null;
  if (order.includes(wanted)) return wanted;
  const lower = wanted.toLowerCase();
  return order.find((g) => g.toLowerCase() === lower) ?? null;
}

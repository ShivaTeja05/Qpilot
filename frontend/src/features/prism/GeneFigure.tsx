/**
 * The Prism figure of one gene, for other sections (Gene's aside): every biological unit, the
 * group means and their 95 % confidence intervals, as the Prism bundle will hold them. Renders
 * nothing when the session's Prism project has no table for the gene (only its genes get one),
 * or before the results are visible (the server refuses then).
 *
 *   import { GenePrismFigure, useHasPrismFigure } from "@/features/prism/GeneFigure";
 *   {useHasPrismFigure(sid, gene) && <GenePrismFigure sid={sid} gene={gene} />}
 */
import { LoadingBlock } from "@/ui";
import { usePrismPreview } from "./api";
import { PrismFigure } from "./PrismFigure";

export function GenePrismFigure({ sid, gene }: { sid: string; gene: string }) {
  const listed = usePrismPreview(sid);
  const has = Boolean(listed.data?.genes.includes(gene));
  const preview = usePrismPreview(sid, gene, has);
  if (listed.isPending || (has && preview.isPending)) return <LoadingBlock label="Reading the Prism preview" lines={3} />;
  const figure = preview.data?.figure;
  if (!has || !figure || figure.gene !== gene || !figure.groups.some((g) => g.n > 0)) return null;
  return <PrismFigure figure={figure} caption={figure.note} />;
}

/** True when the session's Prism project has a table for `gene` (whether to show a card at all). */
export function useHasPrismFigure(sid: string, gene: string): boolean {
  const preview = usePrismPreview(sid);
  return Boolean(preview.data?.genes.includes(gene));
}

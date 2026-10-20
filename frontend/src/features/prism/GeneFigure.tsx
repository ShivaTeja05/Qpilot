/**
 * The Prism figure of one gene, for other sections (Gene's aside): every biological unit, the
 * group means and their 95 % confidence intervals, as the Prism bundle will hold them. Renders
 * nothing when the session's Prism preview has no table for the gene (only the project's genes
 * get one), or before the results are visible (the server refuses then).
 *
 *   import { GenePrismFigure } from "@/features/prism/GeneFigure";
 *   <GenePrismFigure sid={workspace.key} gene="ODC1" />
 */
import { LoadingBlock } from "@/ui";
import { usePrismPreview } from "./api";
import { PrismFigure } from "./PrismFigure";
import { pointsFromTable } from "./tables";

export { usePrismPreview } from "./api";

export function GenePrismFigure({ sid, gene }: { sid: string; gene: string }) {
  const preview = usePrismPreview(sid);
  if (preview.isPending) return <LoadingBlock label="Reading the Prism preview" lines={3} />;
  const data = preview.data;
  const table = data?.tables?.[gene];
  if (!data || !table) return null;
  const figure = data.figures?.[gene] ?? pointsFromTable(gene, table, data.template.layout);
  if (!figure || !figure.groups.some((g) => g.points.length)) return null;
  return (
    <PrismFigure
      figure={figure}
      caption="What the Prism bundle holds for this gene: every biological unit, the group mean and its 95 % confidence interval. Prism draws the real graph."
    />
  );
}

/** True when the session's Prism preview has a table for `gene` (to decide whether to show a card). */
export function useHasPrismFigure(sid: string, gene: string): boolean {
  const preview = usePrismPreview(sid);
  return Boolean(preview.data?.tables?.[gene]);
}

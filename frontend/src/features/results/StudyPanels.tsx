/** The flip matrix and the reference genes' stability, below the table. */
import { useCallback, useMemo } from "react";
import { FlipMatrix, GenormBars } from "@/charts";
import { count } from "@/lib/format";
import { Card, CardBody, CardHeader } from "@/ui";
import type { GeneRow, ResultsView } from "./api";

type Impact = Record<string, { flips?: boolean; max_delta_log2fc?: number | null }>;

export function FlipPanel({
  genes,
  dims,
  dimLabel,
  onOpen,
}: {
  genes: GeneRow[];
  dims: string[];
  dimLabel: (dim: string) => string;
  onOpen: (gene: string) => void;
}) {
  const byGene = useMemo(() => new Map(genes.map((g) => [g.gene, g])), [genes]);
  const cell = useCallback(
    (dim: string, gene: string) => {
      const g = byGene.get(gene);
      if (!g) return undefined;
      const impact = (g as GeneRow & { impact?: Impact }).impact?.[dim];
      return { flips: g.flips_by.includes(dim), delta: impact?.max_delta_log2fc ?? null };
    },
    [byGene],
  );
  const decisions = useMemo(() => dims.map((id) => ({ id, label: dimLabel(id) })), [dims, dimLabel]);
  const names = useMemo(() => genes.map((g) => g.gene), [genes]);
  const flipping = genes.filter((g) => g.flips_by.length > 0).length;
  const perDim = dims.map((d) => `${dimLabel(d).toLowerCase()} ${count(genes.filter((g) => g.flips_by.includes(d)).length)}`).join(", ");
  return (
    <Card as="section" aria-labelledby="flips-title">
      <CardHeader
        id="flips-title"
        title="What one choice alone can flip"
        hint={`${count(flipping)} of ${count(genes.length)} genes change their call when a single choice changes and everything else stays as recommended.`}
      />
      <CardBody>
        <FlipMatrix
          decisions={decisions}
          genes={names}
          cell={cell}
          onSelectGene={onOpen}
          summary={`Decisions by genes: a cross where that decision alone changes the gene's call. Genes flipped per decision: ${perDim}.`}
          caption="Each row is a decision on a Decision Card; each column a gene, the genes that flip most first. Decide those cards before you report the genes they flip."
        />
      </CardBody>
    </Card>
  );
}

export function ReferencesPanel({ view }: { view: ResultsView }) {
  const g = view.references.genorm;
  return (
    <Card as="section" aria-labelledby="refs-title">
      <CardHeader
        id="refs-title"
        title="Reference genes"
        hint={`The analysis normalises to ${view.references.used.join(", ")}. geNorm ranks the candidates by how steady they are across samples.`}
      />
      <CardBody>
        <GenormBars m={g.M_initial} order={g.order} cutoffM={g.cutoff_M} v={g.V} cutoffV={g.cutoff_V} used={view.references.used} />
      </CardBody>
    </Card>
  );
}

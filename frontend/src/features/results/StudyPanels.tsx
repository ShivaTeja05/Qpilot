/** The flip matrix and the reference genes' stability, below the table. */
import { useCallback, useMemo } from "react";
import { FlipMatrix, GenormBars } from "@/charts";
import { count, plural } from "@/lib/format";
import { Card, CardBody, CardHeader, Skeleton } from "@/ui";
import type { FlipsView, ResultsView } from "./api";

export function FlipPanel({
  flips,
  onOpen,
}: {
  flips: FlipsView | undefined;
  onOpen: (gene: string) => void;
}) {
  const index = useMemo(() => new Map((flips?.genes ?? []).map((g, i) => [g, i])), [flips]);
  const rows = useMemo(() => new Map((flips?.rows ?? []).map((r) => [r.dimension, r])), [flips]);
  const cell = useCallback(
    (dim: string, gene: string) => {
      const r = rows.get(dim);
      const i = index.get(gene);
      if (!r || i == null) return undefined;
      // the shade: the share of this decision's other options that change the call
      const others = r.options.filter((o) => !o.planned);
      const flipping = others.filter((o) => o.flips[i]).length;
      return {
        flips: Boolean(r.flips[i]),
        delta: others.length ? flipping / others.length : 0,
        note: `${count(flipping)} of ${count(others.length)} other options change the call`,
      };
    },
    [rows, index],
  );
  const decisions = useMemo(
    () => (flips?.rows ?? []).map((r) => ({ id: r.dimension, label: r.title })),
    [flips],
  );
  if (!flips) return <Skeleton className="h-64 w-full rounded-xl" />;
  const flipping = flips.genes.filter((_, i) => flips.rows.some((r) => r.flips[i])).length;
  const perDim = flips.rows.map((r) => `${r.title.toLowerCase()} ${count(r.n_flipped)}`).join(", ");
  return (
    <Card as="section" aria-labelledby="flips-title">
      <CardHeader
        id="flips-title"
        title="What one choice alone can flip"
        hint={
          flipping === 0
            ? "No gene changes its call when a single decision changes and everything else stays as it is."
            : `${count(flipping)} of ${plural(flips.genes.length, "gene")} ${flipping === 1 ? "changes its" : "change their"} call when a single decision changes and everything else stays as it is.`
        }
      />
      <CardBody>
        <FlipMatrix
          decisions={decisions}
          genes={flips.genes}
          cell={cell}
          onSelectGene={onOpen}
          shadeLabel="Share of the decision's other options that change the call (darker: more)"
          summary={`Decisions by genes: a cross where that decision alone changes the gene's call. Calls changed per decision: ${perDim}.`}
          caption="Each row is a decision on a Decision Card; each column a gene, the genes that flip most first. Decide those cards before you report the genes they flip."
        />
      </CardBody>
    </Card>
  );
}

export function ReferencesPanel({ view }: { view: ResultsView }) {
  const g = view.references;
  return (
    <Card as="section" aria-labelledby="refs-title">
      <CardHeader
        id="refs-title"
        title="Reference genes"
        hint={`The analysis normalises to ${g.used.join(", ")}. geNorm ranks the candidates by how steady they are across samples.`}
      />
      <CardBody>
        <GenormBars
          m={g.m}
          order={g.order}
          cutoffM={g.cutoff_m}
          v={g.v}
          cutoffV={g.cutoff_v}
          used={g.used}
        />
      </CardBody>
    </Card>
  );
}

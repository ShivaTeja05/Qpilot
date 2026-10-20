/** The hero chart: the robustness map of every gene, coloured by call, confidence or verdict. */
import { useMemo } from "react";
import {
  CALLS,
  CALL_ORDER,
  LEVELS,
  LEVEL_ORDER,
  LineSwatch,
  RobustnessMap,
  VERDICTS,
  VERDICT_ORDER,
  resultsMapPoints,
  type LegendItem,
  type MapEncoding,
} from "@/charts";
import { count } from "@/lib/format";
import { Card, CardBody, CardHeader, SegmentedControl } from "@/ui";
import type { GeneRow, ResultsView } from "./api";

/** The size of qPilot's choice grid, when every gene was checked over the same one. */
export function gridSize(genes: readonly GeneRow[]): number | null {
  const sizes = new Set(genes.filter((g) => g.holds != null).map((g) => g.n_cells));
  return sizes.size === 1 ? [...sizes][0]! : null;
}

export function MapPanel({
  view,
  by,
  onBy,
  highlight,
  selected,
  onOpen,
}: {
  view: ResultsView;
  by: MapEncoding;
  onBy: (by: MapEncoding) => void;
  highlight: ReadonlySet<string> | null;
  selected: string | null;
  onOpen: (gene: string) => void;
}) {
  const genes = view.genes;
  const audited = genes.some((g) => g.verdict);
  const points = useMemo(
    () =>
      resultsMapPoints(
        genes.filter((g): g is GeneRow & { holds: number } => g.holds != null),
        by,
      ),
    [genes, by],
  );
  const line = view.rule.min_log2fc;
  const lineFold = `${Number((2 ** line).toPrecision(3))}×`;
  const legend: LegendItem[] = useMemo(() => {
    const tally = (pred: (g: GeneRow) => boolean) => genes.filter(pred).length;
    const items: LegendItem[] =
      by === "level"
        ? LEVEL_ORDER.map((l) => ({
            mark: LEVELS[l],
            label: `${l} confidence`,
            count: tally((g) => g.level === l),
          }))
        : by === "verdict"
          ? VERDICT_ORDER.map((v) => ({
              mark: VERDICTS[v],
              label: VERDICTS[v].label,
              count: tally((g) => g.verdict === v),
            }))
          : CALL_ORDER.map((c) => ({
              mark: CALLS[c],
              label: CALLS[c].label,
              count: tally((g) => g.conclusion === c),
            }));
    return [
      ...items.filter((i) => i.count),
      { swatch: <LineSwatch dashed />, label: `${lineFold} line` },
    ];
  }, [genes, by, lineFold]);

  const cells = gridSize(genes);
  const setWords = cells
    ? `of the ${count(cells)} analyses qPilot checks`
    : "of the analyses qPilot checks";
  const oneChoice = genes.filter((g) => g.conclusion !== "none" && g.flips_by.length > 0).length;
  const called = genes.filter((g) => g.conclusion !== "none").length;
  const group = view.summary.groups[0]?.label;
  const summary =
    `Robustness map of ${count(genes.length)} genes: fold change across, and up, the share ${setWords} that give the same call. ` +
    `${count(called)} genes are called; a single choice can change the call of ${count(oneChoice)} of them.`;

  return (
    <Card as="section" aria-labelledby="map-title">
      <CardHeader
        id="map-title"
        title="Robustness map"
        hint={`Every gene: how large the change is, and in what share ${setWords} it keeps its call (qPilot's choice grid: every control-gene set, cut-off, empty-well rule and amplification-call rule). Genes low on the map lean on the choices made.`}
        actions={
          <SegmentedControl<MapEncoding>
            label="Colour the genes by"
            size="sm"
            value={by}
            onValueChange={onBy}
            options={[
              { value: "conclusion", label: "Call" },
              { value: "level", label: "Confidence" },
              {
                value: "verdict",
                label: "Audit verdict",
                disabled: !audited,
                title: audited ? undefined : "Run the robustness audit to see each gene's verdict",
              },
            ]}
          />
        }
      />
      <CardBody>
        <RobustnessMap
          points={points}
          line={line}
          lineLabel={`${lineFold} line`}
          lower={group ? `lower in ${group}` : "lower"}
          higher={group ? `higher in ${group}` : "higher"}
          legend={legend}
          summary={summary}
          setWords={setWords}
          yLabel={
            cells
              ? `Same call in qPilot's choice grid (${count(cells)} analyses)`
              : "Same call in qPilot's choice grid"
          }
          selected={selected}
          highlight={highlight}
          onSelect={onOpen}
          caption="Hover or use the arrow keys to read a gene; click or press Enter to open it. Confidence is a level with named reasons, never a percentage."
        />
      </CardBody>
    </Card>
  );
}

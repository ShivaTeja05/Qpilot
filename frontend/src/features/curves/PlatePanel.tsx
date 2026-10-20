/**
 * The plate heatmap of the Curves stage: pick a gene (and its plate), switch the layer (call,
 * Cq, efficiency, R², sample type), select wells. Blind: the plate map has no group field.
 */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { PlateMap, layerOptions, plateWells, type PlateLayer } from "@/charts/plate";
import { count } from "@/lib/format";
import { useHotkeys } from "@/lib/hooks";
import {
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  IconButton,
  LoadingBlock,
  SegmentedControl,
  Select,
} from "@/ui";
import type { PlateView } from "./api";

export const ALL_GENES = "__all__";

const LAYERS: PlateLayer[] = ["call", "cq", "efficiency", "r2", "role"];

export interface PlatePanelProps {
  plate: PlateView | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  gene: string;
  onGeneChange: (gene: string) => void;
  onRunChange: (run: string) => void;
  layer: PlateLayer;
  onLayerChange: (layer: PlateLayer) => void;
  selected: readonly string[];
  onSelectedChange: (wells: string[]) => void;
  onActivate?: (well: string) => void;
  /** Busy re-reading another plate (the previous one stays on screen). */
  fetching?: boolean;
}

export function PlatePanel({
  plate,
  loading,
  error,
  onRetry,
  gene,
  onGeneChange,
  onRunChange,
  layer,
  onLayerChange,
  selected,
  onSelectedChange,
  onActivate,
  fetching,
}: PlatePanelProps) {
  const runs = useMemo(() => (plate?.runs ?? []).filter((r) => r.in_design), [plate?.runs]);
  const others = useMemo(() => (plate?.runs ?? []).filter((r) => !r.in_design), [plate?.runs]);
  const genes = useMemo(
    () => [...new Set(runs.flatMap((r) => r.targets))].sort((a, b) => a.localeCompare(b)),
    [runs],
  );
  const shownRuns = gene === ALL_GENES ? runs : runs.filter((r) => r.targets.includes(gene));
  const current = plate?.run.run_id ?? null;
  const at = shownRuns.findIndex((r) => r.run_id === current);

  const wells = useMemo(
    () =>
      plate ? plateWells(plate, gene === ALL_GENES ? {} : { keep: (w) => w.target === gene }) : [],
    [plate, gene],
  );

  const step = (by: number) => {
    const i = runs.findIndex((r) => r.run_id === current);
    const next = runs[(i + by + runs.length) % runs.length];
    if (!next) return;
    if (gene !== ALL_GENES) onGeneChange(next.targets[0] ?? ALL_GENES);
    onRunChange(next.run_id);
  };
  useHotkeys({ "[": () => step(-1), "]": () => step(1) }, runs.length > 1);

  const disagreements = plate?.wells.filter((w) => w.disagrees).length ?? 0;
  const waiting = plate?.wells.filter((w) => w.proposal_id).length ?? 0;

  return (
    <Card as="section" aria-labelledby="curves-plate-title">
      <CardHeader
        id="curves-plate-title"
        title="The plate"
        hint={
          plate
            ? `${plate.run.run_id} · ${plate.n_rows * plate.n_cols} positions · ${plural(plate.wells.length, "well")}${
                disagreements ? ` · the Curve Judge disagrees on ${count(disagreements)}` : ""
              }${waiting ? ` · ${count(waiting)} with a proposal waiting` : ""}`
            : "Every well of one plate; pick a well to see its curve."
        }
      />
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
          <label className="flex min-w-0 flex-col gap-1 text-[12px] font-medium text-muted">
            Gene
            <Select
              size="sm"
              label="Gene"
              className="w-44"
              value={gene}
              onValueChange={(g) => {
                onGeneChange(g);
                const first = g === ALL_GENES ? null : runs.find((r) => r.targets.includes(g));
                if (first && first.run_id !== current) onRunChange(first.run_id);
              }}
              options={[
                { value: ALL_GENES, label: "All genes" },
                ...genes.map((g) => ({ value: g, label: g })),
              ]}
            />
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-[12px] font-medium text-muted">
            Plate
            <Select
              size="sm"
              label="Plate"
              className="w-60"
              value={current ?? undefined}
              onValueChange={onRunChange}
              options={[
                ...shownRuns.map((r) => ({
                  value: r.run_id,
                  label: r.run_id,
                  hint: `${r.targets.join(", ")} · ${count(r.n_wells)} wells`,
                })),
                ...(gene === ALL_GENES
                  ? others.map((r) => ({
                      value: r.run_id,
                      label: r.run_id,
                      hint: `not in the analysed experiment (${r.experiment_id})`,
                    }))
                  : []),
              ]}
            />
          </label>
          <div className="flex items-center gap-1 pb-0.5">
            <IconButton
              label="Previous plate ([)"
              size="sm"
              onClick={() => step(-1)}
              disabled={runs.length < 2}
            >
              <ChevronLeft />
            </IconButton>
            <IconButton
              label="Next plate (])"
              size="sm"
              onClick={() => step(1)}
              disabled={runs.length < 2}
            >
              <ChevronRight />
            </IconButton>
            {at >= 0 && shownRuns.length > 1 ? (
              <span className="ml-1 text-[12px] text-faint tabular">
                {count(at + 1)} of {count(shownRuns.length)}
              </span>
            ) : null}
          </div>
          <div className="ml-auto max-w-full overflow-x-auto">
            <SegmentedControl<PlateLayer>
              size="sm"
              label="Colour the wells by"
              value={layer}
              onValueChange={onLayerChange}
              options={layerOptions(LAYERS).map((o) => ({
                ...o,
                disabled: o.value !== "role" && plate != null && !plate.curves_shown,
              }))}
            />
          </div>
        </div>

        {error && !plate ? (
          <ErrorPanel error={error} onRetry={onRetry} compact />
        ) : loading && !plate ? (
          <LoadingBlock label="Reading the plate" lines={6} />
        ) : plate ? (
          <div
            className={fetching ? "opacity-60 transition-opacity" : undefined}
            aria-busy={fetching || undefined}
          >
            <PlateMap
              wells={wells}
              layer={layer}
              label={`Plate ${plate.run.run_id}`}
              rows={plate.n_rows}
              columns={plate.n_cols}
              selected={selected}
              onSelectedChange={onSelectedChange}
              onActivate={onActivate}
              caption={
                <>
                  {plate.curves_note} The Curve Judge {plate.curve_judge}.{" "}
                  {!plate.run.in_design
                    ? "This plate is not in the experiment the design analyses. "
                    : null}
                  Click a well for its curve; ⌘/Ctrl-click or Shift-click to compare several; arrow
                  keys move, Space selects, Enter opens.
                </>
              }
            />
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function plural(n: number, one: string): string {
  return `${count(n)} ${n === 1 ? one : `${one}s`}`;
}

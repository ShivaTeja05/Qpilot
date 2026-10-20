/**
 * One well, opened from the trace: what it is and what is unusual about it, its raw curve
 * (Studio sessions: the curve comes from the session's file) and its plate with the well
 * highlighted (from the trace's own well table, so any workspace has it). Clicking another
 * well on the plate opens that one.
 */
import { ArrowUpRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "wouter";
import { CurveViewer, curveSeries } from "@/charts/curves";
import { PlateMap, layerOptions, type PlateLayer, type PlateWell } from "@/charts/plate";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { Badge, ErrorPanel, KeyValues, LoadingBlock, SegmentedControl } from "@/ui";
import { count, fixed } from "@/lib/format";
import { useTracePlate, useWellCurve, type TraceScope, type Well } from "./api";
import { WELL_FLAG, wellRole } from "./words";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

export function plateWellsOf(wells: readonly Well[]): PlateWell[] {
  return wells.map((w) => ({
    well: w.well,
    sample: w.sample,
    target: w.gene,
    role: w.sample_type,
    amplified: w.sample_type === "unkn" || w.cq != null ? w.amplified : null,
    cq: w.cq ?? null,
    efficiency: w.efficiency ?? null,
    notes: w.flags.map((f) => WELL_FLAG[f]?.detail ?? f),
  }));
}

export function WellFacts({ well }: { well: Well }) {
  const rows: [string, string][] = [
    ["Plate · well", `${well.plate} · ${well.well}`],
    ["Sample", well.sample === well.unit ? well.sample : `${well.sample} (sample ${well.unit})`],
    ["Gene", `${well.gene} (${wellRole(well)})`],
    ["Cq", well.cq != null ? fixed(well.cq, 2) : well.amplified ? "—" : "no curve (not amplified)"],
  ];
  if (well.plate_median_cq != null)
    rows.push(["Plate median Cq (this gene)", fixed(well.plate_median_cq, 2)]);
  if (well.efficiency != null) rows.push(["Efficiency", fixed(well.efficiency, 3)]);
  if (well.pull_log2 != null && well.flags.includes("reference_pull")) {
    const factor = 2 ** Math.abs(well.pull_log2);
    rows.push([
      "What it does",
      `Every value of sample ${well.unit} is ${fixed(factor, 2)}× ${well.pull_log2 > 0 ? "too high" : "too low"} because of it`,
    ]);
  }
  if (well.lowest_standard && well.lowest_standard_cq != null)
    rows.push([
      "Fewest-copies standard on the plate",
      `${well.lowest_standard} at Cq ${fixed(well.lowest_standard_cq, 1)}`,
    ]);
  if (well.ntc_well && well.ntc_cq != null)
    rows.push([
      "Amplifying no-template control",
      `${well.ntc_well} at Cq ${fixed(well.ntc_cq, 1)}`,
    ]);
  if (well.note) rows.push(["LinRegPCR's note", well.note]);
  return (
    <div className="flex flex-col gap-3">
      {well.flags.length ? (
        <ul className="flex flex-col gap-1.5" aria-label="What is unusual">
          {well.flags.map((f) => (
            <li key={f} className="flex items-start gap-2 text-[13px]">
              <Badge
                tone={f === "reference_pull" || f === "ntc_window" ? "warn" : "neutral"}
                className="shrink-0"
              >
                {WELL_FLAG[f]?.word ?? f}
              </Badge>
              <span className="text-muted">{WELL_FLAG[f]?.detail}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">Nothing unusual in this well.</p>
      )}
      <KeyValues rows={rows} />
    </div>
  );
}

export function WellCurve({
  workspace,
  scope,
  well,
}: {
  workspace: Workspace;
  scope: TraceScope;
  well: Well;
}) {
  const curve = useWellCurve(scope, well.key, well.gene);
  if (scope.kind !== "session") {
    return (
      <p className="text-xs text-muted">
        Raw curves open from a Studio session of this file; this study was analysed outside one.
      </p>
    );
  }
  if (curve.error)
    return <ErrorPanel compact error={curve.error} onRetry={() => void curve.refetch()} />;
  if (!curve.data) return <LoadingBlock lines={3} label="Reading the well's curve" />;
  const c = curve.data;
  return (
    <CurveViewer
      series={curveSeries(c)}
      yLabel="Fluorescence (raw)"
      label={`Well ${c.well} of plate ${c.run_id}, sample ${c.sample}, ${c.target}`}
      height={200}
      caption={
        c.replicates.length
          ? `The other ${count(c.replicates.length)} wells of this sample on the plate are drawn faint.`
          : undefined
      }
      controls={
        <Link
          href={sectionPath(workspace, "curves", c.run_id, c.well)}
          className="inline-flex items-center gap-1 text-xs text-accent underline-offset-4 hover:underline"
        >
          Open in Curves
          <ArrowUpRight className="size-3" aria-hidden />
        </Link>
      }
    />
  );
}

const LAYERS: PlateLayer[] = ["cq", "call", "efficiency", "role"];

export function WellPlate({
  scope,
  well,
  onWell,
}: {
  scope: TraceScope;
  well: Well;
  /** Another well of the plate was chosen. */
  onWell: (well: Well) => void;
}) {
  const plate = useTracePlate(scope, well.plate);
  const [layer, setLayer] = useState<PlateLayer>("cq");
  const wells = plate.data?.plate.wells;
  const forGene = useMemo(
    () => (wells ? wells.filter((w) => w.gene === well.gene) : []),
    [wells, well.gene],
  );
  const mapped = useMemo(() => plateWellsOf(forGene), [forGene]);
  if (plate.error)
    return <ErrorPanel compact error={plate.error} onRetry={() => void plate.refetch()} />;
  if (!plate.data) return <LoadingBlock lines={4} label={`Reading plate ${well.plate}`} />;
  const genes = plate.data.plate.genes;
  return (
    <PlateMap
      wells={mapped}
      layer={layer}
      label={`Plate ${well.plate}${genes.length > 1 ? `, ${well.gene} wells` : ""}`}
      selected={[well.well]}
      multiple={false}
      onSelectedChange={(picked) => {
        const next = forGene.find((w) => w.well === picked[0]);
        if (next && next.key !== well.key) onWell(next);
      }}
      controls={
        <SegmentedControl
          size="sm"
          label="Colour the wells by"
          value={layer}
          onValueChange={(v) => setLayer(v as PlateLayer)}
          options={layerOptions(LAYERS)}
        />
      }
      caption={`Well ${well.well} is selected. Click another well to open it.`}
    />
  );
}

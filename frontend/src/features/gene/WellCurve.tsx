/**
 * A picked sample's well: its raw amplification curve (curves' CurveViewer, with the other wells
 * of the same sample on the plate faint) and LinRegPCR's numbers for it. Studio sessions only:
 * the curves come from the session's file.
 */
import { ArrowUpRight } from "lucide-react";
import { Link } from "wouter";
import { CurveViewer, curveSeries } from "@/charts/curves";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { ErrorPanel, LoadingBlock } from "@/ui";
import { count, fixed } from "@/lib/format";
import { useWellCurve, type GeneScope } from "./api";
import { FactRows } from "./Panel";

export function WellCurve({
  workspace,
  scope,
  plate,
  well,
  gene,
}: {
  workspace: Pick<Schemas["WorkspaceView"], "key" | "kind">;
  scope: GeneScope;
  plate: string;
  well: string;
  gene: string;
}) {
  const curve = useWellCurve(scope, `${plate}/${well}`, gene);
  if (scope.kind !== "session") {
    return (
      <p className="text-xs text-muted">
        Curves open from a Studio session of this file; this study was analysed outside one.
      </p>
    );
  }
  if (curve.error)
    return <ErrorPanel compact error={curve.error} onRetry={() => void curve.refetch()} />;
  if (!curve.data) return <LoadingBlock lines={3} label="Reading the well's curve" />;
  const c = curve.data;
  const amplified =
    c.amplified == null ? "not called" : c.amplified ? "yes" : "no (no usable curve)";
  return (
    <div>
      <CurveViewer
        series={curveSeries(c)}
        yLabel="Fluorescence (raw)"
        label={`Well ${c.well} of plate ${c.run_id}, sample ${c.sample}, ${c.target}`}
        height={220}
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
      {c.numbers_shown ? (
        <FactRows
          className="mt-3"
          rows={[
            ["Amplified", amplified],
            ["Cq (LinRegPCR)", fixed(c.cq, 2)],
            ["Efficiency", fixed(c.efficiency, 2)],
            ["R² of the exponential phase", fixed(c.r2, 3)],
          ]}
        />
      ) : (
        <p className="mt-2 text-xs text-muted">{c.note}</p>
      )}
    </div>
  );
}

/** A picked sample's well as LinRegPCR read it (Studio sessions: the file's raw curves are there). */
import { ErrorPanel, KeyValues, LoadingBlock } from "@/ui";
import { count, fixed } from "@/lib/format";
import { useWellCurve, type GeneScope } from "./api";

export function WellCurve({ scope, plate, well, gene }: { scope: GeneScope; plate: string; well: string; gene: string }) {
  const curve = useWellCurve(scope, `${plate}/${well}`, gene);
  if (scope.kind !== "session") {
    return (
      <p className="text-xs text-muted">
        Curves open from a Studio session of this file; this study was analysed outside one.
      </p>
    );
  }
  if (curve.error) return <ErrorPanel compact error={curve.error} onRetry={() => void curve.refetch()} />;
  if (!curve.data) return <LoadingBlock lines={2} label="Reading the well's curve" />;
  const c = curve.data;
  const amplified = c.amplified == null ? "not called" : c.amplified ? "yes" : "no (no usable curve)";
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold text-fg">The well's curve, as LinRegPCR read it</h4>
      {c.numbers_shown ? (
        <KeyValues
          rows={[
            ["Amplified", amplified],
            ["Cq (LinRegPCR)", fixed(c.cq, 2)],
            ["Efficiency", fixed(c.efficiency, 2)],
            ["R² of the exponential phase", fixed(c.r2, 3)],
            ["Cycles read", count(c.cycle.length)],
            ["Replicate wells on this plate", count(c.replicates.length)],
          ]}
        />
      ) : (
        <p className="text-xs text-muted">{c.note}</p>
      )}
    </div>
  );
}

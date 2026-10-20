/**
 * A cited well's raw curve, in a dialog (from a check's wells or well evidence), drawn by the
 * shared curve viewer (`@/charts/curves`): fluorescence by cycle as the file has it, the other
 * wells of the same sample and target on the plate faint, and LinRegPCR's Cq and baseline only
 * when the server includes them.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { CurveViewer, curveSeries } from "@/charts/curves";
import { fixed } from "@/lib/format";
import { ROLE_WORDS } from "@/lib/vocab";
import { Dialog, ErrorPanel, KeyValues, LoadingBlock } from "@/ui";

export function WellCurveDialog({ sid, well, onClose }: { sid: string; well: string | null; onClose: () => void }) {
  const curve = useQuery({
    queryKey: ["w", sid, "curve", well],
    enabled: Boolean(well),
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/curve", { params: { path: { sid }, query: { well: well! } } })),
  });
  const c = curve.data;
  return (
    <Dialog open={Boolean(well)} onOpenChange={(o) => !o && onClose()} size="lg" title={`Curve of well ${well ?? ""}`} description={c?.note}>
      {curve.isPending ? <LoadingBlock label="Reading the curve" lines={5} /> : null}
      {curve.error ? <ErrorPanel error={curve.error} compact onRetry={() => void curve.refetch()} /> : null}
      {c ? (
        <div className="flex flex-col gap-3">
          <KeyValues
            rows={[
              ["Sample", <span className="font-mono">{c.sample}</span>],
              ["Target", <span className="font-mono">{c.target}</span>],
              ["Declared", ROLE_WORDS[c.declared_type] ?? c.declared_type],
              ...(c.numbers_shown
                ? ([
                    ["Cq (LinRegPCR)", c.cq != null ? fixed(c.cq, 2) : "none"],
                    ["Amplified (LinRegPCR)", c.amplified == null ? "—" : c.amplified ? "yes" : "no"],
                  ] as [string, string][])
                : []),
            ]}
          />
          <CurveViewer
            series={curveSeries(c)}
            yLabel="Fluorescence (raw)"
            label={`Well ${c.well} of plate ${c.run_id}`}
            caption={`Raw fluorescence as in the file; faint: the other wells of this sample and target on the plate${c.numbers_shown ? "; LinRegPCR's Cq and baseline are marked" : ""}.`}
          />
        </div>
      ) : null}
    </Dialog>
  );
}

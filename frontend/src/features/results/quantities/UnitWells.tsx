/**
 * From one sample's quantity to its wells (Trace for a quantity): every well of the unit with
 * its plate, Cq, whether it counts as detected and the quantity that well alone reads as, the
 * well farthest from the others named (the one to look at first when the replicates disagree),
 * and the curve of any well (in a Studio session). Every number is the API's.
 */
import { lazy, Suspense, useState } from "react";
import { fixed } from "@/lib/format";
import { Badge, Button } from "@/ui";
import type { UnitQuantity } from "./api";
import { fmtQuantity } from "./format";

/** The curve viewer (uPlot) loads only when a person opens a well's curve. */
const WellCurveDialog = lazy(() =>
  import("@/features/design/WellCurve").then((m) => ({ default: m.WellCurveDialog })),
);

/** The detected well whose own quantity is farthest (on the log scale) from the others' mean. */
export function farthestWell(unit: UnitQuantity): string | null {
  const read = unit.wells.filter((w) => w.detected && w.quantity != null && w.quantity > 0);
  if (read.length < 3) return null;
  let best: string | null = null;
  let gap = 0;
  for (const w of read) {
    const others = read.filter((o) => o !== w);
    const mean = others.reduce((s, o) => s + Math.log10(o.quantity!), 0) / others.length;
    const d = Math.abs(Math.log10(w.quantity!) - mean);
    if (d > gap) {
      gap = d;
      best = `${w.run_id}/${w.well}`;
    }
  }
  return gap > Math.log10(2) ? best : null; // only when it is more than 2-fold from the others
}

export function UnitWells({ unit, sid }: { unit: UnitQuantity; sid: string | null }) {
  const [curve, setCurve] = useState<string | null>(null);
  const odd = farthestWell(unit);
  return (
    <div className="space-y-2 py-1" data-testid="unit-wells">
      <p className="text-[12.5px] text-muted">
        {unit.unit}: {unit.n_detected} of {unit.n_wells} wells detected
        {unit.curves.length ? `, read from ${unit.curves.join(" and ")}` : ""}. The quantity is read
        from the mean Cq of the detected wells; each well alone reads as below.
      </p>
      <ul className="space-y-1 text-[12.5px]">
        {unit.wells.map((w) => {
          const key = `${w.run_id}/${w.well}`;
          return (
            <li key={key} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-fg">{key}</span>
              <span className="text-muted">{w.sample}</span>
              <span className="tabular">Cq {w.cq == null ? "none" : fixed(w.cq, 2)}</span>
              <span className={w.detected ? "text-fg" : "text-muted"}>
                {w.detected ? "detected" : "not detected"}
              </span>
              <span className="tabular text-muted">
                {w.quantity != null ? `alone: ${fmtQuantity(w.quantity)}` : ""}
              </span>
              {key === odd && <Badge tone="warn">Farthest from the others (over 2-fold)</Badge>}
              {sid && (
                <Button
                  size="sm"
                  variant="link"
                  className="h-auto p-0"
                  onClick={() => setCurve(key)}
                >
                  Curve
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {sid && curve ? (
        <Suspense fallback={null}>
          <WellCurveDialog sid={sid} well={curve} onClose={() => setCurve(null)} />
        </Suspense>
      ) : null}
    </div>
  );
}

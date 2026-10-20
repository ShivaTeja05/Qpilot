/** The sample picked in "Your samples": its value, its group, its well (plate, position, Cq, flags). */
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, IconButton, KeyValues } from "@/ui";
import type { AuditSamplePoint, AuditSamples } from "./api";

export function SampleDetail({
  point,
  samples,
  curve,
  onClose,
}: {
  point: AuditSamplePoint;
  samples: AuditSamples;
  /** The well's amplification curve, when a viewer can show it. */
  curve?: ReactNode;
  onClose: () => void;
}) {
  const group = samples.groups[point.group];
  const flags = [
    point.carries ? <Badge key="carries" tone="warn">Leaving it out changes the call</Badge> : null,
    point.nondetect ? <Badge key="nd" tone="warn">No Cq: never amplified</Badge> : null,
    point.late ? <Badge key="late" tone="warn">Late Cq (above {samples.late_cut})</Badge> : null,
    point.flagged ? <Badge key="flag" tone="warn">Flagged by LinRegPCR</Badge> : null,
  ].filter(Boolean);
  return (
    <section aria-label={`Sample ${point.sample}`} className="mt-4 rounded-lg border border-line-strong bg-surface-2 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">Sample {point.sample}</h3>
          <p className="text-xs text-muted">{group?.label ?? point.group}</p>
        </div>
        <IconButton size="sm" variant="ghost" label="Close the sample" onClick={onClose}>
          <X />
        </IconButton>
      </div>
      {flags.length ? <div className="mt-2 flex flex-wrap gap-1.5">{flags}</div> : null}
      <KeyValues
        className="mt-3"
        rows={[
          ["Value, relative to the rest's mean", point.value],
          ["Plate (RDML run)", <span className="font-mono">{point.plate}</span>],
          ["Well", <span className="font-mono">{point.well}</span>],
          ["Cq", point.cq ?? "none (never amplified)"],
        ]}
      />
      {curve ? <div className="mt-3">{curve}</div> : null}
    </section>
  );
}

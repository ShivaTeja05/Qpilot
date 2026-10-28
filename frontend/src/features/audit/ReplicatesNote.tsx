/**
 * How the audit treated a design's technical replicates, in plain words: shown when the audited
 * (or to-be-audited) design has several wells per biological unit and gene. The words and counts
 * come from the audit's scope (qpilot/integration/simulator.py); nothing here is typed in.
 */
import { Layers } from "lucide-react";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import type { AuditScope } from "./types";

export type AuditReplicates = NonNullable<AuditScope["technical_replicates"]>;

/** The counts behind the words: how many values come from several wells, and how many wells. */
export function replicateCounts(r: AuditReplicates): string {
  return `${count(r.values_with_several_wells)} of ${plural(r.values, "unit value")} come from several wells (up to ${count(r.most_wells_per_value)} per value, ${plural(r.wells, "well")} in all).`;
}

export function ReplicatesNote({
  replicates,
  className,
}: {
  replicates: AuditReplicates | null | undefined;
  className?: string;
}) {
  if (!replicates) return null;
  return (
    <aside
      aria-label="Technical replicates"
      className={cn(
        "flex items-start gap-3 rounded-xl border border-line bg-surface p-4 text-sm",
        className,
      )}
    >
      <Layers className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0">
        <p className="font-semibold text-fg">How your replicate wells were handled</p>
        <p className="mt-1 text-[13px] leading-relaxed text-fg">{replicates.words}</p>
        <p className="mt-1 text-xs text-muted">{replicateCounts(replicates)}</p>
      </div>
    </aside>
  );
}

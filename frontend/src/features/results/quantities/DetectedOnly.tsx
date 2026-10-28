/**
 * A gene detected in one group only (or in neither): said in words with that group's ΔCq, never
 * as a fold change (a ratio to nothing). The numbers are the engine's facts (WithheldGene).
 */
import { fixed } from "@/lib/format";
import type { ResultsView } from "../api";

type Withheld = ResultsView["withheld"][number];

export function DetectedOnlyLine({ gene }: { gene: Withheld }) {
  const only = gene.detected_only;
  if (!only) return null;
  if (only.group == null) {
    return (
      <span>
        not detected in any of the {only.n_absent} biological units of {only.absent}: no fold change
        to give.
      </span>
    );
  }
  const sd = only.dcq_sd != null ? ` ± ${fixed(only.dcq_sd, 2)} (SD)` : "";
  return (
    <span>
      detected only in <strong className="font-medium text-fg">{only.group}</strong> (
      {only.n_detected} of {only.n_group} biological units), not in any of the {only.n_absent} units
      of {only.absent}
      {only.dcq != null ? `; ΔCq in ${only.group} ${fixed(only.dcq, 2)}${sd}` : ""}. No fold change
      is given: the other group has no measured amount.
    </span>
  );
}

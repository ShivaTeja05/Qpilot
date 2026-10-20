/** API view → plate map props. Group labels are never read: the plate map is blind. */
import type { Schemas } from "@/api/client";
import type { PlateWell } from "./layers";

export interface PlateWellOptions {
  /** Wells whose names read like instructions (from the session's quarantine flags). */
  flagged?: (well: Schemas["PlateWell"]) => boolean;
  /** Fade wells that do not pass (a gene filter). */
  keep?: (well: Schemas["PlateWell"]) => boolean;
}

/**
 * The wells of a `PlateView`. Curve numbers (call, Cq, efficiency, R², the Curve Judge) are
 * carried only when the view shows them (`curves_shown`); before that the map has sample types
 * only. The role is the design's when one is assembled, else what the file declares.
 */
export function plateWells(
  view: Pick<Schemas["PlateView"], "wells" | "curves_shown">,
  options: PlateWellOptions = {},
): PlateWell[] {
  return view.wells.map((w) => {
    const notes: string[] = [];
    if (w.excluded_by_person) notes.push("Excluded from the analysis by a person.");
    if (w.excluded_note) notes.push(`Note from the file or LinRegPCR: ${w.excluded_note}`);
    if (w.role && w.role !== w.declared_type)
      notes.push(`The file declares it “${w.declared_type}”.`);
    if (w.proposal_id) notes.push("A proposal about this well’s call is waiting for you.");
    const base: PlateWell = {
      well: w.well,
      sample: w.sample,
      target: w.target,
      role: w.role ?? w.declared_type,
      flagged: options.flagged?.(w) || undefined,
      dimmed: options.keep ? !options.keep(w) : undefined,
      notes,
    };
    if (!view.curves_shown) return base;
    return {
      ...base,
      amplified: w.amplified ?? null,
      cq: w.cq ?? null,
      efficiency: w.efficiency ?? null,
      r2: w.r2 ?? null,
      disagree: w.disagrees,
      personCall: w.person_call != null,
    };
  });
}

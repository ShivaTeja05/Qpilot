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
  const curves = curvesByWell(view.wells);
  return view.wells.map((w) => {
    const notes: string[] = [];
    const others = (curves.get(w.key) ?? []).filter((o) => o !== w);
    if (others.length)
      notes.push(`Also in this well (multiplex): ${others.map(curveName).join(", ")}.`);
    if (w.excluded_by_person) notes.push("Excluded from the analysis by a person.");
    if (w.excluded_note) notes.push(`Note from the file or LinRegPCR: ${w.excluded_note}`);
    if (w.role && w.role !== w.declared_type)
      notes.push(`The file declares it “${w.declared_type}”.`);
    if (w.proposal_id) notes.push("A proposal about this well’s call is waiting for you.");
    const base: PlateWell = {
      well: w.well,
      sample: w.sample,
      target: w.target,
      dye: w.dye ?? null,
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

/** A curve of a well in words: its target, and its dye when the file names one. */
export function curveName(w: Pick<Schemas["PlateWell"], "target" | "dye">): string {
  return w.dye ? `${w.target} (${w.dye})` : w.target;
}

/** Well key (`run_id/well`) -> its curves in the view's order (one per dye on a multiplex plate). */
export function curvesByWell(
  wells: readonly Schemas["PlateWell"][],
): Map<string, Schemas["PlateWell"][]> {
  const out = new Map<string, Schemas["PlateWell"][]>();
  for (const w of wells) {
    const list = out.get(w.key);
    if (list) list.push(w);
    else out.set(w.key, [w]);
  }
  return out;
}

/**
 * One entry per well of a multiplex plate (several curves per well): the curve of `target` where
 * the well has one, else the well's first curve, faded; with no `target`, every well's first
 * curve. So the map, its legend and its table count wells, not curves; each entry's hover card
 * names the well's other curves. A plate with one curve per well is {@link plateWells} as is.
 */
export function plateWellsOneDye(
  view: Pick<Schemas["PlateView"], "wells" | "curves_shown" | "multiplex">,
  target: string | null,
  options: Omit<PlateWellOptions, "keep"> = {},
): PlateWell[] {
  if (!view.multiplex)
    return plateWells(view, target ? { ...options, keep: (w) => w.target === target } : options);
  const curves = curvesByWell(view.wells);
  const shown = new Set<Schemas["PlateWell"]>();
  const faded = new Set<Schemas["PlateWell"]>();
  for (const list of curves.values()) {
    const mine = target ? list.find((w) => w.target === target) : list[0];
    if (mine) shown.add(mine);
    else faded.add(list[0]!);
  }
  const all = plateWells(view, { ...options, keep: (w) => shown.has(w) });
  return all.filter((_, i) => shown.has(view.wells[i]!) || faded.has(view.wells[i]!));
}

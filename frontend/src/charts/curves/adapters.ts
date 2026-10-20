/** API view → curve viewer series. */
import type { Schemas } from "@/api/client";
import type { CurveSeries } from "./data";

/** `A1 · 1495`: the well and its sample. */
export function seriesLabel(well: string, sample: string): string {
  return `${well} · ${sample}`;
}

/**
 * A well's curve (focus, with its Cq and baseline when the view shows them) and the other wells
 * of the same sample and target on its plate (context, faint).
 */
export function curveSeries(
  view: Schemas["CurveView"],
  options: { replicates?: boolean } = {},
): CurveSeries[] {
  const shown = view.numbers_shown;
  const focus: CurveSeries = {
    id: view.key,
    label: seriesLabel(view.well, view.sample),
    cycles: view.cycle,
    values: view.fluorescence,
    cq: shown ? (view.cq ?? null) : null,
    baseline: shown ? (view.baseline ?? null) : null,
    role: "focus",
  };
  if (options.replicates === false) return [focus];
  return [
    focus,
    ...view.replicates.map<CurveSeries>((r) => ({
      id: r.key,
      label: seriesLabel(r.well, r.sample),
      cycles: r.cycle,
      values: r.fluorescence,
      role: "context",
    })),
  ];
}

/**
 * Several wells' curves together: each chosen well in focus; the replicates of a single chosen
 * well as context (with many chosen wells, their replicates are left out unless chosen too).
 */
export function curvesOf(views: readonly Schemas["CurveView"][]): CurveSeries[] {
  if (views.length === 1) return curveSeries(views[0]!);
  return views.map((v) => curveSeries(v, { replicates: false })[0]!);
}

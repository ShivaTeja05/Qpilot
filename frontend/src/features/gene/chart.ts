/**
 * The audit's views as the charts take them. The API sends `null` where the engine could not
 * compute a number (an analysis with no fold, a group with no usable sample); a chart cannot
 * place those, so they are left out here and counted by the views' own totals.
 */
import type {
  AuditAnalyses as ChartAnalyses,
  AuditEffects as ChartEffects,
  AuditSamples as ChartSamples,
} from "@/charts";
import type { AuditAnalyses, AuditEffects, AuditSamples } from "./api";

export function chartAnalyses(a: AuditAnalyses): ChartAnalyses {
  return { ...a, rows: a.rows.flatMap((r) => (r.log2 == null ? [] : [{ ...r, log2: r.log2 }])) };
}

export function chartEffects(e: AuditEffects): ChartEffects {
  return {
    ...e,
    planned_log2: e.planned_log2 ?? Number.NaN,
    decisions: e.decisions.map((d) => ({
      ...d,
      options: d.options.flatMap((o) => (o.log2 == null ? [] : [{ ...o, log2: o.log2 }])),
    })),
  };
}

export function chartSamples(s: AuditSamples): ChartSamples {
  const groups: ChartSamples["groups"] = {};
  for (const [key, g] of Object.entries(s.groups))
    if (g.mean != null) groups[key] = { ...g, mean: g.mean };
  return {
    ...s,
    fold_log2: s.fold_log2 ?? Number.NaN,
    groups,
    points: s.points.flatMap((p) =>
      p.x == null || !(p.group in groups) ? [] : [{ ...p, x: p.x }],
    ),
  };
}

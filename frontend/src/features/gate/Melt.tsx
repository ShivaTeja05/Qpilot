/**
 * A G-MELT check's wells, as melt curves: opened from its row in the rule checks, it reads the
 * plate's melt calls (`/api/studies/{id}/melt`) and shows the −dF/dT of the sample's wells (or
 * of the wells the check points at), their peaks and the assay's expected melting temperature,
 * with each well's call. In a Studio session the wells open in Curves as well. Every number
 * is the engine's.
 */
import { lazy, Suspense, useMemo } from "react";
import { Link } from "wouter";
import {
  MAX_MELT_WELLS,
  useMelt,
  type MeltSource,
  type MeltView,
} from "@/features/curves/melt/api";
import { ErrorPanel, LoadingBlock } from "@/ui";
import type { Evaluation } from "./api";

// The chart (uPlot) loads with the first G-MELT check opened, not with the Controls section.
const MeltCurves = lazy(() =>
  import("@/features/curves/melt/MeltPanel").then((m) => ({ default: m.MeltCurves })),
);

/** The wells of a G-MELT check: its sample's wells of its target, else the wells it flags. */
export function meltWellsOf(view: MeltView | undefined, e: Evaluation): string[] {
  if (!view || !e.plate) return [];
  const flagged = e.flagged
    .filter((k) => k.startsWith(`${e.plate}/`))
    .map((k) => k.slice(e.plate!.length + 1));
  if (e.sample) {
    const mine = view.calls
      .filter((c) => c.target === e.target && c.sample === e.sample)
      .map((c) => c.well);
    return [...new Set([...flagged, ...mine])].slice(0, MAX_MELT_WELLS);
  }
  return [...new Set(flagged)].slice(0, MAX_MELT_WELLS);
}

export function GateMelt({
  studyId,
  evaluation: e,
  curvesHref,
}: {
  studyId: string;
  evaluation: Evaluation;
  /** Where these wells open in Curves (a Studio session only). */
  curvesHref?: (plate: string, wells: string[]) => string;
}) {
  const source = useMemo<MeltSource>(() => ({ kind: "study", studyId }), [studyId]);
  const plate = e.plate ?? null;
  const all = useMelt(source, plate, [], Boolean(plate) && e.verdict !== "not_applicable");
  const wells = useMemo(() => meltWellsOf(all.data, e), [all.data, e]);
  const q = useMelt(source, plate, wells, wells.length > 0);
  if (!plate || e.verdict === "not_applicable") return null;
  if (all.error || q.error) {
    return (
      <ErrorPanel error={all.error ?? q.error} compact title="The melt curves could not be read" />
    );
  }
  if (!all.data || (wells.length > 0 && !q.data)) {
    return <LoadingBlock label="Reading the melt curves" lines={3} />;
  }
  if (!all.data.has_melt || !wells.length || !q.data) return null;
  const many = wells.length > 1;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[12px] font-medium text-muted">
          {many ? "Their melt curves" : "Its melt curve"} (−dF/dT)
        </h3>
        {curvesHref ? (
          <Link
            href={curvesHref(plate, wells)}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            Open {many ? "these wells" : "this well"} in Curves
          </Link>
        ) : null}
      </div>
      <Suspense fallback={<LoadingBlock label="Drawing the melt curves" lines={3} />}>
        <MeltCurves
          view={q.data}
          height={220}
          label={`${many ? "Wells" : "Well"} ${wells.join(", ")} of plate ${plate}`}
        />
      </Suspense>
    </div>
  );
}

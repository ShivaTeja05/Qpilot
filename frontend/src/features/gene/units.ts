/**
 * Each biological unit's value of one gene, from the engine (`GET /api/studies/{id}/genes/{gene}/
 * units`, qpilot/web/contract_units.py): what "Your samples" draws when the robustness audit is not
 * there to, so the panel is never empty once Results exist. Positions are log2, relative to the
 * second group's mean; the numbers are the engine's, worded by the server.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { shownQuery, type GeneScope } from "./api";

function fetchGeneUnits(studyId: string, gene: string, comparison?: string | null) {
  return unwrap(
    api.GET("/api/studies/{study_id}/genes/{gene}/units", {
      params: { path: { study_id: studyId, gene }, query: shownQuery(comparison) },
    }),
  );
}

export type GeneUnits = Awaited<ReturnType<typeof fetchGeneUnits>>;
export type UnitPoint = GeneUnits["points"][number];
export type UnitWell = UnitPoint["wells"][number];
export type UnitGroup = GeneUnits["groups"]["high"];

export function useGeneUnits(s: GeneScope, gene: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["w", s.key, s.studyId, "units", gene, s.comparison ?? null] as const,
    enabled: Boolean(s.studyId && gene) && enabled,
    queryFn: () => fetchGeneUnits(s.studyId!, gene!, s.comparison),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

/**
 * Which values "Your samples" shows. The audit's own chart (it can recompute under any what-if and
 * rings the samples that carry the call) when the audit covers the gene; the engine's per-unit
 * values otherwise, and also when the audited design has technical replicates, because only they
 * show each unit's wells (the audit's marks are added to them).
 */
export function samplesSource(covered: boolean, replicateAudit: boolean): "audit" | "engine" {
  return covered && !replicateAudit ? "audit" : "engine";
}

/** Units the audit says carry the call (removing one alone changes it), by name. */
export function carriedUnits(points: readonly { sample: string; carries: boolean }[] | undefined) {
  return new Set((points ?? []).filter((p) => p.carries).map((p) => p.sample));
}

/** A unit's label: its name, and its samples when it pools several. */
export function unitLabel(p: Pick<UnitPoint, "unit" | "samples">): string {
  const others = p.samples.filter((s) => s !== p.unit);
  return others.length ? `${p.unit} (${p.samples.join(", ")})` : p.unit;
}

/** The well a unit opens first: its first used well, else its first well. */
export function firstWell(p: Pick<UnitPoint, "wells">): UnitWell | undefined {
  return p.wells.find((w) => w.state === "used") ?? p.wells[0];
}

/** How a well counts, in words. */
export function wellState(w: Pick<UnitWell, "state">): string {
  if (w.state === "excluded") return "left out by a person";
  if (w.state === "no_value") return "no usable curve (not used)";
  return "used";
}

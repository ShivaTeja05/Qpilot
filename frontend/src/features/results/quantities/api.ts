/**
 * The Quantities view's data (qpilot/web/routers/absolute.py): every assay with standards, one
 * assay's curves and units, recording the reaction input (a person, with a reason), and the
 * ng → copies helper. Every number is the engine's; query keys start with `["w", key]` so a
 * live event refreshes them.
 */
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";
import { useWrite } from "@/shell/writes";

const getQuantities = (study_id: string) =>
  unwrap(api.GET("/api/studies/{study_id}/quantities", { params: { path: { study_id } } }));
const getAssay = (study_id: string, target: string) =>
  unwrap(
    api.GET("/api/studies/{study_id}/quantities/{target}", {
      params: { path: { study_id, target } },
    }),
  );
const getCopies = (q: CopiesQuery) =>
  unwrap(
    api.GET("/api/tools/copies", {
      params: {
        query: {
          ng: q.ng,
          length: q.length,
          kind: q.kind,
          ...(q.step && q.levels ? { step: q.step, levels: q.levels } : {}),
        },
      },
    }),
  );

export type QuantitiesView = Awaited<ReturnType<typeof getQuantities>>;
export type AssaySummary = QuantitiesView["assays"][number];
export type CurveSummary = AssaySummary["curves"][number];
export type AssayView = Awaited<ReturnType<typeof getAssay>>;
export type CurveDetail = AssayView["curves"][number];
export type UnitQuantity = AssayView["units"][number];
export type Limit = CurveSummary["lod"];
export type Suspect = CurveSummary["suspects"][number];
export type CopiesAnswer = Awaited<ReturnType<typeof getCopies>>;
export type MoleculeKind = "dsDNA" | "ssDNA" | "RNA";
export interface CopiesQuery {
  ng: number;
  length: number;
  kind: MoleculeKind;
  step?: number;
  levels?: number;
}

/** Keep asking while the server reads the study's file for the first time (503 `warming`). */
const retry = {
  retry: (n: number, e: Error) =>
    e instanceof ApiError && e.code === "warming"
      ? n < 90
      : !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
  retryDelay: (n: number, e: Error) =>
    e instanceof ApiError && e.code === "warming" ? 2000 : Math.min(1000 * 2 ** n, 8000),
};

export function useQuantities(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "quantities", studyId],
    enabled: Boolean(studyId),
    ...retry,
    queryFn: () => getQuantities(studyId!),
  });
}

export function useAssay(key: string, studyId: string | null | undefined, target: string | null) {
  return useQuery({
    queryKey: ["w", key, "quantities", studyId, target],
    enabled: Boolean(studyId && target),
    ...retry,
    queryFn: () => getAssay(studyId!, target!),
  });
}

/** ng → copies (no study needed): asked only once the numbers are complete. */
export function useCopies(q: CopiesQuery | null) {
  return useQuery({
    queryKey: ["tools", "copies", q],
    enabled: q != null,
    queryFn: () => getCopies(q!),
    staleTime: Infinity,
    retry: false,
  });
}

export interface ReactionWrite {
  template_ul: number | null;
  input_ng: number | null;
  unit: string | null;
  reason: string;
  /** The quantities view's `inbox_head`: a 409 `stale` when something was decided since. */
  expected_head: string;
}

/** A person records what one reaction held; the study is analysed again with it. */
export function useRecordReaction(key: string, studyId: string) {
  return useWrite<ReactionWrite, { status: string; message: string }>({
    workspaceKey: key,
    mutationFn: (w) =>
      unwrap(
        api.POST("/api/studies/{study_id}/quantities/reaction", {
          params: { path: { study_id: studyId } },
          body: {
            template_ul: w.template_ul,
            input_ng: w.input_ng,
            unit: w.unit,
            reason: w.reason,
            expected_head: w.expected_head,
          },
        }),
      ),
    success: (r) =>
      r.status === "unchanged"
        ? "Already recorded: nothing changed"
        : { title: "Reaction input recorded", description: r.message },
  });
}

/**
 * The rule proposes leaving out each standard that looks wrong (science review J2): one
 * `curve.exclude_well` per well, waiting in Curves for a person to accept or reject.
 */
export function useProposeStandards(key: string, studyId: string) {
  return useWrite<void, { status: string; message: string }>({
    workspaceKey: key,
    mutationFn: () =>
      unwrap(
        api.POST("/api/studies/{study_id}/quantities/standards", {
          params: { path: { study_id: studyId } },
        }),
      ),
    success: (r) =>
      r.status === "nothing"
        ? r.message
        : { title: "Proposed: you decide in Curves", description: r.message },
  });
}

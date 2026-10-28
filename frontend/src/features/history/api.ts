/**
 * The History section's data (qpilot/web/routers/history.py): the chain replayed step by step,
 * the diff of two steps, and the comparison with another analysis of the same file. Read only;
 * every query key starts with `["w", key]`, so a decision made anywhere (Results, an agent)
 * refreshes the timeline through the live event stream.
 */
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, unwrap, type Schemas } from "@/api/client";

export type HistoryView = Schemas["HistoryView"];
export type HistoryStep = Schemas["HistoryStep"];
export type HistoryAnalysis = Schemas["HistoryAnalysis"];
export type HistoryGene = Schemas["HistoryGene"];
export type StudioMilestone = Schemas["StudioMilestone"];
export type RelatedStudy = Schemas["RelatedStudy"];
export type ChoiceInForce = Schemas["ChoiceInForce"];
export type HistoryDiff = Schemas["HistoryDiff"];
export type HistoryCompare = Schemas["HistoryCompare"];
export type GeneChange = Schemas["GeneChange"];
export type ChoiceChange = Schemas["ChoiceChange"];

/**
 * While the server reads a study's file for the first time it answers 503 `warming`; keep asking
 * instead of showing an error. Other refusals (blind, not found) are final.
 */
const warmingRetry = {
  retry: (count: number, e: Error) =>
    e instanceof ApiError && e.code === "warming"
      ? count < 90
      : !(e instanceof ApiError && e.status >= 400 && e.status < 500) && count < 2,
  retryDelay: (count: number, e: Error) =>
    e instanceof ApiError && e.code === "warming" ? 2000 : Math.min(1000 * 2 ** count, 8000),
};

/** True while a query waits for the server to finish reading the study. */
export function isWarming(q: { failureReason: Error | null }): boolean {
  return q.failureReason instanceof ApiError && q.failureReason.code === "warming";
}

/** The comparison replayed, as the routes' `?comparison=` (none: the study's first). */
const shown = (comparison: string | null | undefined) => (comparison ? { comparison } : {});

/** The chain replayed (a study with several comparisons: the calls of `comparison`). */
export function useHistory(
  key: string,
  studyId: string | null | undefined,
  comparison: string | null = null,
) {
  return useQuery({
    queryKey: ["w", key, "history", studyId, comparison],
    enabled: Boolean(studyId),
    ...warmingRetry,
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/history", {
          params: { path: { study_id: studyId! }, query: shown(comparison) },
        }),
      ),
  });
}

export function useHistoryDiff(
  key: string,
  studyId: string | null | undefined,
  from: number | null,
  to: number | null,
  comparison: string | null = null,
) {
  return useQuery({
    queryKey: ["w", key, "history-diff", studyId, from, to, comparison],
    enabled: Boolean(studyId) && from != null && to != null,
    ...warmingRetry,
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/history/diff", {
          params: {
            path: { study_id: studyId! },
            query: { from: from!, to: to!, ...shown(comparison) },
          },
        }),
      ),
  });
}

export function useHistoryCompare(
  key: string,
  studyId: string | null | undefined,
  other: string | null | undefined,
) {
  return useQuery({
    queryKey: ["w", key, "history-compare", studyId, other],
    enabled: Boolean(studyId) && Boolean(other),
    ...warmingRetry,
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/history/compare", {
          params: { path: { study_id: studyId! }, query: { other: other! } },
        }),
      ),
  });
}

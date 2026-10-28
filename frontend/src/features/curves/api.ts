/**
 * The Curves section's reads and writes. Every query about the session starts with
 * `["w", sid, …]` so live events (an agent's proposal, another tab's decision, a finished job)
 * re-read exactly what is on screen.
 */
import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type PlateView = Schemas["PlateView"];
export type CurveView = Schemas["CurveView"];
export type CurveCallsView = Schemas["CurveCallsView"];

/** One plate's wells (the design's first plate when `run` is not given). */
export function usePlate(sid: string, run: string | null) {
  return useQuery({
    queryKey: ["w", sid, "plate", run ?? ""],
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/plate", {
          params: { path: { sid }, query: run ? { run } : {} },
        }),
      ),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

function curveQuery(sid: string, key: string) {
  return {
    queryKey: ["w", sid, "curve", key],
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/curve", { params: { path: { sid }, query: { well: key } } }),
      ),
    staleTime: 60_000,
  };
}

/** Several wells' curves (`run_id/well` keys), fetched side by side. */
export function useCurves(sid: string, keys: readonly string[]) {
  return useQueries({
    queries: keys.map((k) => curveQuery(sid, k)),
    combine: (results) => ({
      data: results.map((r) => r.data).filter((d): d is CurveView => d != null),
      pending: results.some((r) => r.isPending),
      error: results.find((r) => r.error)?.error ?? null,
      refetch: () => results.forEach((r) => void r.refetch()),
    }),
  });
}

/** One target's wells under every amplification rule (and the Curve Judge where it ran). */
export function useCurveCalls(sid: string, gene: string | null) {
  return useQuery({
    queryKey: ["w", sid, "curve-calls", gene ?? ""],
    enabled: Boolean(gene),
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/curve-calls", {
          params: { path: { sid }, query: { gene: gene! } },
        }),
      ),
    staleTime: 60_000,
  });
}

export type CqTableView = Schemas["CqTableView"];
export type CqSetView = Schemas["CqSetView"];

/**
 * A file of Cq values only: its Cq table for the curves stage (`cq_only: false` for a file with
 * curves). Blind: no group, fold change or p-value; the Cq values once the design is confirmed.
 */
export function useCqTable(sid: string) {
  return useQuery({
    queryKey: ["w", sid, "cq-table"],
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/cq-table", { params: { path: { sid } } })),
    staleTime: 30_000,
  });
}

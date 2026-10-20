/**
 * The Curves section's reads and writes. Every query about the session starts with
 * `["w", sid, …]` so live events (an agent's proposal, another tab's decision, a finished job)
 * re-read exactly what is on screen.
 */
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type PlateView = Schemas["PlateView"];
export type CurveView = Schemas["CurveView"];
export type CurveCallsView = Schemas["CurveCallsView"];
export type ProposalList = Schemas["ProposalList"];
export type Proposal = Schemas["Proposal"];

/** One plate's wells (the design's first plate when `run` is not given). */
export function usePlate(sid: string, run: string | null) {
  return useQuery({
    queryKey: ["w", sid, "plate", run ?? ""],
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/plate", { params: { path: { sid }, query: run ? { run } : {} } })),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

function curveQuery(sid: string, key: string) {
  return {
    queryKey: ["w", sid, "curve", key],
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/curve", { params: { path: { sid }, query: { well: key } } })),
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
      unwrap(api.GET("/api/sessions/{sid}/curve-calls", { params: { path: { sid }, query: { gene: gene! } } })),
    staleTime: 60_000,
  });
}

/** The curves stage's inbox: waiting proposals first (contradicted, then cannot-check, then the rest). */
export function useCurveProposals(sid: string) {
  return useQuery({
    queryKey: ["w", sid, "proposals", "curves"],
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/proposals", { params: { path: { sid }, query: { stage: "curves" } } })),
  });
}

/** Check the curves: a job (about 15 s on the demo). Returns the job to follow. */
export function useProposeCurves(sid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/sessions/{sid}/propose/curves", { params: { path: { sid } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["w", sid] }),
  });
}

/**
 * The planner's data (api: qpilot/web/routers/planner.py, generated types):
 *
 *   GET  /api/studies/{id}/planner          what the study measured (noise per gene, groups, plates)
 *   POST /api/studies/{id}/planner          the plan for a change, a power and a size
 *   POST /api/studies/{id}/planner/layout   every plate of the next experiment
 *   GET  /api/studies/{id}/planner/layout.csv  the same plates as CSV (a link, `csv_url`)
 *
 * The POSTs only read (the server writes nothing), so they are queries keyed by their body:
 * moving a slider asks again, an answer already seen comes from the cache. Every key starts with
 * `["w", workspace key, study id, …]` so a live event about the study re-reads them.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type PlannerBody = Schemas["PlannerBody"];
export type PlanLayoutBody = Schemas["PlanLayoutBody"];

function fetchPlanner(studyId: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/planner", { params: { path: { study_id: studyId } } }),
  );
}

function fetchPlan(studyId: string, body: PlannerBody) {
  return unwrap(
    api.POST("/api/studies/{study_id}/planner", { params: { path: { study_id: studyId } }, body }),
  );
}

function fetchLayout(studyId: string, body: PlanLayoutBody) {
  return unwrap(
    api.POST("/api/studies/{study_id}/planner/layout", {
      params: { path: { study_id: studyId } },
      body,
    }),
  );
}

// The types are the client's own answers: openapi-fetch reads a tuple (σ's interval, the
// efficiency range) as an array, so they are taken from the calls, not from Schemas directly.
export type PlannerView = Awaited<ReturnType<typeof fetchPlanner>>;
export type PlannerGene = PlannerView["genes"][number];
export type PlanView = Awaited<ReturnType<typeof fetchPlan>>;
export type PlanGene = PlanView["genes"][number];
export type PlanPowerCurve = PlanView["curves"][number];
export type PlanLayoutView = Awaited<ReturnType<typeof fetchLayout>>;
export type PlanLayoutPlate = PlanLayoutView["plates"][number];
export type PlanLayoutWell = PlanLayoutPlate["wells"][number];

/** Which study the planner reads, and the workspace it lives in. */
export interface PlannerScope {
  key: string;
  studyId: string | null;
}

export function scopeOf(workspace: Schemas["WorkspaceView"]): PlannerScope {
  return {
    key: workspace.key,
    studyId: workspace.study_id ?? (workspace.kind === "study" ? workspace.key : null),
  };
}

const wkey = (s: PlannerScope, ...rest: unknown[]) =>
  ["w", s.key, s.studyId, "planner", ...rest] as const;

/** `GET /api/studies/{id}/planner`: the study's own noise (a few seconds the first time). */
export function usePlanner(s: PlannerScope) {
  return useQuery({
    queryKey: wkey(s, "measured"),
    enabled: Boolean(s.studyId),
    staleTime: 60_000,
    queryFn: () => fetchPlanner(s.studyId!),
  });
}

/** `POST /api/studies/{id}/planner`: the plan for `body` (null: not yet). */
export function usePlan(s: PlannerScope, body: PlannerBody | null) {
  return useQuery({
    queryKey: wkey(s, "plan", body),
    enabled: Boolean(s.studyId && body),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    queryFn: () => fetchPlan(s.studyId!, body!),
  });
}

/** `POST /api/studies/{id}/planner/layout`: the plates for `body` (null: not yet). */
export function useLayout(s: PlannerScope, body: PlanLayoutBody | null) {
  return useQuery({
    queryKey: wkey(s, "layout", body),
    enabled: Boolean(s.studyId && body),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    queryFn: () => fetchLayout(s.studyId!, body!),
  });
}

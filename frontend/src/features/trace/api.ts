/**
 * Trace's data (api: `qpilot/web/routers/trace.py`, contract `qpilot/web/contract_trace.py`):
 * one gene's call followed down to its samples, wells and plates; the study's overview; the
 * call recomputed with samples set aside; one plate's wells; and (Studio sessions) one well's
 * curve. Every number comes from the engine through these routes; nothing is computed here.
 *
 * Query keys start with `["w", workspace key, study id, "trace", …]`, so a live event about the
 * session or the study (a decision, the end of the `trace.load` job) re-reads them.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, ApiError, unwrap, type JobView, type Schemas } from "@/api/client";

export interface TraceScope {
  /** The workspace key (a session id or a study id). */
  key: string;
  /** The study traced (null until a session's results exist). */
  studyId: string | null;
  kind: Schemas["WorkspaceView"]["kind"];
}

export function scopeOf(workspace: Schemas["WorkspaceView"]): TraceScope {
  return {
    key: workspace.key,
    studyId: workspace.study_id ?? (workspace.kind === "study" ? workspace.key : null),
    kind: workspace.kind,
  };
}

const wkey = (s: TraceScope, ...rest: unknown[]) =>
  ["w", s.key, s.studyId, "trace", ...rest] as const;
const studyPath = (studyId: string) => ({ params: { path: { study_id: studyId } } });

function fetchStudy(studyId: string) {
  return unwrap(api.GET("/api/studies/{study_id}/trace", studyPath(studyId)));
}
function fetchGene(studyId: string, gene: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/trace/{gene}", {
      params: { path: { study_id: studyId, gene } },
    }),
  );
}
function fetchWithout(studyId: string, gene: string, samples: string[]) {
  return unwrap(
    api.POST("/api/studies/{study_id}/trace/{gene}/without", {
      params: { path: { study_id: studyId, gene } },
      body: { samples },
    }),
  );
}
function fetchPlate(studyId: string, run: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/trace/plate", {
      params: { path: { study_id: studyId }, query: { run } },
    }),
  );
}
function fetchCurve(sid: string, well: string, target: string | null) {
  return unwrap(
    api.GET("/api/sessions/{sid}/curve", {
      params: { path: { sid }, query: { well, target: target ?? undefined } },
    }),
  );
}

// The client's own answers (openapi-fetch reads a tuple such as `ci` as an array).
export type StudyView = Awaited<ReturnType<typeof fetchStudy>>;
export type GeneView = Awaited<ReturnType<typeof fetchGene>>;
export type WithoutView = Awaited<ReturnType<typeof fetchWithout>>;
export type PlateView = Awaited<ReturnType<typeof fetchPlate>>;
export type CurveView = Awaited<ReturnType<typeof fetchCurve>>;
export type Trace = GeneView["trace"];
export type Overview = StudyView["trace"];
export type Sample = Trace["samples"][number];
export type Well = Sample["wells"][number];
export type Place = Trace["places"][number];
export type Option = Place["options"][number];
export type Reference = Trace["references"][number];
export type CallView = Trace["call"];
export type CallChange = Option["changes"][number];
export type GeneRow = Overview["genes"][number];
export type Suspect = Overview["suspects"][number];
export type Missing = Overview["left_out"][number];
export type Texts = GeneView["texts"];
export type FactText = Texts[string];

/** The `trace.load` job a 409 `loading` names (the study's model is being read). */
export function loadingJob(error: unknown): JobView | null {
  if (!(error instanceof ApiError) || error.code !== "loading") return null;
  const job = error.details.job as JobView | undefined;
  return job && typeof job.id === "string" ? job : null;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** While the model loads, ask again now and then (the job's end also re-reads it). */
const whileLoading = (q: { state: { error: unknown } }) =>
  loadingJob(q.state.error) ? 1500 : false;

/** Retry nothing but a load in progress: a 404 or a refusal is an answer. */
const retry = (count: number, error: unknown) => Boolean(loadingJob(error)) && count < 40;

export function useTraceStudy(s: TraceScope) {
  return useQuery({
    queryKey: wkey(s, "study"),
    enabled: Boolean(s.studyId),
    queryFn: () => fetchStudy(s.studyId!),
    refetchInterval: whileLoading,
    retry,
  });
}

export function useTraceGene(s: TraceScope, gene: string | null) {
  return useQuery({
    queryKey: wkey(s, "gene", gene),
    enabled: Boolean(s.studyId && gene),
    queryFn: () => fetchGene(s.studyId!, gene!),
    placeholderData: keepPreviousData,
    refetchInterval: whileLoading,
    retry,
  });
}

/** The call with these samples set aside (the engine recomputes it; nothing is applied). */
export function useWithout(s: TraceScope, gene: string | null, samples: readonly string[]) {
  const sorted = [...samples].sort();
  return useQuery({
    queryKey: wkey(s, "without", gene, sorted),
    enabled: Boolean(s.studyId && gene && sorted.length),
    queryFn: () => fetchWithout(s.studyId!, gene!, sorted),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry,
  });
}

export function useTracePlate(s: TraceScope, run: string | null) {
  return useQuery({
    queryKey: wkey(s, "plate", run),
    enabled: Boolean(s.studyId && run),
    queryFn: () => fetchPlate(s.studyId!, run!),
    staleTime: 5 * 60_000,
    retry,
  });
}

/** One well's raw curve: Studio sessions only (the curve comes from the session's file). */
export function useWellCurve(s: TraceScope, key: string | null, target: string | null) {
  const sid = s.kind === "session" ? s.key : null;
  return useQuery({
    queryKey: ["w", s.key, "curve", key, target],
    enabled: Boolean(sid && key),
    queryFn: () => fetchCurve(sid!, key!, target),
    staleTime: Infinity,
  });
}

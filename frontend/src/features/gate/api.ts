/**
 * The Controls section's data (api: `qpilot/web/routers/gate.py`, contract
 * `qpilot/web/contract_gate.py`): every plate's controls checked against the rule pack, and
 * what leaving the wells a rule points at would change. Every number comes from the engine
 * through this one route; nothing is computed here.
 *
 * The query key starts with `["w", workspace key, study id, "gate"]`, so a live event about the
 * session or the study (a decision, the end of the `gate.run` job) re-reads it.
 */
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, unwrap, type JobView, type Schemas } from "@/api/client";

export interface GateScope {
  /** The workspace key (a session id or a study id). */
  key: string;
  /** The study checked (null until a session's results exist). */
  studyId: string | null;
  kind: Schemas["WorkspaceView"]["kind"];
}

export function scopeOf(workspace: Schemas["WorkspaceView"]): GateScope {
  return {
    key: workspace.key,
    studyId: workspace.study_id ?? (workspace.kind === "study" ? workspace.key : null),
    kind: workspace.kind,
  };
}

function fetchGate(studyId: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/gate", { params: { path: { study_id: studyId } } }),
  );
}

// The client's own answers (openapi-fetch reads a tuple such as `ci` as an array).
export type GateView = Awaited<ReturnType<typeof fetchGate>>;
export type Evaluation = GateView["evaluations"][number];
export type Consequence = GateView["consequences"][number];
export type Option = Consequence["options"][number];
export type Plate = GateView["plates"][number];
export type GateCard = GateView["cards"][number];
export type RuleInfo = GateView["pack"]["rules"][number];
export type FactText = GateView["headline"];
export type Verdict = Evaluation["verdict"];
export type ConsequenceClass = Consequence["consequence"];

/** The `gate.run` job a 409 `loading` names (the controls are being checked). */
export function loadingJob(error: unknown): JobView | null {
  if (!(error instanceof ApiError) || error.code !== "loading") return null;
  const job = error.details.job as JobView | undefined;
  return job && typeof job.id === "string" ? job : null;
}

/** While the gate runs, ask again now and then (the job's end also re-reads it). */
const whileLoading = (q: { state: { error: unknown } }) =>
  loadingJob(q.state.error) ? 1500 : false;

/** Retry nothing but a run in progress: a refusal is an answer. */
const retry = (count: number, error: unknown) => Boolean(loadingJob(error)) && count < 60;

export function useGate(s: GateScope) {
  return useQuery({
    queryKey: ["w", s.key, s.studyId, "gate"],
    enabled: Boolean(s.studyId),
    queryFn: () => fetchGate(s.studyId!),
    refetchInterval: whileLoading,
    retry,
  });
}

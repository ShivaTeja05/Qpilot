/**
 * The Controls section's data (api: `qpilot/web/routers/gate.py`, contract
 * `qpilot/web/contract_gate.py`): every plate's controls checked against the rule pack, and
 * what leaving the wells a rule points at would change. Every number comes from the engine
 * through this one route; nothing is computed here.
 *
 * The query key starts with `["w", workspace key, study id, "gate"]`, so a live event about the
 * session or the study (a decision, the end of the `gate.run` job) re-reads it.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, postForm, unwrap, type JobView, type Schemas } from "@/api/client";

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
export type GateDecision = NonNullable<Consequence["decision"]>;
export type GateRequest = Consequence["requests"][number];
export type GateDecided = Schemas["GateDecided"];
export type RunFile = GateView["runs"][number];
export type RunLinked = Schemas["GateRunLinked"];

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

export interface GateChoice {
  /** The consequence's `decision_id` (`card_gate_<id>`). */
  card: string;
  option: string;
  reason: string;
}

/**
 * A person's choice on a gate card (a Studio session only; the server sets the actor). Leaving
 * wells out, or putting them back, starts the analysis of the changed design (`job`); every
 * query of the workspace is read again when it settles.
 */
export function useGateDecide(s: GateScope, view: GateView | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (c: GateChoice) =>
      unwrap(
        api.POST("/api/studies/{study_id}/gate/cards/{card_id}/decide", {
          params: { path: { study_id: s.studyId!, card_id: c.card } },
          body: {
            option: c.option,
            reason: c.reason,
            expected_head: view?.head ?? null,
            expected_inbox: view?.inbox_head ?? null,
          },
        }),
      ),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", s.key] }),
  });
}

/**
 * A person links the run file the instrument wrote to one plate (G-INSTR reads it in the
 * plate's place, for every analysis of the study's file). Linking changes no number; the gate
 * is read again (a `gate.run` job) when it settles.
 */
export function useLinkRunFile(s: GateScope) {
  const qc = useQueryClient();
  return useMutation<RunLinked, unknown, { plate: string; file: File }>({
    mutationFn: ({ plate, file }) => {
      const form = new FormData();
      form.append("plate", plate);
      form.append("run", file, file.name);
      return postForm<RunLinked>(
        `/api/studies/${encodeURIComponent(s.studyId ?? "")}/gate/run-files`,
        form,
      );
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", s.key] }),
  });
}

/** A person removes a plate's linked run file (G-INSTR reads the study's own file again). */
export function useUnlinkRunFile(s: GateScope) {
  const qc = useQueryClient();
  return useMutation<RunLinked, unknown, string>({
    mutationFn: (plate) =>
      unwrap(
        api.POST("/api/studies/{study_id}/gate/run-files/unlink", {
          params: { path: { study_id: s.studyId! } },
          body: { plate },
        }),
      ),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", s.key] }),
  });
}

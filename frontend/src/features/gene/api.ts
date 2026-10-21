/**
 * The Gene section's data: the qPilot views of one gene (api: `/results`, `/genes/{gene}`,
 * `/cards`) and the robustness audit's views of it (api-audit: `/audit`, `/audit/gene|analyses|
 * effects|lab/{gene}`, `POST /audit/samples`).
 *
 * Every query key starts with `["w", workspace key, study id, …]`, so a live event about either
 * the session or the study re-reads what this section shows (src/api/live.ts).
 *
 * The types are the typed client's own answers (generated from the API's contract).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, unwrap, type JobView, type Schemas } from "@/api/client";

// ---- the frame ----------------------------------------------------------------------------------

/** Which study this section reads, and the workspace it lives in. */
export interface GeneScope {
  /** The workspace key (a session id or a study id). */
  key: string;
  /** The study whose results are shown (null until a session's results exist). */
  studyId: string | null;
  kind: Schemas["WorkspaceView"]["kind"];
}

export function scopeOf(workspace: Schemas["WorkspaceView"]): GeneScope {
  return {
    key: workspace.key,
    studyId: workspace.study_id ?? (workspace.kind === "study" ? workspace.key : null),
    kind: workspace.kind,
  };
}

const wkey = (s: GeneScope, ...rest: unknown[]) => ["w", s.key, s.studyId, ...rest] as const;

// ---- errors -------------------------------------------------------------------------------------

/** True when the API has no such route or thing yet (404): the section shows what it can. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

// ---- qPilot's views (api: qpilot/web/contract.py, "results"; generated types) ----------------

export type CallKey = "up" | "down" | "none";

/** `GET /api/studies/{id}/results`. */
function fetchResults(studyId: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/results", { params: { path: { study_id: studyId } } }),
  );
}

/** `GET /api/studies/{id}/genes/{gene}` (404 `not_found` for a gene the study does not compare). */
function fetchGene(studyId: string, gene: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/genes/{gene}", {
      params: { path: { study_id: studyId, gene } },
    }),
  );
}

// The types are the client's own answers (generated from the contract): openapi-fetch reads a
// tuple such as `ci` as an array, so they are taken from the calls, not from Schemas directly.
export type ResultsView = Awaited<ReturnType<typeof fetchResults>>;
export type GeneView = Awaited<ReturnType<typeof fetchGene>>;
export type GeneRow = GeneView["row"];
export type GenormView = ResultsView["references"];
export type FlipRow = GeneView["effects"][number];
export type CardView = GeneView["cards"][number];

/** A Decision Card that touches this gene, as the Gene section lists it. */
export interface GeneCardRef {
  id: string;
  title: string;
  status: string;
  /** The server's words for where the card stands. */
  statusLine?: string | null;
  /** Whether this card's choice alone can flip this gene's call. */
  flips: boolean;
  maxDeltaLog2: number | null;
  /** The option applied now (or planned), in words. */
  chosenLabel?: string | null;
}

export function useResults(s: GeneScope) {
  return useQuery({
    queryKey: wkey(s, "results"),
    enabled: Boolean(s.studyId),
    queryFn: () => fetchResults(s.studyId!),
  });
}

/** The query for one gene (shared by the view and the neighbours' prefetch). */
export function geneQuery(s: GeneScope, gene: string | null) {
  return {
    queryKey: wkey(s, "gene", gene),
    queryFn: () => fetchGene(s.studyId!, gene!),
  };
}

/** One gene (404 `not_found` for a gene the study does not compare, e.g. a reference gene). */
export function useGene(s: GeneScope, gene: string | null) {
  return useQuery({
    ...geneQuery(s, gene),
    enabled: Boolean(s.studyId && gene),
    placeholderData: keepPreviousData,
  });
}

// ---- the robustness audit's views (api-audit: contract_audit.py; generated types) --------------

const auditPath = (studyId: string) => ({ params: { path: { study_id: studyId } } });
const auditGenePath = (studyId: string, gene: string) => ({
  params: { path: { study_id: studyId, gene } },
});

function fetchAuditStatus(studyId: string) {
  return unwrap(api.GET("/api/studies/{study_id}/audit", auditPath(studyId)));
}
function fetchAuditGene(studyId: string, gene: string) {
  return unwrap(api.GET("/api/studies/{study_id}/audit/gene/{gene}", auditGenePath(studyId, gene)));
}
function fetchAuditAnalyses(studyId: string, gene: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/audit/analyses/{gene}", auditGenePath(studyId, gene)),
  );
}
function fetchAuditEffects(studyId: string, gene: string) {
  return unwrap(
    api.GET("/api/studies/{study_id}/audit/effects/{gene}", auditGenePath(studyId, gene)),
  );
}
function fetchAuditLab(studyId: string, gene: string) {
  return unwrap(api.GET("/api/studies/{study_id}/audit/lab/{gene}", auditGenePath(studyId, gene)));
}
function fetchAuditSamples(studyId: string, gene: string, changes: Record<string, string>) {
  return unwrap(
    api.POST("/api/studies/{study_id}/audit/samples", {
      ...auditPath(studyId),
      body: { gene, changes },
    }),
  );
}

export type AuditStatus = Awaited<ReturnType<typeof fetchAuditStatus>>;
export type AuditGeneCard = Awaited<ReturnType<typeof fetchAuditGene>>;
export type AuditAnalyses = Awaited<ReturnType<typeof fetchAuditAnalyses>>;
export type AuditEffects = Awaited<ReturnType<typeof fetchAuditEffects>>;
export type AuditLab = Awaited<ReturnType<typeof fetchAuditLab>>;
export type AuditSamples = Awaited<ReturnType<typeof fetchAuditSamples>>;
export type AuditSamplePoint = AuditSamples["points"][number];

/** True when the audit's views are still loading: the error carries the load job to follow. */
export function loadingJob(error: unknown): JobView | null {
  if (!(error instanceof ApiError) || error.code !== "loading") return null;
  const job = error.details.job as JobView | undefined;
  return job && typeof job.id === "string" ? job : null;
}

export function useAuditStatus(s: GeneScope) {
  return useQuery({
    queryKey: wkey(s, "audit", "status"),
    enabled: Boolean(s.studyId),
    queryFn: () => fetchAuditStatus(s.studyId!),
    // Events re-read it when a job ends; poll slowly only while something is under way.
    refetchInterval: (q) => {
      const d = q.state.data as AuditStatus | undefined;
      return d?.status === "running" || (d?.status === "ready" && !d.views_ready) ? 5000 : false;
    },
  });
}

const AUDIT_VIEW = {
  gene: fetchAuditGene,
  analyses: fetchAuditAnalyses,
  effects: fetchAuditEffects,
  lab: fetchAuditLab,
} as const;
type AuditGeneView = keyof typeof AUDIT_VIEW;

export function useAuditView<V extends AuditGeneView>(
  s: GeneScope,
  view: V,
  gene: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: wkey(s, "audit", view, gene),
    enabled: Boolean(s.studyId && gene) && enabled,
    queryFn: () =>
      AUDIT_VIEW[view](s.studyId!, gene!) as Promise<Awaited<ReturnType<(typeof AUDIT_VIEW)[V]>>>,
    staleTime: 5 * 60_000,
  });
}

/** Each sample's value of this gene under a set of choices (the planned analysis by default). */
export function useAuditSamples(
  s: GeneScope,
  gene: string | null,
  changes: Record<string, string>,
  enabled: boolean,
) {
  return useQuery({
    queryKey: wkey(s, "audit", "samples", gene, changes),
    enabled: Boolean(s.studyId && gene) && enabled,
    queryFn: () => fetchAuditSamples(s.studyId!, gene!, changes),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

/** Start the robustness audit (a job of about 50 s on the demo). */
export function useRunAudit(s: GeneScope) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (again: boolean = false) =>
      unwrap(
        api.POST("/api/studies/{study_id}/audit", { ...auditPath(s.studyId!), body: { again } }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: wkey(s, "audit", "status") }),
  });
}

// ---- one well's curve (Studio sessions only) ------------------------------------------------------

export type WellCurve = Schemas["CurveView"];

/** One well's raw curve and LinRegPCR's numbers (`plate/well`, as the audit's samples name it). */
export function useWellCurve(s: GeneScope, well: string | null, target: string | null) {
  const sid = s.kind === "session" ? s.key : null;
  return useQuery({
    queryKey: ["w", s.key, "curve", well, target],
    enabled: Boolean(sid && well),
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/curve", {
          params: { path: { sid: sid! }, query: { well: well!, target: target ?? undefined } },
        }),
      ),
    staleTime: Infinity,
  });
}

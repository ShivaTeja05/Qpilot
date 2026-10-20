/**
 * The Gene section's data: the qPilot views of one gene (api: `/results`, `/genes/{gene}`,
 * `/cards`) and the robustness audit's views of it (api-audit: `/audit`, `/audit/gene|analyses|
 * effects|lab/{gene}`, `POST /audit/samples`).
 *
 * Every query key starts with `["w", workspace key, study id, …]`, so a live event about either
 * the session or the study re-reads what this section shows (src/api/live.ts).
 *
 * The types below are structural: only the fields this section reads. They mirror the shapes the
 * API owners posted on the bus (#0076, #0085, #0086); the generated schema types fit them.
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

// ---- requests -----------------------------------------------------------------------------------

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

/** JSON from the API, or an {@link ApiError} in the server's own words. */
export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      ...init,
      headers: { accept: "application/json", ...(init?.body ? { "content-type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const e = (body as ErrorShape | undefined)?.error;
    throw new ApiError(
      response.status,
      e?.code ?? `http_${response.status}`,
      e?.message ?? "The server could not answer this request.",
      e?.details ?? {},
    );
  }
  return body as T;
}

const enc = encodeURIComponent;
const studyUrl = (s: GeneScope, path: string) => `/api/studies/${enc(s.studyId ?? "")}${path}`;

/** True when the API has no such route or thing yet (404): the section shows what it can. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

// ---- qPilot's views (api: qpilot/web/contract.py, "results"; generated types) ----------------

export type CallKey = "up" | "down" | "none";

/** `GET /api/studies/{id}/results`. */
function fetchResults(studyId: string) {
  return unwrap(api.GET("/api/studies/{study_id}/results", { params: { path: { study_id: studyId } } }));
}

/** `GET /api/studies/{id}/genes/{gene}` (404 `not_found` for a gene the study does not compare). */
function fetchGene(studyId: string, gene: string) {
  return unwrap(api.GET("/api/studies/{study_id}/genes/{gene}", { params: { path: { study_id: studyId, gene } } }));
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

// ---- the robustness audit's views (qsim Screen dicts, as the API returns them) ------------------

export type AuditStatusName = "none" | "running" | "ready" | "refused" | "not_applicable" | "unavailable" | "failed";

export interface AuditStatus {
  status: AuditStatusName | string;
  /** Why not, in plain words (refused, not applicable, unavailable, failed). */
  reason?: string | null;
  /** The running (or failed) audit job. */
  job?: JobView | null;
  manifest?: { analyses?: number | null; chain_head?: string | null } | null;
  /** Ready: no decision was made on the study since it was audited. */
  current?: boolean | null;
  decisions_since?: number;
  /** Ready: the live views are loaded (the first load takes ~15 s; the views wait for it). */
  views_ready?: boolean;
  /** The job loading the live views. */
  loading?: JobView | null;
  typical_s?: number;
}

interface AuditScale {
  line_log2: number;
  line: string;
}

/** The audit's gene card: the verdict and the words around it. */
export interface AuditGeneCard {
  gene: string;
  verdict: string;
  label: string;
  call_key?: string | null;
  headline_gene?: boolean;
  tiles?: { label: string; value: string; sub: string }[];
  result: { headline: string; lines: string[]; verdict_sentence: string };
  holds: { n: number; lines: string[] };
  changes: { choice: string; fold: string; call: string; call_key?: string | null; same_call: boolean }[];
  no_changes?: string | null;
  shortcut?: string | null;
  leans: string[];
  singles: { sample: string; plate: string; well: string; call: string; call_key?: string | null }[];
  todo: string[];
}

export interface AuditAnalyses extends AuditScale {
  gene: string;
  n: number;
  n_same: number;
  n_other: number;
  base_call: string;
  rows: { log2: number; fold: string; call: string; call_key?: string | null; same: boolean; choices: string[]; planned: boolean }[];
}

export interface AuditEffects extends AuditScale {
  gene: string;
  planned_log2: number;
  planned: string;
  decisions: {
    id: string;
    name: string;
    n_change: number;
    options: {
      label: string;
      tier: string;
      log2: number;
      fold: string;
      call: string;
      call_key?: string | null;
      changes_call: boolean;
      planned: boolean;
    }[];
  }[];
}

export interface AuditSamplePoint {
  x: number;
  group: string;
  sample: string;
  plate: string;
  well: string;
  cq: string | null;
  late: boolean;
  nondetect: boolean;
  flagged: boolean;
  carries: boolean;
  value: string;
}

export interface AuditSamples extends AuditScale {
  gene: string;
  fold: string;
  fold_log2: number;
  late_cut: string;
  changes: string[];
  groups: Record<string, { label: string; n: number; missing: number; mean: number }>;
  points: AuditSamplePoint[];
}

export interface AuditLab {
  gene: string;
  rows: { label: string; value: string }[];
  references: { gene: string; m: string | number; differs: boolean }[];
  refs_label: string;
  stable_below: string;
}

export function useAuditStatus(s: GeneScope) {
  return useQuery({
    queryKey: wkey(s, "audit", "status"),
    enabled: Boolean(s.studyId),
    queryFn: () => requestJson<AuditStatus>(studyUrl(s, "/audit")),
    // Events re-read it when the job ends; poll slowly only while something is under way.
    refetchInterval: (q) => {
      const d = q.state.data as AuditStatus | undefined;
      return d?.status === "running" || (d?.status === "ready" && !d.views_ready && d.loading) ? 5000 : false;
    },
  });
}

type AuditGeneView = "gene" | "analyses" | "effects" | "lab";
type AuditViewOf<V extends AuditGeneView> = V extends "gene"
  ? AuditGeneCard
  : V extends "analyses"
    ? AuditAnalyses
    : V extends "effects"
      ? AuditEffects
      : AuditLab;

export function useAuditView<V extends AuditGeneView>(s: GeneScope, view: V, gene: string | null, enabled: boolean) {
  return useQuery({
    queryKey: wkey(s, "audit", view, gene),
    enabled: Boolean(s.studyId && gene) && enabled,
    queryFn: () => requestJson<AuditViewOf<V>>(studyUrl(s, `/audit/${view}/${enc(gene ?? "")}`)),
    staleTime: 5 * 60_000,
  });
}

/** Each sample's value of this gene under a set of choices (the planned analysis by default). */
export function useAuditSamples(s: GeneScope, gene: string | null, changes: Record<string, string>, enabled: boolean) {
  return useQuery({
    queryKey: wkey(s, "audit", "samples", gene, changes),
    enabled: Boolean(s.studyId && gene) && enabled,
    queryFn: () =>
      requestJson<AuditSamples>(studyUrl(s, "/audit/samples"), {
        method: "POST",
        body: JSON.stringify({ gene, changes }),
      }),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

/** Start the robustness audit (a job of about 50 s on the demo). */
export function useRunAudit(s: GeneScope) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (again: boolean = false) =>
      requestJson<{ job: JobView }>(studyUrl(s, "/audit"), { method: "POST", body: JSON.stringify({ again }) }),
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

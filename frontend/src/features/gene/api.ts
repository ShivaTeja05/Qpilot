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
import { ApiError, type JobView, type Schemas } from "@/api/client";

// ---- the frame ----------------------------------------------------------------------------------

/** Which study this section reads, and the workspace it lives in. */
export interface GeneScope {
  /** The workspace key (a session id or a study id). */
  key: string;
  /** The study whose results are shown (null until a session's results exist). */
  studyId: string | null;
  kind: Schemas["WorkspaceView"]["kind"];
  hasAudit: boolean;
}

export function scopeOf(workspace: Schemas["WorkspaceView"]): GeneScope {
  return {
    key: workspace.key,
    studyId: workspace.study_id ?? (workspace.kind === "study" ? workspace.key : null),
    kind: workspace.kind,
    hasAudit: workspace.has_audit,
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

// ---- qPilot's views -----------------------------------------------------------------------------

export type CallKey = "up" | "down" | "none";

/** One confidence check of a gene (ordinal level reasons). */
export interface ConfidenceCheck {
  id: string;
  passed: boolean;
  note: string;
}

/** One gene as the Results table lists it (api's GeneRow). */
export interface GeneRow {
  gene: string;
  headline?: boolean;
  conclusion: CallKey | string;
  fc: number;
  ci: [number, number] | number[];
  p: number | null;
  n_hi?: number | null;
  n_lo?: number | null;
  holds: number;
  n_cells?: number | null;
  level?: string | null;
  reasons?: string[];
  checks?: ConfidenceCheck[];
  /** Decision dimensions whose single change flips this gene's call. */
  flips_by?: string[];
  efficiency?: number | null;
  verdict?: string | null;
  verdict_label?: string | null;
}

export interface Genorm {
  M_initial: Record<string, number>;
  order?: string[];
  V?: Record<string, number> | null;
  recommended?: string[];
  cutoff_M: number;
  cutoff_V?: number;
}

/** The study's results (api's ResultsView): the gene list, the groups, the rule, the references. */
export interface ResultsView {
  study_id: string;
  summary?: {
    n_plates?: number;
    n_reactions?: number;
    n_samples?: number;
    groups?: { label: string; n: number }[];
    design_line?: string;
    mode?: string;
  };
  rule?: { alpha: number; min_log2fc: number; text?: string };
  references?: { used?: string[]; candidates?: string[]; genorm?: Genorm | null } | null;
  genes: GeneRow[];
  headline?: string[];
  audit?: { status: string; verdict_counts?: Record<string, number> } | null;
  chain_head?: string | null;
}

/** How one decision moves this gene (robustness impact, from qPilot's own grid). */
export interface GeneImpact {
  flips: boolean;
  max_delta_log2fc: number;
}

/** A Decision Card that touches this gene. */
export interface GeneCardRef {
  id: string;
  kind: string;
  title?: string | null;
  status: string;
  decision?: string | null;
  decision_label?: string | null;
  recommended?: string | null;
  recommended_label?: string | null;
  rank?: number | null;
  decided_by?: string | null;
  /** Whether this card's choice alone can flip this gene's call. */
  flips?: boolean | null;
  max_delta_log2fc?: number | null;
}

/** The wells behind this gene. */
export interface GeneAssay {
  efficiency?: number | null;
  n_wells?: number | null;
  n_amplified?: number | null;
  n_undetermined?: number | null;
  cq_median?: number | null;
  cq_min?: number | null;
  cq_max?: number | null;
}

/** One gene (api's GeneView: the GeneRow plus what only this page needs). */
export interface GeneView extends GeneRow {
  role?: "toi" | "ref" | string | null;
  groups?: { label: string; n: number }[];
  order?: string[];
  impact?: Record<string, GeneImpact> | null;
  cards?: GeneCardRef[];
  assay?: GeneAssay | null;
  references?: ResultsView["references"];
  rule?: ResultsView["rule"];
}

/** A Decision Card as `/cards` serves it (only what this section reads). */
export interface CardLike {
  id: string;
  kind: string;
  title?: string | null;
  status: string;
  decision?: string | null;
  decided_by?: string | null;
  recommended?: string | null;
  rank?: number | null;
  options?: { id: string; label: string }[];
  impact?: { flips?: boolean; n_genes_flipped?: number } | null;
}

export function useResults(s: GeneScope) {
  return useQuery({
    queryKey: wkey(s, "results"),
    enabled: Boolean(s.studyId),
    queryFn: () => requestJson<ResultsView>(studyUrl(s, "/results")),
  });
}

export function useGene(s: GeneScope, gene: string | null) {
  return useQuery({
    queryKey: wkey(s, "gene", gene),
    enabled: Boolean(s.studyId && gene),
    queryFn: () => requestJson<GeneView>(studyUrl(s, `/genes/${enc(gene ?? "")}`)),
    placeholderData: keepPreviousData,
  });
}

export function useCards(s: GeneScope, enabled = true) {
  return useQuery({
    queryKey: wkey(s, "cards"),
    enabled: Boolean(s.studyId) && enabled,
    queryFn: () => requestJson<{ head?: string; cards: CardLike[] }>(studyUrl(s, "/cards")),
  });
}

// ---- the robustness audit's views (qsim Screen dicts, as the API returns them) ------------------

export type AuditStatusName = "none" | "running" | "ready" | "refused" | "not_applicable" | "unavailable";

export interface AuditStatus {
  status: AuditStatusName | string;
  reason?: string | null;
  job?: JobView | null;
  manifest?: Record<string, unknown> | null;
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
    refetchInterval: (q) => ((q.state.data as AuditStatus | undefined)?.status === "running" ? 5000 : false),
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
    mutationFn: () => requestJson<{ job: JobView }>(studyUrl(s, "/audit"), { method: "POST", body: "{}" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: wkey(s, "audit", "status") }),
  });
}

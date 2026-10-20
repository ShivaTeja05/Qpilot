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

// ---- qPilot's views (api: qpilot/web/contract.py, "results") ----------------------------------

export type CallKey = "up" | "down" | "none";

/** A sentence whose numbers are the engine's facts. */
export interface FactText {
  plain: string;
  segments?: { text: string; fact?: string | null }[];
  facts?: { id: string; text: string }[];
  source?: "template" | "model";
}

/** One confidence check of a gene (the reasons behind its ordinal level). */
export interface ConfidenceCheck {
  id: string;
  passed: boolean;
  note: string;
}

/** A gene's result at the options a person chose on the Decision Cards. */
export interface AtChoices {
  fc: number;
  log2fc: number;
  p: number;
  conclusion: CallKey;
  differs: boolean;
}

/** One compared gene (api's GeneRow): contrast, robustness share, confidence, verdict. */
export interface GeneRow {
  gene: string;
  headline: boolean;
  conclusion: CallKey;
  fc: number;
  log2fc?: number;
  ci: [number, number] | number[];
  p: number;
  n_hi: number;
  n_lo: number;
  /** Share of reasonable analyses with the same call (0–1). */
  holds?: number | null;
  n_cells?: number;
  level?: string | null;
  reasons?: string[];
  min_flip_changes?: number | null;
  /** Decisions that alone can change this call. */
  flips_by?: string[];
  efficiency?: number | null;
  at_your_choices?: AtChoices | null;
  verdict?: string | null;
  verdict_label?: string | null;
}

/** Reference genes: which are used, and geNorm's stability (M) and pairwise V. */
export interface GenormView {
  used: string[];
  candidates?: string[];
  m: Record<string, number>;
  order?: string[];
  v?: Record<string, number>;
  recommended?: string[];
  cutoff_m: number;
  cutoff_v?: number;
  stable?: string[];
}

/** The study's results (api's ResultsView): the genes, the groups, the rule, the references. */
export interface ResultsView {
  study_id: string;
  summary: {
    n_plates?: number;
    n_samples?: number;
    groups: { label: string; n: number }[];
    design_line?: string;
  };
  rule: { alpha: number; min_log2fc: number; min_fold?: number; text: string };
  references: GenormView;
  genes: GeneRow[];
  headline?: string[];
  head?: string;
  audit?: { status: string; current?: boolean };
}

/** One option of one decision, the other choices as planned (aligned with the genes asked). */
export interface FlipOption {
  value: string;
  label: string;
  card_option?: string | null;
  planned: boolean;
  chosen?: boolean;
  conclusion: CallKey[];
  log2fc: number[];
  flips: boolean[];
}

/** One decision for this gene: can it flip the call alone, how far it moves it, each option. */
export interface FlipRow {
  dimension: string;
  title: string;
  card_id?: string | null;
  status?: string | null;
  flips: boolean[];
  max_delta_log2fc: number[];
  n_flipped?: number;
  options: FlipOption[];
}

/** Every analysis in qPilot's grid for one gene, compactly. */
export interface GeneGrid {
  dimensions: string[];
  options: Record<string, string[]>;
  /** The planned option's index per dimension. */
  planned: number[];
  /** Option index per dimension, one per analysis. */
  cells: number[][];
  log2fc: number[];
  p: number[];
  conclusion: CallKey[];
}

/** A Decision Card as the API words it (only what this section reads). */
export interface CardViewLike {
  card: { id: string; kind: string; status: string; decision?: string | null; recommended?: string | null; rank?: number | null };
  title: string;
  status_line: string;
  needs_human?: boolean;
  options: {
    id: string;
    label: string;
    recommended?: boolean;
    chosen?: boolean;
    /** E.g. a single control gene (MIQE): a shortcut, not a reasonable option. */
    not_recommended?: boolean;
    effects?: { gene: string; changes_call: boolean; log2fc: number }[];
  }[];
}

/** Everything about one gene (api's GeneView). */
export interface GeneView {
  study_id: string;
  gene: string;
  row: GeneRow;
  confidence?: { level: string; reasons: string[]; checks: ConfidenceCheck[]; min_flip_changes?: number | null } | null;
  confidence_text?: FactText | null;
  grid?: GeneGrid | null;
  /** One decision at a time (this gene only). */
  effects: FlipRow[];
  /** Decision Cards that can change this gene. */
  cards: CardViewLike[];
  is_reference?: boolean;
  reference_m?: number | null;
  prev_gene?: string | null;
  next_gene?: string | null;
  audit_verdict?: string | null;
  audit_verdict_label?: string | null;
}

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
    queryFn: () => requestJson<ResultsView>(studyUrl(s, "/results")),
  });
}

/** The query for one gene (shared by the view and the neighbours' prefetch). */
export function geneQuery(s: GeneScope, gene: string | null) {
  return {
    queryKey: wkey(s, "gene", gene),
    queryFn: () => requestJson<GeneView>(studyUrl(s, `/genes/${enc(gene ?? "")}`)),
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

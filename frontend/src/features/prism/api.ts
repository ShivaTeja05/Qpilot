/**
 * The Prism section's data: api-files' session routes (docs/app.md §2, the Prism row) and the
 * Studio inbox of the two Prism stages. Every query key starts with ["w", sid] so a live event
 * about the session refreshes it; slow work answers 202 {job} and is followed with `useJob`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type JobView, type Schemas } from "@/api/client";

export type Proposal = Schemas["Proposal"];
export type ProposalList = Schemas["ProposalList"];
export type Workspace = Schemas["WorkspaceView"];

// ---------------------------------------------------------------------------------------------
// Shapes (the service's JSON; `qpilot/studio_service.py` preview_prism / exports / round_trip)

/** One usual route from the instrument to Prism, recomputed by the engine on this study. */
export interface RouteRow {
  /** `ddcq` | `linear_welch` | `linear_student`. */
  id: string;
  label: string;
  /** How many conclusions this route draws differently from the engine. */
  n_differ: number;
  /** Which genes. */
  genes: string[];
  /** Each differing gene's conclusion under this route, when the server computed it. */
  conclusions?: Record<string, string> | null;
}

export interface PrismRoutes {
  study_id: string;
  n_genes: number;
  routes: RouteRow[];
  /** The engine's conclusion per gene (for "engine ▲ up · this route — no call"). */
  engine?: Record<string, string> | null;
}

export interface PreviewTable {
  columns: string[];
  n_rows: number;
  /** The CSV's first lines (header first), exactly as the file will hold them. */
  head: string[];
}

export interface ExportedChoice {
  card_id: string;
  dimension?: string | null;
  option: string;
  recommended?: string | null;
  value?: unknown;
  /** `human` | `system` | an agent name; null while the card is open (recommended option). */
  actor: string | null;
  status?: string | null;
}

export interface FigureGroup {
  name: string;
  n: number;
  mean: number | null;
  ci_lo: number | null;
  ci_hi: number | null;
  points: { unit: string; value: number }[];
}

/** One gene's figure: every biological unit per group with the group mean and its 95 % CI. */
export interface GeneFigure {
  gene: string;
  /** What the values are (log2 relative quantity). */
  scale?: string | null;
  groups: FigureGroup[];
}

export interface PrismPreview {
  writes_nothing?: boolean;
  bundle: {
    study_id: string;
    template_id: string;
    test: string;
    chain_head?: string | null;
    info: Record<string, string | undefined>;
    tables: { gene: string; columns: string[]; n_rows: number; csv: string }[];
  };
  template: { id: string; file: string; available: boolean; layout: string; test: string; graph: string };
  tables: Record<string, PreviewTable>;
  choices: ExportedChoice[];
  would_write: string[];
  not_affiliated: string;
  /** Per gene, when the server sends the figure's points (else the page reads the tables). */
  figures?: Record<string, GeneFigure> | null;
}

/** A bundle Send to Prism wrote from this session. */
export interface BundleEntry {
  /** Opaque id the round trip names it by (never a path). */
  id: string;
  study_id: string;
  at: string;
  bundle_sha256: string;
  /** True when it was sent for the analysis shown now (its decisions have not moved since). */
  current?: boolean | null;
  /** The folder its tables were last sent back from, when a round trip read one. */
  sent_back_dir?: string | null;
  /** Where Prism is told to send the tables back to (`<bundle>/sent_back`). */
  suggested_folder?: string | null;
  /** A download id for the zip (GET /api/downloads/{id}). */
  download?: string | null;
}

export interface SendResult {
  bundle_id?: string | null;
  bundle_sha256?: string | null;
  files?: string[];
  notes?: string[];
  /** GET /api/downloads/{id}. */
  download?: string | null;
  download_name?: string | null;
  launched?: boolean;
  /** Prism finished the script (its done file appeared). */
  done?: boolean | null;
  /** Why Prism was not started, in words. */
  note?: string | null;
  /** What to run on the computer that has Prism. */
  command_line?: string | null;
}

export interface DiffItem {
  kind: string;
  table?: string;
  gene: string;
  row?: string | null;
  column?: string | null;
  exported?: number | null;
  returned?: unknown;
  detail?: string | null;
}

export interface GeneChange {
  fc_before?: number | null;
  fc_after?: number | null;
  p_before?: number | null;
  p_after?: number | null;
  n_units_before?: number[] | null;
  n_units_after?: number[] | null;
  conclusion_before?: string | null;
  conclusion_after?: string | null;
  withheld_after?: string | null;
}

export interface CombinedConsequence {
  exclusions: { gene: string; biological_unit: string; well_rep?: number; well?: string }[];
  genes: Record<string, GeneChange>;
  n_conclusions_changed: number;
  n_genes: number;
  changed_genes: string[];
}

export interface RoundTripResult {
  items: DiffItem[];
  notes: string[];
  combined_consequence?: CombinedConsequence | null;
  /** The inbox outcome: ids proposed, and ids already decided / refused. */
  inbox?: Record<string, string[] | undefined> | null;
}

// ---------------------------------------------------------------------------------------------
// Requests

/**
 * A JSON request to a route that is not in the generated client yet (api-files' Prism routes),
 * with the same error handling as {@link unwrap}. Swapped for `api.GET`/`api.POST` once the
 * contract lands in `schema.d.ts`.
 */
async function request<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const call = fetch(path, {
    method: init?.method ?? "GET",
    credentials: "same-origin",
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  }).then(async (response) => {
    const body: unknown = await response.json().catch(() => undefined);
    return response.ok ? { data: body as T, response } : { error: body ?? {}, response };
  });
  return unwrap<T>(call);
}

const base = (sid: string) => `/api/sessions/${encodeURIComponent(sid)}/prism`;

export const prismKeys = {
  all: (sid: string) => ["w", sid, "prism"] as const,
  routes: (sid: string) => ["w", sid, "prism", "routes"] as const,
  preview: (sid: string) => ["w", sid, "prism", "preview"] as const,
  bundles: (sid: string) => ["w", sid, "prism", "bundles"] as const,
  inbox: (sid: string, stage: "prism" | "roundtrip") => ["w", sid, "proposals", stage] as const,
};

/** How often the usual Excel→Prism routes change a conclusion on this study. */
export function usePrismRoutes(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.routes(sid),
    enabled,
    queryFn: () => request<PrismRoutes>(`${base(sid)}/routes`),
    staleTime: 60_000,
  });
}

/** What Send to Prism would write (nothing is written). */
export function usePrismPreview(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.preview(sid),
    enabled,
    queryFn: () => request<PrismPreview>(`${base(sid)}/preview`),
  });
}

/** Every bundle Send to Prism wrote from this session, newest last. */
export function usePrismBundles(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.bundles(sid),
    enabled,
    queryFn: async () => {
      const data = await request<BundleEntry[] | { bundles: BundleEntry[] }>(`${base(sid)}/bundles`);
      return Array.isArray(data) ? data : data.bundles;
    },
  });
}

/** The Studio inbox of one Prism stage (the draft, or the round trip's questions). */
export function useStageInbox(sid: string, stage: "prism" | "roundtrip", enabled = true) {
  return useQuery({
    queryKey: prismKeys.inbox(sid, stage),
    enabled,
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/proposals", { params: { path: { sid }, query: { stage } } })),
  });
}

type Started = { job: JobView };

/** Start one of the section's slow actions; the caller follows the job it returns. */
function useStart<B>(sid: string, action: "draft" | "send" | "roundtrip") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: B) => request<Started>(`${base(sid)}/${action}`, { method: "POST", body }),
    onSuccess: ({ job }) => {
      qc.setQueryData(["job", job.id], job);
    },
  });
}

/** POST draft: the AI (or the rule) drafts the Prism project as a proposal. */
export const useStartDraft = (sid: string) => useStart<{ expected_head?: string | null }>(sid, "draft");

/** POST send: write the bundle, zip it, and start Prism when it is installed. */
export const useStartSend = (sid: string) => useStart<{ expected_head?: string | null; share?: boolean }>(sid, "send");

/** POST roundtrip: compare what came back from Prism with the bundle. */
export const useStartRoundTrip = (sid: string) =>
  useStart<{ bundle: string; folder: string; expected_head?: string | null }>(sid, "roundtrip");

/** The URL a download id is served from (a same-origin link; the server sends it as a file). */
export function downloadUrl(id: string): string {
  return `/api/downloads/${encodeURIComponent(id)}`;
}

/** The newest still-running job of this session whose kind ends with `suffix` (survives navigation). */
export function activeJob(workspace: Workspace, suffix: string): JobView | null {
  const jobs = (workspace.active_jobs ?? []).filter((j) => j.kind.endsWith(suffix));
  return jobs.length ? jobs[jobs.length - 1]! : null;
}

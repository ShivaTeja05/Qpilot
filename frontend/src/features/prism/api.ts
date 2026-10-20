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
// Shapes: api-files' contract (`qpilot/web/contract_files.py`), mirrored until it lands in
// `schema.d.ts`; then each becomes `Schemas["…"]`.

/** A file the server wrote into its private export folder, offered for download. */
export interface DownloadLink {
  id: string;
  /** `/api/downloads/<id>` (served as an attachment). */
  url: string;
  name: string;
  bytes: number;
}

/** `GET …/prism`: where Prism stands for this session. */
export interface PrismStatus {
  session_id: string;
  study_id: string;
  choices_confirmed: boolean;
  project: {
    status: "accepted" | "waiting" | "none";
    proposal_id?: string | null;
    template_id?: string | null;
    genes: string[];
    made_by?: string | null;
  };
  can_draft: boolean;
  can_send: boolean;
  /** What to do next, in words. */
  next: string;
  bundles: number;
}

/** One usual route from the instrument to Prism, recomputed by the engine on this study. */
export interface PrismRoute {
  /** `ddcq` | `linear_welch` | `linear_student`. */
  route: string;
  label: string;
  /** The method in the engine's words (`qpcr.routes.ROUTE_LABELS`). */
  method?: string | null;
  /** How many conclusions this route draws differently from the engine. */
  n_differ: number;
  n_genes: number;
  /** Which genes. */
  genes: string[];
  /** The fact id of `n_differ`. */
  fact: string;
  genes_fact?: string | null;
}

/** `GET …/prism/routes`: why the bridge matters, on this study's own plates. */
export interface PrismRoutes {
  study_id: string;
  n_genes: number | null;
  /** The engine's call rule in words. */
  rule?: string | null;
  /** The engine's call for every gene any route changes (a listed gene: that route's call differs). */
  engine?: Record<string, string> | null;
  routes: PrismRoute[];
  note: string;
}

/** The first rows of one table Prism will import (cells as text, as in the CSV). */
export interface PreviewTable {
  gene: string;
  columns: string[];
  n_rows: number;
  rows: string[][];
}

/** One analysis choice the bundle is exported at, and who decided it. */
export interface PrismChoice {
  card_id: string;
  /** The card's title ("Reference genes"), when the server sends it. */
  title?: string | null;
  dimension: string;
  option: string;
  /** The option's label ("Top 15 % by MYCN expression"), when the server sends it. */
  option_label?: string | null;
  recommended: string;
  value?: unknown;
  /** `human` | `system` | an agent; null while the card is open (exported at its recommended option). */
  actor?: string | null;
  status: string;
  /** Who decided, in words. */
  decided_by: string;
}

/** Every biological unit of one group (log2 relative quantity), and the mean with its 95 % CI. */
export interface FigureGroup {
  name: string;
  n: number;
  mean?: number | null;
  ci_lo?: number | null;
  ci_hi?: number | null;
  points: { unit: string; value: number }[];
}

/** An approximation of the template's graph for one gene (Prism draws the real one). */
export interface PrismFigureData {
  gene: string;
  scale: string;
  groups: FigureGroup[];
  note: string;
}

export interface PrismTemplate {
  id: string;
  file: string;
  /** False: not made in Prism yet (the bundle's README says how). */
  available: boolean;
  layout: string;
  test: string;
  graph: string;
}

/** `GET …/prism/preview`: what Send to Prism would write (nothing is written). */
export interface PrismPreview {
  study_id?: string;
  writes_nothing?: boolean;
  bundle: {
    study_id: string;
    template_id: string;
    test: string;
    chain_head: string;
    info: Record<string, string | undefined>;
    tables: { name?: string; gene?: string; csv: string; n_rows?: number }[];
  };
  would_write: string[];
  template: PrismTemplate;
  genes: string[];
  tables: PreviewTable[];
  choices: PrismChoice[];
  caption?: string | null;
  /** Every gene's figure (column layout only; empty otherwise). */
  figures?: Record<string, PrismFigureData> | null;
  choices_confirmed?: boolean;
  not_affiliated: string;
}

/** One bundle sent to Prism from this session. */
export interface PrismBundleView {
  /** Opaque id of a bundle this launch wrote (round trip, download); null for an older one. */
  id: string | null;
  study_id: string;
  bundle_sha256: string;
  at: string;
  folder: string;
  exists: boolean;
  /** Its analysis is the session's current one. */
  current: boolean;
  /** The folder a round trip read, or where send_back.pzc writes. */
  sent_back_folder?: string | null;
  /** A round trip can be started from this page. */
  round_trip: boolean;
  download?: DownloadLink | null;
}

/** The result of a Send to Prism job. */
export interface PrismSent {
  bundle: PrismBundleView;
  n_files: number;
  files?: string[];
  notes: string[];
  launched: boolean;
  /** Prism finished run.pzc (when launched). */
  done?: boolean | null;
  /** Why Prism was not started, in words. */
  launch_note?: string | null;
  /** What to run on the computer with Prism. */
  command_line: string;
  send_back_command: string;
  download: DownloadLink;
}

/** The result of a Draft the Prism project job. */
export interface PrismDrafted {
  status: string;
  proposal_id?: string | null;
  reason?: string | null;
  message: string;
}

export interface DiffItem {
  kind: string;
  table: string;
  gene: string;
  row?: string | null;
  column?: string | null;
  exported?: number | null;
  returned?: number | null;
  note: string;
}

/** The result of a round trip: what changed in Prism, as proposals with consequences. */
export interface PrismRoundTrip {
  bundle_id: string;
  study_id: string;
  items: DiffItem[];
  /** Ids of the proposals added to the Round trip inbox. */
  proposed: string[];
  refused: { reason?: string | null; subject?: string | null }[];
  notes: string[];
  /** What all the proposed exclusions do together. */
  combined?: Record<string, unknown> | null;
  message: string;
}

/** One gene's numbers before → after leaving values out (a round-trip consequence). */
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
  status: (sid: string) => ["w", sid, "prism", "status"] as const,
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

/** Where Prism stands: the project of the current analysis, and what can be done next. */
export function usePrismStatus(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.status(sid),
    enabled,
    queryFn: () => request<PrismStatus>(base(sid)),
  });
}

/**
 * What Send to Prism would write (nothing is written), with every gene's figure. The first call
 * after a server start is slow (the engine rebuilds the export inputs), then it is quick.
 */
export function usePrismPreview(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.preview(sid),
    enabled,
    queryFn: () => request<PrismPreview>(`${base(sid)}/preview?rows=${PREVIEW_ROWS}`),
  });
}

/** Rows of each table shown in the preview. */
export const PREVIEW_ROWS = 8;

/** Every bundle sent to Prism from this session, newest first. */
export function usePrismBundles(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.bundles(sid),
    enabled,
    queryFn: async () =>
      (await request<{ session_id: string; bundles: PrismBundleView[] }>(`${base(sid)}/bundles`))
        .bundles,
  });
}

/** The Studio inbox of one Prism stage (the draft, or the round trip's questions). */
export function useStageInbox(sid: string, stage: "prism" | "roundtrip", enabled = true) {
  return useQuery({
    queryKey: prismKeys.inbox(sid, stage),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/proposals", { params: { path: { sid }, query: { stage } } }),
      ),
  });
}

type Started = { job: JobView };

/** Start one of the section's slow actions; the caller follows the job it returns. */
function useStart<B>(sid: string, action: "draft" | "send" | "roundtrip") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: B) =>
      request<Started>(`${base(sid)}/${action}`, { method: "POST", body: body ?? undefined }),
    onSuccess: ({ job }) => {
      qc.setQueryData(["job", job.id], job);
    },
  });
}

/** POST draft: the AI (or the rule) drafts the Prism project as a proposal. */
export const useStartDraft = (sid: string) => useStart<void>(sid, "draft");

/** POST send: write the bundle, zip it, and start Prism when it is installed. */
export const useStartSend = (sid: string) => useStart<void>(sid, "send");

/** POST roundtrip: compare what came back from Prism with the bundle. */
export const useStartRoundTrip = (sid: string) =>
  useStart<{ bundle: string; folder: string }>(sid, "roundtrip");

/** The newest still-running job of this session of one kind (`prism.send` …): it survives navigation. */
export function activeJob(
  workspace: Workspace,
  kind: "prism.draft" | "prism.send" | "prism.roundtrip",
): JobView | null {
  const jobs = (workspace.active_jobs ?? []).filter((j) => j.kind === kind);
  return jobs.length ? jobs[jobs.length - 1]! : null;
}

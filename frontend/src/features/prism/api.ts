/**
 * The Prism section's data: api-files' session routes (docs/app.md §2, the Prism row) and the
 * Studio inbox of the two Prism stages. Every query key starts with ["w", sid] so a live event
 * about the session refreshes it; slow work answers 202 {job} and is followed with `useJob`.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, postForm, unwrap, type JobView, type Schemas } from "@/api/client";

export type Proposal = Schemas["Proposal"];
export type ProposalList = Schemas["ProposalList"];
export type Workspace = Schemas["WorkspaceView"];

// ---------------------------------------------------------------------------------------------
// Shapes: api-files' contract (`qpilot/web/contract_files.py`), generated into `schema.d.ts`

export type DownloadLink = Schemas["DownloadLink"];
/** `GET …/prism`: where Prism stands for this session. */
export type PrismStatus = Schemas["PrismStatus"];
/** One usual route from the instrument to Prism, recomputed by the engine on this study. */
export type PrismRoute = Schemas["PrismRoute"];
/** `GET …/prism/routes`: why the bridge matters, on this study's own plates. */
export type PrismRoutes = Schemas["PrismRoutes"];
/** The first rows of one table Prism will import (cells as text, as in the CSV). */
export type PreviewTable = Schemas["PreviewTable"];
/** One analysis choice the bundle is exported at, and who decided it. */
export type PrismChoice = Schemas["PrismChoice"];
/** Every biological unit of one group (log2 relative quantity), and the mean with its 95 % CI. */
export type FigureGroup = Schemas["GroupPoints"];
/** An approximation of the template's graph for one gene (Prism draws the real one). */
export type PrismFigureData = Schemas["PrismFigure"];
export type PrismTemplate = Schemas["PrismTemplate"];
/** One table of the Prism project (.pzfx). */
export type PrismTableView = Schemas["PrismTableView"];
/** `GET …/prism/preview`: what Send to Prism would write (nothing is written). */
export type PrismPreview = Schemas["PrismPreview"];
/** One bundle sent to Prism from this session. */
export type PrismBundleView = Schemas["PrismBundleView"];
/** The result of a Send to Prism job (`prism.send`). */
export type PrismSent = Schemas["PrismSent"];
/** The result of a Draft the Prism project job (`prism.draft`). */
export type PrismDrafted = Schemas["PrismDrafted"];
export type DiffItem = Schemas["PrismDiffItem"];
/** The result of a round trip (`prism.roundtrip`): what changed in Prism, as proposals. */
export type PrismRoundTrip = Schemas["PrismRoundTrip"];

// ---------------------------------------------------------------------------------------------
// Requests

const path = (sid: string) => ({ params: { path: { sid } } });

export const prismKeys = {
  all: (sid: string) => ["w", sid, "prism"] as const,
  status: (sid: string) => ["w", sid, "prism", "status"] as const,
  routes: (sid: string) => ["w", sid, "prism", "routes"] as const,
  preview: (sid: string) => ["w", sid, "prism", "preview"] as const,
  bundles: (sid: string) => ["w", sid, "prism", "bundles"] as const,
  inbox: (sid: string, stage: "prism" | "roundtrip") => ["w", sid, "proposals", stage] as const,
};

/**
 * How often the usual Excel→Prism routes change a conclusion on this study. The answer is the
 * study's stored facts (cached by the server per study), so the last one stays on screen while
 * it is read again; while the server is still reading the file it answers `warming`, and the
 * page asks again when it is warm.
 */
export function usePrismRoutes(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.routes(sid),
    enabled,
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/prism/routes", path(sid))),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

/** Where Prism stands: the project of the current analysis, and what can be done next. */
export function usePrismStatus(sid: string, enabled = true) {
  return useQuery({
    queryKey: prismKeys.status(sid),
    enabled,
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/prism", path(sid))),
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
    queryFn: () =>
      unwrap(
        api.GET("/api/sessions/{sid}/prism/preview", {
          params: { path: { sid }, query: { rows: PREVIEW_ROWS } },
        }),
      ),
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
      (await unwrap(api.GET("/api/sessions/{sid}/prism/bundles", path(sid)))).bundles,
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

/** Follow a started job from its first answer (the event stream keeps it current). */
function useStarted() {
  const qc = useQueryClient();
  return ({ job }: { job: JobView }) => qc.setQueryData(["job", job.id], job);
}

/** POST draft: the AI (or the rule) drafts the Prism project as a proposal. */
export function useStartDraft(sid: string) {
  const onSuccess = useStarted();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/sessions/{sid}/prism/draft", path(sid))),
    onSuccess,
  });
}

/** POST send: write the bundle, zip it, and start Prism when it is installed. */
export function useStartSend(sid: string) {
  const onSuccess = useStarted();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/sessions/{sid}/prism/send", path(sid))),
    onSuccess,
  });
}

/** POST roundtrip: compare what came back from Prism (the folder) with the bundle. */
export function useStartRoundTrip(sid: string) {
  const onSuccess = useStarted();
  return useMutation({
    mutationFn: (body: Schemas["RoundTripRequest"]) =>
      unwrap(api.POST("/api/sessions/{sid}/prism/roundtrip", { ...path(sid), body })),
    onSuccess,
  });
}

/** POST roundtrip/upload: the project a person saved in Prism, uploaded (Prism elsewhere). */
export function useStartRoundTripUpload(sid: string) {
  const onSuccess = useStarted();
  return useMutation({
    mutationFn: ({ bundle, file }: { bundle: string; file: File }) => {
      const form = new FormData();
      form.append("bundle", bundle);
      form.append("project", file, file.name);
      return postForm<{ job: JobView }>(
        `/api/sessions/${encodeURIComponent(sid)}/prism/roundtrip/upload`,
        form,
      );
    },
    onSuccess,
  });
}

/** The newest still-running job of this session of one kind (`prism.send` …): it survives navigation. */
export function activeJob(
  workspace: Workspace,
  kind: "prism.draft" | "prism.send" | "prism.roundtrip",
): JobView | null {
  const jobs = (workspace.active_jobs ?? []).filter((j) => j.kind === kind);
  return jobs.length ? jobs[jobs.length - 1]! : null;
}

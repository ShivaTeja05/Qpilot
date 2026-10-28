/**
 * The shell's queries: what this install is (`["system"]`), every workspace (`["workspaces"]`),
 * the open workspace's frame (`["w", key, "frame"]`) and its running jobs. Sections may use
 * these hooks too; the query keys follow docs/app.md §6 so live events keep them current.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type JobView, type Schemas } from "@/api/client";
import { jobPollMs } from "@/api/jobs";

export type WorkspaceView = Schemas["WorkspaceView"];
export type WorkspaceSummary = Schemas["WorkspaceSummary"];
export type SystemView = Schemas["SystemView"];
export type WorkspaceKind = "s" | "r";

/** What this install is and what it will use (version, model, autonomy, demo, policy lines). */
export function useSystem() {
  return useQuery({
    queryKey: ["system"],
    queryFn: () => unwrap(api.GET("/api/system")),
    staleTime: 60_000,
  });
}

/** Every workspace in the store, most recently changed first. */
export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => unwrap(api.GET("/api/workspaces")),
    select: (d) => d.workspaces,
  });
}

/** One workspace's frame: its file, stages, whether results show, the next step. */
export function useWorkspaceFrame(kind: WorkspaceKind | undefined, key: string | undefined) {
  return useQuery({
    queryKey: ["w", key, "frame"],
    enabled: Boolean(key && kind),
    queryFn: () =>
      kind === "s"
        ? unwrap(api.GET("/api/sessions/{sid}", { params: { path: { sid: key! } } }))
        : unwrap(api.GET("/api/studies/{study_id}", { params: { path: { study_id: key! } } })),
    // While the file warms after a start, the warm job's done event re-reads the frame; poll
    // slowly as well, in case the event stream is down.
    refetchInterval: (q) =>
      (q.state.data as { warming?: boolean } | undefined)?.warming ? 3000 : false,
  });
}

/** Jobs the server knows (running and recent), optionally for one workspace. */
export function useJobs(key?: string | null) {
  return useQuery({
    queryKey: key ? ["w", key, "jobs"] : ["jobs"],
    queryFn: () =>
      unwrap(api.GET("/api/jobs", { params: { query: key ? { key } : {} } })) as Promise<JobView[]>,
    refetchInterval: (q) => {
      const jobs = q.state.data as JobView[] | undefined;
      // The jobs' events keep this list current (api/live.ts); this poll only backs them up.
      return jobs?.some((j) => j.status === "queued" || j.status === "running")
        ? jobPollMs()
        : false;
    },
  });
}

/** The list entry of a workspace (counts, pending agent requests). */
export function useWorkspaceSummary(key: string | undefined): WorkspaceSummary | undefined {
  const list = useWorkspaces();
  return key ? list.data?.find((w) => w.key === key) : undefined;
}

/**
 * Every write from the page goes through {@link useWrite}: it sends, re-reads the workspace,
 * and says what happened in a toast (with Undo where the chain allows it). A `stale` answer
 * (409: someone decided since this view was read) re-reads the view and says so; a refusal is
 * shown in the server's own words.
 */
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { errorHeading, errorMessage, toast } from "@/ui";

export interface WriteToast {
  title: string;
  description?: string;
  /** Adds an Undo button to the toast. */
  undo?: () => void;
}

export interface WriteOptions<V, R> {
  /** The workspace key whose views to re-read after the write (and on `stale`). */
  workspaceKey?: string | null;
  mutationFn: (vars: V) => Promise<R>;
  /** The success toast (null: none). */
  success?: (result: R, vars: V) => WriteToast | string | null;
  /** Called after a successful write (after the views are re-read). */
  onSuccess?: (result: R, vars: V) => void;
  /** Called after a failed write (after the toast). */
  onError?: (error: unknown, vars: V) => void;
}

/** Re-read every query about one workspace (and the workspace list). */
export function refreshWorkspace(
  qc: QueryClient,
  key: string | null | undefined,
): Promise<unknown> {
  return Promise.all([
    key ? qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(key) }) : Promise.resolve(),
    qc.invalidateQueries({ queryKey: ["workspaces"] }),
  ]);
}

/** Say a failed write in words; on `stale`, re-read the workspace first. */
export function reportWriteError(qc: QueryClient, error: unknown, key?: string | null): void {
  if (error instanceof ApiError && error.stale) {
    void refreshWorkspace(qc, key);
    toast.info("Something was decided since you loaded this", {
      description:
        "Another tab or an agent wrote to this study. The page now shows the current state; look again before you decide.",
    });
    return;
  }
  if (error instanceof ApiError && error.needsKey) {
    toast.error("Open the link qPilot printed in your terminal", {
      description: "This page lost its launch key (qPilot may have been restarted).",
      duration: Infinity,
    });
    return;
  }
  toast.error(errorHeading(error), { description: errorMessage(error), duration: Infinity });
}

/** A write with re-reads and toasts built in (a TanStack mutation). */
export function useWrite<V = void, R = unknown>(options: WriteOptions<V, R>) {
  const qc = useQueryClient();
  return useMutation<R, unknown, V>({
    mutationFn: options.mutationFn,
    onSuccess: async (result, vars) => {
      await refreshWorkspace(qc, options.workspaceKey);
      const said = options.success?.(result, vars);
      if (said) {
        const t = typeof said === "string" ? { title: said } : said;
        toast.success(t.title, {
          description: t.description,
          action: t.undo ? { label: "Undo", onClick: t.undo } : undefined,
          duration: t.undo ? 10_000 : undefined,
        });
      }
      options.onSuccess?.(result, vars);
    },
    onError: (error, vars) => {
      reportWriteError(qc, error, options.workspaceKey);
      options.onError?.(error, vars);
    },
  });
}

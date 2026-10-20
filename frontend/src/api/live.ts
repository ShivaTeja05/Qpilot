/**
 * Live updates. One EventSource per tab on /api/events; each event invalidates exactly the
 * queries it concerns. Query-key convention (all features follow it):
 *
 *   ["system"] · ["workspaces"] · ["job", id]
 *   ["w", key, ...]   anything about one workspace (a session id or a study id)
 *
 * A `study.changed` / `proposals.changed` event for key K invalidates every query whose key
 * contains K, plus the workspace list. Writes made by an agent in another process arrive the
 * same way (the server watches the store on disk).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import type { JobView } from "./client";

export type LiveState = "connecting" | "live" | "offline";

interface LiveEvent {
  type: string;
  key?: string | null;
  job?: JobView;
  source?: string;
  seq?: number;
}

let state: LiveState = "connecting";
const listeners = new Set<() => void>();
const eventListeners = new Set<(event: LiveEvent) => void>();

function setState(next: LiveState): void {
  if (state === next) return;
  state = next;
  listeners.forEach((l) => l());
}

/** The connection state of the event stream (for the "live" dot in the top bar). */
export function useLiveState(): LiveState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
  );
}

/** Subscribe to raw events (e.g. to toast when an agent request arrives). */
export function onLiveEvent(listener: (event: LiveEvent) => void): () => void {
  eventListeners.add(listener);
  return () => eventListeners.delete(listener);
}

/** Mount once (in the app shell): keeps every open view in sync with the store. */
export function useLiveEvents(): void {
  const qc = useQueryClient();
  useEffect(() => {
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const handle = (raw: MessageEvent<string>) => {
      let event: LiveEvent;
      try {
        event = JSON.parse(raw.data) as LiveEvent;
      } catch {
        return;
      }
      eventListeners.forEach((l) => l(event));
      if (event.type === "job.updated" && event.job) {
        const job = event.job;
        qc.setQueryData<JobView>(["job", job.id], (old) => ({ ...old, ...job, result: old?.result }));
        if (job.status === "done" || job.status === "failed") {
          void qc.invalidateQueries({ queryKey: ["job", job.id] });
          if (job.key) invalidateKey(job.key);
          void qc.invalidateQueries({ queryKey: ["workspaces"] });
        }
        return;
      }
      if (event.type === "study.changed" || event.type === "proposals.changed") {
        if (event.key) invalidateKey(event.key);
        void qc.invalidateQueries({ queryKey: ["workspaces"] });
        return;
      }
      if (event.type === "settings.changed") void qc.invalidateQueries({ queryKey: ["system"] });
    };

    const invalidateKey = (key: string) =>
      void qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(key) });

    const connect = () => {
      if (closed) return;
      setState("connecting");
      source = new EventSource("/api/events", { withCredentials: true });
      source.onopen = () => {
        setState("live");
        // Anything may have changed while the stream was down: re-read what is shown.
        void qc.invalidateQueries();
      };
      source.onerror = () => {
        setState("offline");
        source?.close();
        retry = setTimeout(connect, 2000);
      };
      for (const type of [
        "hello",
        "job.updated",
        "study.changed",
        "proposals.changed",
        "settings.changed",
        "model.status",
      ]) {
        source.addEventListener(type, handle as EventListener);
      }
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      source?.close();
    };
  }, [qc]);
}

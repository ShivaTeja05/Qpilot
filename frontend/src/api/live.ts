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

/** How long a burst of events must be quiet before the views it touched are re-read. */
const COALESCE_MS = 150;

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
          else void qc.invalidateQueries({ queryKey: ["workspaces"] });
        }
        return;
      }
      if (event.type === "study.changed" || event.type === "proposals.changed") {
        if (event.key) invalidateKey(event.key);
        return;
      }
      if (event.type === "settings.changed") void qc.invalidateQueries({ queryKey: ["system"] });
    };

    // Writes come in bursts (a bulk accept of 100 proposals is 100 events): invalidations are
    // coalesced per key and flushed once the burst has been quiet for a moment, so a burst costs
    // one refetch per query, not one per event.
    const pending = new Set<string>();
    let flushTimer: ReturnType<typeof setTimeout> | undefined;
    const flush = () => {
      flushTimer = undefined;
      const keys = [...pending];
      pending.clear();
      if (keys.length === 0) return;
      void qc.invalidateQueries({ predicate: (q) => keys.some((k) => q.queryKey.includes(k)) });
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
    };
    const invalidateKey = (key: string) => {
      pending.add(key);
      clearTimeout(flushTimer);
      flushTimer = setTimeout(flush, COALESCE_MS);
    };

    const connect = () => {
      if (closed || document.hidden) return;
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
        source = null;
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
    // Browsers allow about six connections per site: a hidden tab gives its stream back and
    // reconnects (re-reading everything) when it is shown again, so many open tabs never starve
    // the API of connections.
    const onVisibility = () => {
      if (document.hidden) {
        clearTimeout(retry);
        source?.close();
        source = null;
        setState("connecting");
      } else if (!source) {
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      clearTimeout(flushTimer);
      source?.close();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [qc]);
}

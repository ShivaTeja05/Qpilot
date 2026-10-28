/**
 * Live updates. One EventSource per tab on /api/events; each event re-reads exactly the views it
 * concerns, once. Query-key convention (all features follow it):
 *
 *   ["system"] · ["workspaces"] · ["job", id] · ["jobs"]
 *   ["w", key, ...]   anything about one workspace (a session id or a study id)
 *
 * A `study.changed` / `proposals.changed` event for key K re-reads every query whose key contains
 * K, plus the workspace list. Writes made by an agent in another process arrive the same way (the
 * server watches the store on disk). What keeps that to one re-read per change ({@link Refresher}):
 *
 * * **One flush per burst.** Events are collected and flushed once the burst has been quiet for
 *   {@link COALESCE_MS} (at most {@link MAX_WAIT_MS} after the first), so a bulk accept of 100
 *   proposals, or a job that finishes and tells two keys, is one re-read per query.
 * * **Not what was read after.** A query whose last read started after the event arrived already
 *   shows that change (the server tells an event only after the write), so it is not read again;
 *   a query still reading when its change is flushed is not cut off (its answer would be thrown
 *   away), it is re-read once that read is done.
 * * **This tab's own writes.** A write re-reads its workspace as soon as it is answered
 *   (`refreshWorkspace`); the events it caused come back with this tab's {@link TAB_ID} as their
 *   `origin` and are dropped when that re-read covers them.
 * * **Job progress costs nothing.** `job.updated` updates the job and the running-jobs lists in
 *   place; only a finished job re-reads, and a job that only prepared a view (the gate, Trace,
 *   the audit's views) re-asks just the views that were waiting on it.
 * * **Reconnects re-read only when something changed.** The stream's `hello` names the store
 *   sequence; every answer names the sequence it was read at (`x-qpilot-store-seq`). After a
 *   reconnect (or a first connect that came after the first reads) the views are re-read only
 *   when the store changed meanwhile.
 */
import { useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import { ApiError, TAB_ID, onReadSeq, type JobView } from "./client";

export type LiveState = "connecting" | "live" | "offline";

/** How long a burst of events must be quiet before the views it touched are re-read. */
export const COALESCE_MS = 150;
/** A burst that goes on is flushed at least this often. */
export const MAX_WAIT_MS = 600;
/** This tab's own write: how long its event waits for the write's own re-read to cover it. */
export const OWN_WAIT_MS = 700;
/** A re-read by this tab this soon before its own write's event covers that event. */
export const OWN_WINDOW_MS = 2500;
/** A view still reading when its change is flushed is looked at again this much later. */
export const BUSY_RETRY_MS = 250;

/** Jobs that only prepare a view in memory: when done, re-ask the views waiting on them only. */
export const PREPARING_JOBS = new Set(["gate.run", "trace.load", "audit.load", "model.test"]);

export interface LiveEvent {
  type: string;
  key?: string | null;
  job?: JobView;
  source?: string;
  seq?: number;
  store_seq?: number;
  origin?: string | null;
  boot?: string;
}

let state: LiveState = "connecting";
const listeners = new Set<() => void>();
const eventListeners = new Set<(event: LiveEvent) => void>();

function setState(next: LiveState): void {
  if (state === next) return;
  state = next;
  listeners.forEach((l) => l());
}

/** The connection state now (for fallbacks that poll only while the stream is down). */
export function getLiveState(): LiveState {
  return state;
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

/** A query still waiting for the server to prepare its view (`loading` / `warming`). */
function waiting(q: Query): boolean {
  const e = q.state.error ?? q.state.fetchFailureReason;
  return e instanceof ApiError && e.warming;
}

/**
 * Turns events and this tab's writes into re-reads: one per query per change (see the module
 * doc). One per QueryClient; {@link useLiveEvents} makes it, tests drive it directly.
 */
export class Refresher {
  /** When each query's latest read started (by query hash). */
  private readAt = new Map<string, number>();
  /** Keys with a change not re-read yet → when the latest event about it arrived. */
  private pending = new Map<string, number>();
  /** This tab's own events waiting for its write's re-read → when each arrived. */
  private own = new Map<string, number>();
  /** When this tab last re-read each key itself after a write. */
  private refreshedAt = new Map<string, number>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private ownTimer: ReturnType<typeof setTimeout> | undefined;
  private firstPending: number | null = null;
  private unsubscribe: () => void;

  constructor(
    private readonly qc: QueryClient,
    private readonly now: () => number = () => performance.now(),
  ) {
    this.unsubscribe = qc.getQueryCache().subscribe((e) => {
      if (e.type === "updated" && e.action.type === "fetch") {
        this.readAt.set(e.query.queryHash, this.now());
      } else if (e.type === "removed") {
        this.readAt.delete(e.query.queryHash);
      }
    });
  }

  dispose(): void {
    clearTimeout(this.timer);
    clearTimeout(this.ownTimer);
    this.unsubscribe();
  }

  /** When this query's latest read started (-Infinity: never read). */
  readStart(q: Query): number {
    return this.readAt.get(q.queryHash) ?? -Infinity;
  }

  /** A store change of `key` was told (`own`: caused by this tab's request). */
  changed(key: string, own = false, at: number = this.now()): void {
    if (own) {
      const refreshed = this.refreshedAt.get(key);
      if (refreshed !== undefined && refreshed >= at - OWN_WINDOW_MS) return; // covered
      this.own.set(key, Math.max(this.own.get(key) ?? -Infinity, at));
      clearTimeout(this.ownTimer);
      this.ownTimer = setTimeout(() => this.releaseOwn(), OWN_WAIT_MS);
      return;
    }
    this.pending.set(key, Math.max(this.pending.get(key) ?? -Infinity, at));
    this.schedule();
  }

  /** Own events whose write was not re-read by the page in time: re-read them as any other. */
  private releaseOwn(): void {
    this.ownTimer = undefined;
    for (const [key, at] of this.own) {
      const refreshed = this.refreshedAt.get(key);
      if (refreshed === undefined || refreshed < at - OWN_WINDOW_MS) {
        this.pending.set(key, Math.max(this.pending.get(key) ?? -Infinity, at));
      }
    }
    this.own.clear();
    if (this.pending.size) this.schedule();
  }

  private schedule(): void {
    const now = this.now();
    this.firstPending ??= now;
    clearTimeout(this.timer);
    const wait = Math.max(0, Math.min(COALESCE_MS, this.firstPending + MAX_WAIT_MS - now));
    this.timer = setTimeout(() => void this.flush(), wait);
  }

  /**
   * Re-read what the pending changes touched: each query once, none read since the change, and
   * none cut off mid-read (a query still reading an older state is re-read when it is done).
   */
  flush(): Promise<unknown> {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.firstPending = null;
    const changes = [...this.pending];
    this.pending.clear();
    if (changes.length === 0) return Promise.resolve();
    const latest = Math.max(...changes.map(([, at]) => at));
    const chosen = new Set<string>();
    const later = new Map<string, number>();
    for (const q of this.qc.getQueryCache().getAll()) {
      const hit: [string, number][] =
        q.queryKey[0] === "workspaces" && q.queryKey.length === 1
          ? changes.filter(([, at]) => at === latest)
          : changes.filter(([key]) => q.queryKey.includes(key));
      if (hit.length === 0) continue;
      const at = Math.max(...hit.map(([, when]) => when));
      if (this.readStart(q) > at) continue; // read after the change: it shows it
      if (q.state.fetchStatus === "fetching" && q.getObserversCount() > 0) {
        for (const [key, when] of hit) later.set(key, Math.max(later.get(key) ?? -Infinity, when));
        continue;
      }
      chosen.add(q.queryHash);
    }
    if (later.size) {
      for (const [key, at] of later) {
        this.pending.set(key, Math.max(this.pending.get(key) ?? -Infinity, at));
      }
      this.firstPending ??= this.now();
      this.timer = setTimeout(() => void this.flush(), BUSY_RETRY_MS);
    }
    if (chosen.size === 0) return Promise.resolve();
    return this.qc.invalidateQueries({ predicate: (q) => chosen.has(q.queryHash) });
  }

  /** This tab wrote to `key`: re-read it now (resolves once re-read). */
  refreshNow(key: string | null | undefined): Promise<unknown> {
    const now = this.now();
    if (key) {
      this.refreshedAt.set(key, now);
      this.own.delete(key);
      // A change told before this moment is covered by this re-read.
      const at = this.pending.get(key);
      if (at !== undefined && at <= now) this.pending.delete(key);
    }
    return Promise.all([
      key
        ? this.qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(key) })
        : Promise.resolve(),
      this.qc.invalidateQueries({ queryKey: ["workspaces"] }),
    ]);
  }

  /** A job reported: update it and the running-jobs lists in place; re-read when it is done. */
  job(job: JobView): void {
    this.qc.setQueryData<JobView>(["job", job.id], (old) => ({
      ...old,
      ...job,
      result: old?.result,
    }));
    const running = job.status === "queued" || job.status === "running";
    const patch = (old: JobView[] | undefined) => {
      if (!old) return old;
      const rest = old.filter((j) => j.id !== job.id);
      return running ? [...rest, { ...job, result: null }] : rest;
    };
    this.qc.setQueriesData<JobView[]>({ queryKey: ["jobs"], exact: true }, patch);
    if (job.key) this.qc.setQueriesData<JobView[]>({ queryKey: ["w", job.key, "jobs"] }, patch);
    if (running) return;
    void this.qc.invalidateQueries({ queryKey: ["job", job.id] });
    if (!job.key) {
      void this.qc.invalidateQueries({ queryKey: ["workspaces"] });
      return;
    }
    if (PREPARING_JOBS.has(job.kind)) {
      const key = job.key;
      void this.qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(key) && waiting(q) });
      return;
    }
    this.changed(job.key);
  }

  /** Re-read every query read before `before` (after the stream missed changes). */
  refreshReadBefore(before: number): Promise<unknown> {
    this.pending.clear();
    return this.qc.invalidateQueries({ predicate: (q) => this.readStart(q) < before });
  }
}

const refreshers = new WeakMap<QueryClient, Refresher>();

/** The {@link Refresher} of this query client (made on first use). */
export function refresherOf(qc: QueryClient): Refresher {
  let r = refreshers.get(qc);
  if (!r) {
    r = new Refresher(qc);
    refreshers.set(qc, r);
  }
  return r;
}

/**
 * Follows the stream's `hello` against the sequence each answer was read at, and says when the
 * views shown may have missed a change (then: re-read what was read before the stream came up).
 */
class Missed {
  private known = -Infinity; // the newest store sequence this tab knows of
  private boot: string | null = null;
  private helloAt: number | null = null;
  private helloSeq: number | null = null;
  private oldestBefore = Infinity; // the oldest sequence read before the stream came up
  private fired = false; // the views were re-read for this hello already
  private greeted = false; // a hello came before (this is a reconnect)

  constructor(
    private readonly onMissed: (before: number) => void,
    private readonly now: () => number = () => performance.now(),
  ) {}

  read(seq: number, startedAt: number): void {
    this.known = Math.max(this.known, seq);
    if (this.helloAt === null || startedAt < this.helloAt) {
      if (this.helloAt !== null && this.helloSeq !== null && seq < this.helloSeq) {
        // Read before the stream came up, at a state older than the stream's first word.
        if (!this.fired) this.onMissed(this.helloAt);
        this.fired = true;
      } else {
        this.oldestBefore = Math.min(this.oldestBefore, seq);
      }
    }
  }

  told(seq: number | undefined): void {
    if (typeof seq === "number") this.known = Math.max(this.known, seq);
  }

  hello(seq: number | undefined, boot: string | undefined): void {
    const at = this.now();
    const again = this.greeted;
    this.greeted = true;
    const restarted = Boolean(boot && this.boot && boot !== this.boot);
    if (boot) this.boot = boot;
    const s = typeof seq === "number" ? seq : null;
    const missed =
      s === null ||
      restarted ||
      (again ? s > this.known : this.oldestBefore !== Infinity && s > this.oldestBefore);
    this.helloAt = at;
    this.helloSeq = s;
    this.oldestBefore = Infinity;
    this.fired = missed;
    if (s !== null) this.known = Math.max(this.known, s);
    if (missed) this.onMissed(at);
  }

  down(): void {
    // Reads from now on started while the stream was down: compared at the next hello.
    this.helloAt = null;
    this.helloSeq = null;
  }
}

/** Mount once (in the app shell): keeps every open view in sync with the store. */
export function useLiveEvents(): void {
  const qc = useQueryClient();
  useEffect(() => {
    const refresher = refresherOf(qc);
    const missed = new Missed((before) => void refresher.refreshReadBefore(before));
    const stopReads = onReadSeq((seq, startedAt) => missed.read(seq, startedAt));
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
      if (event.type === "hello") {
        missed.hello(event.store_seq, event.boot);
        return;
      }
      missed.told(event.store_seq);
      if (event.type === "job.updated" && event.job) {
        refresher.job(event.job);
        return;
      }
      if (event.type === "study.changed" || event.type === "proposals.changed") {
        if (event.key) refresher.changed(event.key, event.origin === TAB_ID);
        else void qc.invalidateQueries({ queryKey: ["workspaces"] });
        return;
      }
      if (event.type === "settings.changed") void qc.invalidateQueries({ queryKey: ["system"] });
    };

    const connect = () => {
      if (closed || document.hidden) return;
      setState("connecting");
      source = new EventSource("/api/events", { withCredentials: true });
      source.onopen = () => setState("live");
      source.onerror = () => {
        setState("offline");
        missed.down();
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
    // reconnects when it is shown again (re-reading only if the store changed meanwhile), so
    // many open tabs never starve the API of connections.
    const onVisibility = () => {
      if (document.hidden) {
        clearTimeout(retry);
        source?.close();
        source = null;
        missed.down();
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
      source?.close();
      stopReads();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [qc]);
}

export { Missed as _Missed };

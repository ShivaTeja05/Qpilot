/**
 * One change, one re-read: the Refresher turns bursts of events, this tab's own writes and job
 * progress into at most one re-read per affected query (perf, excellence round).
 */
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobView } from "./client";
import { ApiError } from "./client";
import {
  BUSY_RETRY_MS,
  COALESCE_MS,
  MAX_WAIT_MS,
  OWN_WAIT_MS,
  Refresher,
  _Missed as Missed,
} from "./live";

const SID = "bc1d233e3866";
const STUDY = "e300000d4f9a";

let clock = 0;
const now = () => clock;

function advance(ms: number) {
  clock += ms;
  vi.advanceTimersByTime(ms);
}

async function settle() {
  // Let invalidations' promises and refetches run (timers are fake; microtasks are real).
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await vi.runOnlyPendingTimersAsync();
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

/** A query client with active queries that count their reads. */
function world(keys: unknown[][]) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: Infinity } },
  });
  const reads = new Map<string, number>();
  const stops: (() => void)[] = [];
  for (const key of keys) {
    const name = JSON.stringify(key);
    reads.set(name, 0);
    const observer = new QueryObserver(qc, {
      queryKey: key,
      queryFn: async () => {
        reads.set(name, (reads.get(name) ?? 0) + 1);
        return { at: clock };
      },
    });
    stops.push(observer.subscribe(() => undefined));
  }
  const refresher = new Refresher(qc, now);
  const count = (key: unknown[]) => reads.get(JSON.stringify(key)) ?? 0;
  const total = () => [...reads.values()].reduce((a, b) => a + b, 0);
  return { qc, refresher, count, total, close: () => stops.forEach((s) => s()) };
}

const SESSION_VIEWS = [
  ["w", SID, "frame"],
  ["w", SID, "proposals", "design"],
  ["w", SID, "proposals", "curves"],
  ["w", SID, "plate", ""],
  ["w", SID, "quarantine"],
  ["w", SID, "confirm", "curves"],
  ["w", SID, "results", STUDY],
  ["workspaces"],
  ["system"],
];

beforeEach(() => {
  clock = 1000;
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("Refresher", () => {
  it("re-reads each affected query once for a burst of events about two keys", async () => {
    const w = world(SESSION_VIEWS);
    await settle();
    const before = w.total();
    for (let i = 0; i < 50; i++) {
      w.refresher.changed(i % 2 ? SID : STUDY);
      advance(10);
    }
    advance(COALESCE_MS + MAX_WAIT_MS);
    await settle();
    for (const key of SESSION_VIEWS.filter((k) => k[0] !== "system")) expect(w.count(key)).toBe(2);
    expect(w.count(["system"])).toBe(1); // not about the workspace
    expect(w.total() - before).toBe(SESSION_VIEWS.length - 1);
    w.close();
  });

  it("a burst that goes on is flushed at most every MAX_WAIT_MS", async () => {
    const w = world([["w", SID, "frame"]]);
    await settle();
    for (let i = 0; i < 20; i++) {
      w.refresher.changed(SID);
      advance(COALESCE_MS - 10); // never quiet long enough
    }
    await settle();
    const flushes = w.count(["w", SID, "frame"]) - 1;
    expect(flushes).toBeGreaterThanOrEqual(2);
    expect(flushes).toBeLessThanOrEqual(Math.ceil((20 * (COALESCE_MS - 10)) / MAX_WAIT_MS) + 1);
    w.close();
  });

  it("does not re-read a query whose read started after the event arrived", async () => {
    const w = world([["w", SID, "frame"]]);
    await settle();
    w.refresher.changed(SID);
    advance(5);
    await w.qc.refetchQueries({ queryKey: ["w", SID, "frame"] }); // read after the event
    advance(COALESCE_MS + 10);
    await settle();
    expect(w.count(["w", SID, "frame"])).toBe(2); // first read + the refetch, no third
    w.close();
  });

  it("this tab's write is re-read once: its own event is covered by the write's re-read", async () => {
    const w = world(SESSION_VIEWS);
    await settle();
    const before = w.total();
    // The write's events (the session and its study) arrive first, then the answer, then the
    // page re-reads the session.
    w.refresher.changed(SID, true);
    w.refresher.changed(STUDY, true);
    advance(20);
    await w.refresher.refreshNow(SID);
    advance(OWN_WAIT_MS + COALESCE_MS + 50);
    await settle();
    const session = SESSION_VIEWS.filter((k) => k.includes(SID));
    for (const key of session) expect(w.count(key)).toBe(2);
    expect(w.count(["workspaces"])).toBe(2);
    // The study-keyed view was read by the session's re-read too (its key holds both ids).
    expect(w.total() - before).toBe(session.length + 1);
    w.close();
  });

  it("an own event the page did not re-read for is re-read after OWN_WAIT_MS", async () => {
    const w = world([["w", SID, "frame"]]);
    await settle();
    w.refresher.changed(SID, true);
    advance(OWN_WAIT_MS - 50);
    await settle();
    expect(w.count(["w", SID, "frame"])).toBe(1);
    advance(100 + COALESCE_MS);
    await settle();
    expect(w.count(["w", SID, "frame"])).toBe(2);
    w.close();
  });

  it("another tab's or an agent's write is re-read (no origin, or another origin)", async () => {
    const w = world([["w", SID, "frame"]]);
    await settle();
    await w.refresher.refreshNow(SID); // this tab re-read a moment ago…
    advance(100);
    w.refresher.changed(SID); // …but this change is someone else's
    advance(COALESCE_MS + 10);
    await settle();
    expect(w.count(["w", SID, "frame"])).toBe(3);
    w.close();
  });
});

function job(over: Partial<JobView>): JobView {
  return {
    id: "j1",
    kind: "propose.design",
    title: "Proposing the design",
    key: SID,
    status: "running",
    step: "",
    fraction: null,
    typical_s: 9,
    elapsed_s: 1,
    result: null,
    result_type: null,
    error: null,
    ...over,
  } as JobView;
}

describe("Refresher and jobs", () => {
  it("job progress re-reads nothing and keeps the running-jobs list current in place", async () => {
    const w = world([...SESSION_VIEWS, ["jobs"]]);
    await settle();
    w.qc.setQueryData(["jobs"], []);
    const before = w.total();
    for (let i = 0; i < 30; i++) w.refresher.job(job({ step: `step ${i}`, fraction: i / 30 }));
    advance(COALESCE_MS * 4);
    await settle();
    expect(w.total()).toBe(before);
    expect(w.qc.getQueryData<JobView[]>(["jobs"])?.map((j) => j.step)).toEqual(["step 29"]);
    expect(w.qc.getQueryData<JobView>(["job", "j1"])?.step).toBe("step 29");
    // Done: off the list, and the workspace is re-read once (with the job's own events).
    w.refresher.job(job({ status: "done" }));
    w.refresher.changed(SID);
    advance(COALESCE_MS + 10);
    await settle();
    expect(w.qc.getQueryData<JobView[]>(["jobs"])).toEqual([]);
    expect(w.count(["w", SID, "frame"])).toBe(2);
    w.close();
  });

  it("a job that only prepared a view re-asks just the views waiting on it", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const refresher = new Refresher(qc, now);
    let gateReads = 0;
    let frameReads = 0;
    let ready = false;
    const gate = new QueryObserver(qc, {
      queryKey: ["w", SID, STUDY, "gate"],
      queryFn: async () => {
        gateReads += 1;
        if (!ready) throw new ApiError(409, "loading", "Checking the controls.");
        return { ok: true };
      },
    });
    const frame = new QueryObserver(qc, {
      queryKey: ["w", SID, "frame"],
      queryFn: async () => {
        frameReads += 1;
        return { ok: true };
      },
    });
    const stops = [gate.subscribe(() => undefined), frame.subscribe(() => undefined)];
    await settle();
    expect(gateReads).toBe(1);
    ready = true;
    refresher.job(job({ kind: "gate.run", key: STUDY, status: "done" }));
    await settle();
    expect(gateReads).toBe(2);
    expect(frameReads).toBe(1);
    expect(qc.getQueryData(["w", SID, STUDY, "gate"])).toEqual({ ok: true });
    stops.forEach((s) => s());
    refresher.dispose();
  });
});

describe("Missed (the stream's hello against the reads' store sequence)", () => {
  it("a first hello after reads of the same state re-reads nothing", () => {
    const missed: number[] = [];
    const m = new Missed((t) => missed.push(t), now);
    m.read(4, 900);
    m.read(4, 950);
    m.hello(4, "boot-a");
    expect(missed).toEqual([]);
  });

  it("a first hello after a change re-reads what was read before it", () => {
    const missed: number[] = [];
    const m = new Missed((t) => missed.push(t), now);
    m.read(4, 900);
    m.hello(5, "boot-a");
    expect(missed).toEqual([1000]);
  });

  it("a read that was in flight at hello and is older than it re-reads once", () => {
    const missed: number[] = [];
    const m = new Missed((t) => missed.push(t), now);
    m.hello(5, "boot-a");
    m.read(4, 900); // started before hello, older state
    m.read(4, 950);
    m.read(5, 1200); // started after: fine
    expect(missed).toEqual([1000]);
  });

  it("a reconnect re-reads only when the store changed meanwhile (or the server restarted)", () => {
    const missed: number[] = [];
    const m = new Missed((t) => missed.push(t), now);
    m.hello(3, "boot-a");
    m.told(7);
    m.down();
    clock = 2000;
    m.hello(7, "boot-a");
    expect(missed).toEqual([]);
    m.down();
    clock = 3000;
    m.hello(9, "boot-a");
    expect(missed).toEqual([3000]);
    m.down();
    clock = 4000;
    m.hello(1, "boot-b");
    expect(missed).toEqual([3000, 4000]);
  });
});

describe("Refresher and slow reads", () => {
  it("never cuts off a read in flight: the view is re-read once that read is done", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const refresher = new Refresher(qc, now);
    let reads = 0;
    let release: (() => void) | null = null;
    const observer = new QueryObserver(qc, {
      queryKey: ["w", SID, "plate", ""],
      queryFn: () =>
        new Promise<{ n: number }>((resolve) => {
          reads += 1;
          const n = reads;
          release = () => resolve({ n });
        }),
    });
    const stop = observer.subscribe(() => undefined);
    await settle();
    expect(reads).toBe(1); // in flight
    let cancelled = 0;
    const unsub = qc.getQueryCache().subscribe((e) => {
      if (e.type === "updated" && e.action.type === "error") cancelled += 1;
    });
    refresher.changed(SID);
    advance(COALESCE_MS + 10);
    await settle();
    refresher.changed(SID);
    advance(COALESCE_MS + 10);
    await settle();
    expect(reads).toBe(1); // still the first read, not cut off and not doubled
    release!();
    await settle();
    advance(BUSY_RETRY_MS + 10);
    await settle();
    expect(reads).toBe(2); // one re-read for both changes
    release!();
    await settle();
    advance(BUSY_RETRY_MS * 4);
    await settle();
    expect(reads).toBe(2);
    expect(cancelled).toBe(0);
    unsub();
    stop();
    refresher.dispose();
  });
});

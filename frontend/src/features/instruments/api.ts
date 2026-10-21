/**
 * The Instruments section's data (api: `qpilot/web/routers/instruments.py`, contract
 * `qpilot/web/contract_instruments.py`): the registry, each instrument's hash-chained logbook and
 * incidents, what a run file says about its instrument, and the lookback. Every write is the
 * person's own (the server records `actor="human"`); nothing here computes a number.
 *
 * Query keys: `["instruments"]` (the list) and `["instruments", id]` (one instrument). The registry
 * is not a workspace, so its views are re-read on the server's `instruments.changed` event and
 * after every write made here.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, postForm, unwrap, type Schemas } from "@/api/client";
import { onLiveEvent } from "@/api/live";
import { useWrite } from "@/shell/writes";

export type InstrumentsView = Schemas["InstrumentsView"];
export type InstrumentSummary = Schemas["InstrumentSummary"];
export type InstrumentView = Schemas["InstrumentView"];
export type CalibrationAge = Schemas["CalibrationAge"];
export type EventView = Schemas["EventView"];
export type IncidentView = Schemas["IncidentView"];
export type KindView = Schemas["KindView"];
export type Logged = Schemas["Logged"];
export type RunFileView = Schemas["RunFileView"];
export type RunQuestion = Schemas["RunQuestion"];
export type GateLineView = Schemas["GateLineView"];
export type Linked = Schemas["Linked"];
export type LookbackView = Schemas["LookbackView"];
export type EventBody = Schemas["EventBody"];
export type IncidentBody = Schemas["IncidentBody"];
export type RegisterBody = Schemas["RegisterBody"];
export type TypedKind = EventBody["kind"];
export type FactText = Schemas["FactText"];

export const INSTRUMENTS = "instruments";

/** Every registered instrument and its state now. */
export function useInstruments() {
  return useQuery({
    queryKey: [INSTRUMENTS],
    queryFn: () => unwrap(api.GET("/api/instruments")),
  });
}

/** One instrument: its state, its logbook in chain order and its incidents. */
export function useInstrument(id: string | null) {
  return useQuery({
    queryKey: [INSTRUMENTS, id],
    enabled: Boolean(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/instruments/{instrument_id}", {
          params: { path: { instrument_id: id! } },
        }),
      ),
  });
}

/** Re-read the registry when the server says a logbook changed (this tab, another, the CLI). */
export function useInstrumentsLive(): void {
  const qc = useQueryClient();
  useEffect(() => {
    const off = onLiveEvent((event) => {
      if (event.type === "instruments.changed")
        void qc.invalidateQueries({ queryKey: [INSTRUMENTS] });
    });
    return () => {
      off();
    };
  }, [qc]);
}

/** A logbook write: the server's own sentence in the toast, then the instrument as it is now. */
function useLogbookWrite<V>(mutationFn: (vars: V) => Promise<Logged>) {
  const qc = useQueryClient();
  return useWrite<V, Logged>({
    mutationFn,
    success: (result) => result.message,
    onSuccess: (result) => {
      qc.setQueryData([INSTRUMENTS, result.instrument.instrument.instrument_id], result.instrument);
      void qc.invalidateQueries({ queryKey: [INSTRUMENTS] });
    },
  });
}

/** Register an instrument (a person). */
export function useRegister(onDone?: (view: InstrumentView) => void) {
  const qc = useQueryClient();
  return useWrite<RegisterBody, InstrumentView>({
    mutationFn: (body) => unwrap(api.POST("/api/instruments", { body })),
    success: (view) => `${view.instrument.display_name} is registered.`,
    onSuccess: (view) => {
      void qc.invalidateQueries({ queryKey: [INSTRUMENTS] });
      onDone?.(view);
    },
  });
}

/** Log a calibration, a part change, a service visit, a move or a note. */
export function useLogEvent(id: string) {
  return useLogbookWrite<EventBody>((body) =>
    unwrap(
      api.POST("/api/instruments/{instrument_id}/events", {
        params: { path: { instrument_id: id } },
        body,
      }),
    ),
  );
}

/** Log an incident the person saw (confirmed, since a person logs it). */
export function useLogIncident(id: string) {
  return useLogbookWrite<IncidentBody>((body) =>
    unwrap(
      api.POST("/api/instruments/{instrument_id}/incidents", {
        params: { path: { instrument_id: id } },
        body,
      }),
    ),
  );
}

/** Confirm or turn down an incident an agent proposed (only a person can). */
export function useDecideIncident(id: string) {
  return useLogbookWrite<{ seq: number; decision: "confirm" | "reject" }>(({ seq, decision }) => {
    const params = { params: { path: { instrument_id: id, seq } } };
    return unwrap(
      decision === "confirm"
        ? api.POST("/api/instruments/{instrument_id}/incidents/{seq}/confirm", params)
        : api.POST("/api/instruments/{instrument_id}/incidents/{seq}/reject", params),
    );
  });
}

/** Note what fixed an incident (a person). */
export function useFixIncident(id: string) {
  return useLogbookWrite<{ seq: number; note: string; at?: string | null }>(({ seq, note, at }) =>
    unwrap(
      api.POST("/api/instruments/{instrument_id}/incidents/{seq}/fix", {
        params: { path: { instrument_id: id, seq } },
        body: { note, at: at || null },
      }),
    ),
  );
}

/** Read a run file: what it says about the instrument, and which instrument it names. */
export function useReadRun() {
  return useMutation<RunFileView, unknown, File>({
    mutationFn: (file) => {
      const form = new FormData();
      form.append("run", file, file.name);
      return postForm<RunFileView>("/api/instruments/runs", form);
    },
  });
}

/** Say which instrument a run file is from; the registry remembers it for the next file. */
export function useLinkRun(runId: string) {
  const qc = useQueryClient();
  return useWrite<string, Linked>({
    mutationFn: (instrumentId) =>
      unwrap(
        api.POST("/api/instruments/runs/{run_id}/link", {
          params: { path: { run_id: runId } },
          body: { instrument_id: instrumentId },
        }),
      ),
    success: (linked) => linked.message,
    onSuccess: () => void qc.invalidateQueries({ queryKey: [INSTRUMENTS] }),
  });
}

export interface LookbackInput {
  studyId: string;
  instrumentId: string;
  start: string;
  end: string;
}

/** Start a lookback (a job; nothing is saved). */
export function useStartLookback() {
  return useMutation({
    mutationFn: ({ studyId, instrumentId, start, end }: LookbackInput) =>
      unwrap(
        api.POST("/api/studies/{study_id}/lookback", {
          params: { path: { study_id: studyId } },
          body: { instrument_id: instrumentId, start, end },
        }),
      ),
  });
}

/**
 * The melt route's reads (api: `qpilot/web/routers/melt.py`, contract
 * `qpilot/web/contract_melt.py`): one plate's assays and calls, and the curves of the wells
 * asked for. Every number is the engine's (`qpilot/qpcr/melt.py`); nothing is computed here.
 * Query keys start with `["w", key, …]` so live events about the workspace re-read them.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type MeltView = Schemas["MeltView"];
export type MeltWell = Schemas["MeltWellView"];
export type MeltCall = Schemas["MeltCallView"];
export type MeltAssay = Schemas["MeltAssayView"];
export type MeltPeak = Schemas["MeltPeakView"];
export type MeltStatus = MeltCall["status"];

/** Where the melt curves come from: a Studio session or an analysed study. */
export type MeltSource = { kind: "session"; sid: string } | { kind: "study"; studyId: string };

/** At most this many wells' curves are asked for together (the route's own limit). */
export const MAX_MELT_WELLS = 12;

function query(run: string | null, wells: readonly string[]) {
  const q: { run?: string; wells?: string } = {};
  if (run) q.run = run;
  if (wells.length) q.wells = wells.slice(0, MAX_MELT_WELLS).join(",");
  return q;
}

function fetchMelt(source: MeltSource, run: string | null, wells: readonly string[]) {
  return source.kind === "session"
    ? unwrap(
        api.GET("/api/sessions/{sid}/melt", {
          params: { path: { sid: source.sid }, query: query(run, wells) },
        }),
      )
    : unwrap(
        api.GET("/api/studies/{study_id}/melt", {
          params: { path: { study_id: source.studyId }, query: query(run, wells) },
        }),
      );
}

/** One plate's melt calls (and, for `wells`, their curves). */
export function useMelt(
  source: MeltSource | null,
  run: string | null,
  wells: readonly string[] = [],
  enabled = true,
) {
  const key = source ? (source.kind === "session" ? source.sid : source.studyId) : "";
  const joined = wells.slice(0, MAX_MELT_WELLS).join(",");
  return useQuery({
    queryKey: ["w", key, "melt", source?.kind ?? "", run ?? "", joined],
    enabled: Boolean(source) && enabled,
    queryFn: () => fetchMelt(source!, run, joined ? joined.split(",") : []),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  });
}

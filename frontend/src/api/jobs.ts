/** Following slow work (curve fitting, the audit, the round trip) started by a request. */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type JobView } from "./client";

/** A job's live state; the event stream keeps it current, and the result is fetched once done. */
export function useJob(id: string | null | undefined) {
  return useQuery({
    queryKey: ["job", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id! } } })),
    // Events update the cache; poll slowly only as a fallback when the stream is down.
    refetchInterval: (q) => {
      const s = (q.state.data as JobView | undefined)?.status;
      return s === "done" || s === "failed" ? false : 5000;
    },
  });
}

/** Seconds as the page shows them: "8 s", "1 min 12 s". */
export function seconds(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "";
  const total = Math.max(0, Math.round(s));
  if (total < 60) return `${total} s`;
  const m = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${m} min ${rest} s` : `${m} min`;
}

import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { JobView } from "@/api/client";
import { useJob } from "@/api/jobs";
import { cn } from "@/lib/cn";
import { duration } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { ProgressBar } from "./feedback";

/**
 * Slow work, inline: the job's title and current step, the elapsed time against the typical
 * time ("usually ~50 s"), and a progress bar (determinate when the job reports a fraction).
 * Pass `id` (follows it with `useJob`) or a `job` you already hold. `children(result)` renders
 * the result once done; a failed job shows its message in words.
 */
export function JobCard({
  id,
  job: given,
  children,
  className,
  onDismiss,
}: {
  id?: string | null;
  job?: JobView | null;
  /** What to show when the job is done (receives `job.result`). */
  children?: (result: unknown, job: JobView) => ReactNode;
  className?: string;
  /** Adds a "Dismiss" link on a finished or failed card. */
  onDismiss?: () => void;
}) {
  const query = useJob(given ? null : id);
  const job = given ?? (query.data as JobView | undefined);
  const running = job?.status === "queued" || job?.status === "running";
  const now = useNow(1000, running);
  // The server's elapsed time, advanced locally between events.
  const fetchedAt = query.dataUpdatedAt || now;
  const elapsed = job ? job.elapsed_s + (running ? Math.max(0, (now - fetchedAt) / 1000) : 0) : 0;

  if (!job) {
    return (
      <div className={cn("flex items-center gap-2 rounded-xl border border-line bg-surface p-3 text-sm text-muted", className)}>
        <Loader2 className="size-4 animate-spin" aria-hidden /> Starting…
      </div>
    );
  }

  const typical = job.typical_s != null && job.typical_s > 0 ? job.typical_s : null;
  const over = typical != null && elapsed > typical * 1.5;
  return (
    <div
      className={cn(
        "rounded-xl border bg-surface p-3",
        job.status === "failed" ? "border-danger/40" : job.status === "done" ? "border-ok/30" : "border-line",
        className,
      )}
      aria-live="polite"
      aria-busy={running}
    >
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 shrink-0 [&_svg]:size-4">
          {running ? (
            <Loader2 className="animate-spin text-accent" aria-hidden />
          ) : job.status === "done" ? (
            <CheckCircle2 className="text-ok" aria-hidden />
          ) : (
            <XCircle className="text-danger" aria-hidden />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <p className="text-sm font-medium text-fg">{job.title}</p>
            <p className="text-xs text-muted tabular">
              {running ? (
                <>
                  {duration(elapsed)}
                  {typical ? <span className="text-faint"> · usually ~{duration(typical)}</span> : null}
                </>
              ) : job.status === "done" ? (
                <>done in {duration(job.elapsed_s)}</>
              ) : (
                <>stopped after {duration(job.elapsed_s)}</>
              )}
            </p>
          </div>
          {running ? (
            <>
              <p className="mt-0.5 truncate text-[13px] text-muted">{job.step || (job.status === "queued" ? "Waiting to start" : "Working")}</p>
              <ProgressBar className="mt-2" label={job.title} value={job.fraction} />
              {over ? (
                <p className="mt-1.5 text-xs text-faint">Taking longer than usual; it is still working.</p>
              ) : null}
            </>
          ) : job.status === "failed" ? (
            <p className="mt-0.5 text-[13px] text-danger">{job.error?.message ?? "It stopped before finishing."}</p>
          ) : null}
          {job.status === "done" && children ? <div className="mt-2">{children(job.result, job)}</div> : null}
          {!running && onDismiss ? (
            <button type="button" onClick={onDismiss} className="mt-2 text-xs text-muted underline-offset-2 hover:underline">
              Dismiss
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

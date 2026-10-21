/**
 * While the study's model loads (the first trace of a study answers 409 `loading` with the
 * `trace.load` job), follow that job; any other error is said in words.
 */
import { ErrorPanel, JobCard } from "@/ui";
import { loadingJob } from "./api";

export function TraceWaiting({
  error,
  onRetry,
  what,
}: {
  error: unknown;
  onRetry: () => void;
  what: string;
}) {
  const job = loadingJob(error);
  if (job) {
    return (
      <div className="flex flex-col gap-2" role="status">
        <p className="text-[13px] text-muted">
          Trace re-reads the study&rsquo;s wells from its file the first time (about a second on the
          demo); {what} opens as soon as it is done.
        </p>
        <JobCard id={job.id} job={null} />
      </div>
    );
  }
  return (
    <ErrorPanel
      title={`${what[0]!.toUpperCase()}${what.slice(1)} could not be traced`}
      error={error}
      onRetry={onRetry}
    />
  );
}

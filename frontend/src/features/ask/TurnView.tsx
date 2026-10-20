import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { ApiError } from "@/api/client";
import { useJob } from "@/api/jobs";
import { dateTime } from "@/lib/format";
import { ErrorPanel, JobCard } from "@/ui";
import { Answer, type AnswerLinks } from "./Answer";
import { updateTurn, type Turn } from "./history";
import { toAskView } from "./types";

const UNREADABLE =
  "qPilot finished, but its answer could not be read. Ask again; if it keeps happening, the page and the server are out of step (reload the page).";

/** Follows a running turn's job and stores the answer (or the failure) on the turn. */
function useFollow(studyId: string, turn: Turn): void {
  const following = turn.state === "running" ? turn.jobId : null;
  const job = useJob(following);
  const data = job.data;
  const fetching = job.isFetching;
  const failure = job.error;
  useEffect(() => {
    if (!following) return;
    if (data?.status === "done") {
      const answer = toAskView(data.result);
      if (answer) updateTurn(studyId, turn.id, { state: "done", answer });
      // The event stream marks a job done before its result is read; wait for that read.
      else if (!fetching)
        updateTurn(studyId, turn.id, { state: "failed", error: failure ?? new Error(UNREADABLE) });
    } else if (data?.status === "failed") {
      const e = data.error ?? {};
      updateTurn(studyId, turn.id, {
        state: "failed",
        error: new ApiError(
          500,
          e.code ?? "failed",
          e.message ?? "qPilot could not answer this question.",
        ),
      });
    } else if (failure && !fetching) {
      // The job could not be read (e.g. qPilot was restarted and forgot it).
      updateTurn(studyId, turn.id, { state: "failed", error: failure });
    }
  }, [following, data, fetching, failure, studyId, turn.id]);
}

/** One question and what came of it. */
export function TurnView({
  studyId,
  turn,
  links,
  onRetry,
}: {
  studyId: string;
  turn: Turn;
  links: AnswerLinks;
  onRetry: (turn: Turn) => void;
}) {
  useFollow(studyId, turn);
  return (
    <article
      className="flex scroll-mt-3 flex-col gap-2"
      data-turn={turn.id}
      aria-label={`Question: ${turn.question}`}
    >
      <div className="flex justify-end">
        <p
          className="max-w-[88%] whitespace-pre-wrap break-words rounded-xl rounded-br-sm bg-accent-soft px-3 py-2 text-sm text-fg"
          title={`Asked ${dateTime(turn.askedAt)}`}
        >
          <span className="sr-only">You asked: </span>
          {turn.question}
        </p>
      </div>
      {turn.state === "sending" ? (
        <p className="flex items-center gap-2 text-[13px] text-muted" role="status">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Sending your question…
        </p>
      ) : turn.state === "running" ? (
        <JobCard id={turn.jobId} />
      ) : turn.state === "failed" ? (
        <ErrorPanel
          compact
          error={turn.error}
          title={errorTitle(turn.error)}
          onRetry={() => onRetry(turn)}
        />
      ) : turn.answer ? (
        <div className="rounded-xl border border-line bg-surface p-3">
          <span className="sr-only">qPilot answered: </span>
          <Answer answer={turn.answer} links={links} />
        </div>
      ) : null}
    </article>
  );
}

function errorTitle(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return "No answer";
  if (error.code === "blind") return "Not answered while the study is blind";
  if (error.code === "no_audit") return "The audit cannot answer this yet";
  if (error.code === "no_results") return "No results to ask about yet";
  return error.needsKey || error.stale || error.code === "offline" ? undefined : "No answer";
}

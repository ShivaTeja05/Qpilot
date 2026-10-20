/** Recent agent activity, newest first: requests and choices on Decision Cards, and proposals. */
import { GitCommitHorizontal, Lightbulb } from "lucide-react";
import type { ReactNode } from "react";
import { dateTime, relativeTime } from "@/lib/format";
import { CHECK, STATUS_WORDS, type CheckStatus } from "@/lib/vocab";
import { STATUS as ENTRY_STATUS } from "@/features/record/words";
import { Badge, CheckTag, type Tone } from "@/ui";
import type { AgentActivity } from "./types";

/** A status word and tone for a chain entry's or a proposal's status. */
function statusOf(a: AgentActivity): { word: string; tone: Tone } {
  if (a.kind === "decision") {
    const s = ENTRY_STATUS[a.status as keyof typeof ENTRY_STATUS];
    if (s) return { word: s.word, tone: s.tone };
  } else {
    const word = STATUS_WORDS[a.status as keyof typeof STATUS_WORDS];
    if (word) {
      const tone: Tone =
        a.status === "proposed" ? "warn" : a.status === "rejected" ? "danger" : a.status === "superseded" ? "neutral" : "ok";
      return { word, tone };
    }
  }
  return { word: a.status, tone: "neutral" };
}

export function ActivityList({
  items,
  now,
  where,
}: {
  items: AgentActivity[];
  now: number;
  /** Which workspace an item is about, when it is not the open one (a link). */
  where: (item: AgentActivity) => ReactNode;
}) {
  return (
    <ol className="flex flex-col divide-y divide-line" aria-label="Recent agent activity, newest first">
      {items.map((a, i) => {
        const s = statusOf(a);
        const place = where(a);
        const check = a.check && a.check in CHECK ? (a.check as CheckStatus) : null;
        return (
          <li key={`${a.kind}-${a.proposal_id ?? a.card_id}-${a.at}-${i}`} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
            <span
              className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle text-muted [&_svg]:size-3.5"
              aria-hidden
            >
              {a.kind === "proposal" ? <Lightbulb /> : <GitCommitHorizontal />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                <p className="min-w-0 text-[13px] font-medium text-fg">{a.summary}</p>
                <div className="flex shrink-0 items-center gap-1.5">
                  {check ? <CheckTag status={check} /> : null}
                  <Badge tone={s.tone}>{s.word}</Badge>
                </div>
              </div>
              {a.reason ? (
                <p className="mt-1 line-clamp-2 text-[13px] text-muted">
                  <span className="sr-only">Reason: </span>“{a.reason}”
                </p>
              ) : null}
              <p className="mt-1 text-xs text-faint">
                {a.agent || "An agent"} ·{" "}
                <time dateTime={a.at} title={dateTime(a.at)}>
                  {relativeTime(a.at, now)}
                </time>
                {place ? <> · {place}</> : null}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

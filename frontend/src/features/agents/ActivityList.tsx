/** Recent agent activity, newest first: requests and choices on Decision Cards, and proposals. */
import { GitCommitHorizontal, Lightbulb } from "lucide-react";
import type { ReactNode } from "react";
import { dateTime, relativeTime } from "@/lib/format";
import { STATUS_WORDS } from "@/lib/vocab";
import { STATUS as ENTRY_STATUS } from "@/features/record/words";
import { Badge, type Tone } from "@/ui";
import type { AgentActivity } from "./types";

/** A status word and tone for a chain entry's or a proposal's status. */
function statusOf(a: AgentActivity): { word: string; tone: Tone } {
  if (a.what === "decision") {
    const s = ENTRY_STATUS[a.status as keyof typeof ENTRY_STATUS];
    if (s) return { word: s.word, tone: s.tone };
  } else {
    const word = STATUS_WORDS[a.status as keyof typeof STATUS_WORDS];
    if (word) {
      const tone: Tone = a.status === "proposed" ? "warn" : a.status === "rejected" ? "danger" : a.status === "superseded" ? "neutral" : "ok";
      return { word, tone };
    }
  }
  return { word: a.status, tone: "neutral" };
}

export function ActivityList({
  items,
  now,
  studyNote,
}: {
  items: AgentActivity[];
  now: number;
  /** Which study an item is about, when it is not the open one. */
  studyNote: (item: AgentActivity) => ReactNode;
}) {
  return (
    <ol className="flex flex-col divide-y divide-line" aria-label="Recent agent activity, newest first">
      {items.map((a, i) => {
        const s = statusOf(a);
        const note = studyNote(a);
        return (
          <li key={a.id ?? `${a.at}-${i}`} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle text-muted [&_svg]:size-3.5" aria-hidden>
              {a.what === "proposal" ? <Lightbulb /> : <GitCommitHorizontal />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                <p className="min-w-0 text-[13px] text-fg">
                  <span className="text-muted">{a.what === "proposal" ? "Proposed: " : "Decision card: "}</span>
                  <span className="font-medium">{a.title}</span>
                </p>
                <Badge tone={s.tone}>{s.word}</Badge>
              </div>
              {a.detail ? <p className="mt-0.5 text-[13px] text-muted">{a.detail}</p> : null}
              {a.reason ? <p className="mt-1 line-clamp-2 text-[13px] text-muted">“{a.reason}”</p> : null}
              <p className="mt-1 text-xs text-faint">
                {a.agent || "An agent"} ·{" "}
                <time dateTime={a.at} title={dateTime(a.at)}>
                  {relativeTime(a.at, now)}
                </time>
                {note ? <> · {note}</> : null}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

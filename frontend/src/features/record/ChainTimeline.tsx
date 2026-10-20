/**
 * The decision chain as a timeline, newest first, ending at its root (the input file). Each
 * entry shows its hash and the hash it links to, so the chain is visible: change any line and
 * every later link breaks. The server re-computes the hashes (`chain_intact`); the links drawn
 * here only compare neighbours.
 */
import { ArrowLeft, Bot, Cog, FileDigit, Link2, Unlink, User } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count, dateTime, relativeTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { Badge, Card, CardHeader, Hash, SegmentedControl, Tooltip } from "@/ui";
import type { Actor, ChainEntry } from "./types";
import { ACTOR, STATUS, cardTitle, optionLabel } from "./words";

type Filter = "all" | Actor;

const ACTOR_ICON: Record<Actor, ReactNode> = {
  human: <User aria-hidden />,
  agent: <Bot aria-hidden />,
  system: <Cog aria-hidden />,
};

/** What an entry links to: the entry before it, or the chain's root for the first one. */
function linkOf(entry: ChainEntry, previous: ChainEntry | undefined, root: string) {
  const target = previous ? previous.hash : root;
  const label = previous ? `#${previous.seq}` : "the input file";
  return { ok: entry.prev_hash === target, label };
}

export function ChainTimeline({
  entries,
  root,
  head,
  intact,
  actions,
}: {
  entries: ChainEntry[];
  root: string;
  head: string;
  /** The server's verdict on the whole chain (hashes re-computed), when it gives one. */
  intact?: boolean | null;
  /** Extra controls in the header (e.g. a link to the waiting requests). */
  actions?: ReactNode;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const now = useNow(60_000);
  const ordered = useMemo(() => [...entries].sort((a, b) => a.seq - b.seq), [entries]);
  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: ordered.length, human: 0, agent: 0, system: 0 };
    for (const e of ordered) c[e.actor] += 1;
    return c;
  }, [ordered]);
  const shown = ordered
    .map((entry, i) => ({ entry, previous: ordered[i - 1] }))
    .filter(({ entry }) => filter === "all" || entry.actor === filter)
    .reverse();
  const hidden = ordered.length - shown.length;

  const options = (["all", "human", "agent", "system"] as const).map((f) => ({
    value: f,
    label: (
      <>
        {f === "all" ? "All" : ACTOR[f].filter}
        <span className="font-mono text-[11px] text-faint tabular">{count(counts[f])}</span>
      </>
    ),
    disabled: f !== "all" && counts[f] === 0,
  }));

  return (
    <Card as="section" aria-labelledby="chain-title">
      <CardHeader
        id="chain-title"
        title="Decision chain"
        hint="Every decision on this study, newest first. Each entry's hash covers the entry before it, so changing any line breaks every later link."
        actions={actions}
      />
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-y border-line bg-sunken/60 px-4 py-2.5">
        <dl className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px]">
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">Head</dt>
            <dd>
              <Hash value={head} prefix="chain" />
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">Entries</dt>
            <dd className="font-mono tabular text-fg">{count(ordered.length)}</dd>
          </div>
          {intact != null ? (
            <div className="flex items-center gap-1.5">
              <dt className="sr-only">Chain check</dt>
              <dd>
                {intact ? (
                  <Badge tone="ok" icon={<Link2 />}>
                    Intact: every hash checks out
                  </Badge>
                ) : (
                  <Badge tone="danger" icon={<Unlink />}>
                    Broken: a line was changed
                  </Badge>
                )}
              </dd>
            </div>
          ) : null}
        </dl>
        <SegmentedControl label="Show entries by" size="sm" value={filter} onValueChange={setFilter} options={options} />
      </div>

      <ol className="px-4 pt-4" aria-label="Decision chain entries, newest first">
        {shown.map(({ entry, previous }) => (
          <TimelineEntry
            key={entry.hash}
            entry={entry}
            link={linkOf(entry, previous, root)}
            isHead={entry.hash === head}
            now={now}
          />
        ))}
        {hidden > 0 ? (
          <li className="relative pb-4 pl-12 text-[13px] text-faint">
            <Rail />
            {count(hidden)} {hidden === 1 ? "entry" : "entries"} by others hidden by the filter.
          </li>
        ) : null}
        <li className="relative flex items-start gap-3 pb-4">
          <span className="relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full border border-dashed border-line-strong bg-surface text-faint [&_svg]:size-4">
            <FileDigit aria-hidden />
          </span>
          <div className="min-w-0 pt-1.5 text-[13px]">
            <p className="font-medium text-fg">Start of the chain: the input file</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-1 text-muted">
              The first entry links to the file's SHA-256 <Hash value={root} prefix="sha256" />
            </p>
          </div>
        </li>
      </ol>
    </Card>
  );
}

/** The vertical line behind the nodes. */
function Rail() {
  return <span aria-hidden className="absolute top-0 bottom-0 left-[17px] w-px bg-line" />;
}

function TimelineEntry({
  entry,
  link,
  isHead,
  now,
}: {
  entry: ChainEntry;
  link: { ok: boolean; label: string };
  isHead: boolean;
  now: number;
}) {
  const status = STATUS[entry.status] ?? { word: entry.status, tone: "neutral" as const, meaning: "" };
  const actor = ACTOR[entry.actor] ?? { word: entry.actor, long: entry.actor };
  const settled = entry.status === "rejected" || entry.status === "stale";
  return (
    <li className="relative flex items-start gap-3 pb-5">
      <Rail />
      <Tooltip content={`${actor.word}: ${actor.long}`}>
        <span
          tabIndex={0}
          aria-label={actor.word}
          className={cn(
            "relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full border bg-surface [&_svg]:size-4",
            entry.actor === "human" && "border-accent/40 text-accent-strong",
            entry.actor === "agent" && "border-info/40 text-info",
            entry.actor === "system" && "border-line-strong text-muted",
            entry.status === "pending_human" && "ring-2 ring-warn/40 ring-offset-2 ring-offset-surface",
          )}
        >
          {ACTOR_ICON[entry.actor]}
        </span>
      </Tooltip>

      <article className={cn("min-w-0 flex-1 rounded-lg pt-1", settled && "opacity-80")} aria-label={`Entry ${entry.seq}`}>
        <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <h3 className="min-w-0 text-sm font-semibold text-fg">
            <span className="mr-1.5 font-mono text-[12px] font-medium text-faint tabular">#{entry.seq}</span>
            {cardTitle(entry)}
          </h3>
          <div className="flex shrink-0 items-center gap-1.5">
            {isHead ? <Badge tone="accent">Head</Badge> : null}
            <Tooltip content={status.meaning}>
              <Badge tone={status.tone} tabIndex={0}>
                {status.word}
              </Badge>
            </Tooltip>
          </div>
        </header>

        <p className="mt-1 text-[13px] text-muted">
          {entry.status === "pending_human" ? "Asked for " : entry.status === "rejected" ? "Turned down " : "Chose "}
          <span className="font-medium text-fg">{optionLabel(entry)}</span>
          {entry.option_label && entry.option_label !== entry.option ? (
            <span className="ml-1.5 font-mono text-[11.5px] text-faint">{entry.option}</span>
          ) : null}
        </p>

        {entry.reason ? (
          <blockquote className="mt-2 border-l-2 border-line-strong pl-3 text-[13px] text-fg">{entry.reason}</blockquote>
        ) : null}

        <footer className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span>
            {actor.word} ·{" "}
            <time dateTime={entry.at} title={dateTime(entry.at)}>
              {relativeTime(entry.at, now)}
            </time>
          </span>
          <span className="flex flex-wrap items-center gap-0.5">
            <Hash value={entry.hash} prefix="hash" />
            <ArrowLeft className="size-3 text-faint" aria-label="links to" />
            <Hash value={entry.prev_hash} prefix="prev" />
            {link.ok ? (
              <span className="ml-1 inline-flex items-center gap-1 text-ok">
                <Link2 className="size-3" aria-hidden /> links to {link.label}
              </span>
            ) : (
              <span className="ml-1 inline-flex items-center gap-1 text-danger">
                <Unlink className="size-3" aria-hidden /> does not link to {link.label}
              </span>
            )}
          </span>
        </footer>
      </article>
    </li>
  );
}

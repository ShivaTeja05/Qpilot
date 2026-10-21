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
import type { Actor, ChainEntry, StaleAttempt } from "./types";
import { ACTOR, ANSWERED, STATUS, cardTitle, optionLabel } from "./words";

type Filter = "all" | Actor;

const ACTOR_ICON: Record<Actor, ReactNode> = {
  human: <User aria-hidden />,
  agent: <Bot aria-hidden />,
  system: <Cog aria-hidden />,
};

/** What an entry links to: the entry before it, or the chain's root (the input file) for the first. */
function linkOf(entry: ChainEntry, previous: ChainEntry | undefined, root: string | null) {
  const target = previous ? previous.hash : root;
  const label = previous ? `#${previous.seq}` : "the input file";
  return { ok: target == null || entry.prev_hash === target, label };
}

export function ChainTimeline({
  entries,
  root,
  head,
  intact,
  brokenAt,
  waiting,
  attempts = [],
  actions,
}: {
  entries: ChainEntry[];
  /** The chain's genesis: the input file's SHA-256. */
  root: string | null;
  head: string;
  /** The server's verdict on the whole chain (hashes re-computed), when it gives one. */
  intact?: boolean | null;
  /** The first entry that fails, when the server found the chain broken. */
  brokenAt?: number | null;
  /** Hashes of the agent requests still waiting (others were answered in later entries). */
  waiting?: string[];
  /** Writes refused as stale: logged beside the chain, they never moved the head. */
  attempts?: StaleAttempt[];
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
                    {brokenAt != null
                      ? `Broken at entry ${brokenAt}: a line was changed`
                      : "Broken: a line was changed"}
                  </Badge>
                )}
              </dd>
            </div>
          ) : null}
        </dl>
        <SegmentedControl
          label="Show entries by"
          size="sm"
          value={filter}
          onValueChange={setFilter}
          options={options}
        />
      </div>

      <ol className="px-4 pt-4" aria-label="Decision chain entries, newest first">
        {shown.map(({ entry, previous }) => (
          <TimelineEntry
            key={entry.hash}
            entry={entry}
            link={linkOf(entry, previous, root)}
            isHead={entry.hash === head}
            answered={
              entry.status === "pending_human" && waiting != null && !waiting.includes(entry.hash)
            }
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
              The first entry links to the file's SHA-256{" "}
              <Hash value={root ?? ordered[0]?.prev_hash} prefix="sha256" />
            </p>
          </div>
        </li>
      </ol>
      {attempts.length ? <Attempts attempts={attempts} now={now} /> : null}
    </Card>
  );
}

const ATTEMPTED: Record<string, string> = {
  applied: "set",
  pending_human: "ask a person to set",
  rejected: "turn down",
};

/** Writes that did not change the study: each was based on a view the chain had moved past. */
function Attempts({ attempts, now }: { attempts: StaleAttempt[]; now: number }) {
  return (
    <details className="group border-t border-line px-4 py-3">
      <summary className="cursor-pointer text-[13px] font-medium text-fg outline-offset-2">
        {attempts.length === 1 ? "1 attempt" : `${count(attempts.length)} attempts`} did not change
        the study
        <span className="ml-1.5 font-normal text-muted">(stale: something was decided first)</span>
      </summary>
      <p className="mt-1.5 text-xs text-muted">
        They are logged beside the chain, not in it, so they never moved the head; the record keeps
        them.
      </p>
      <ol className="mt-2 flex flex-col divide-y divide-line rounded-lg border border-line">
        {[...attempts].reverse().map((a, i) => (
          <li key={`${a.at}-${i}`} className="px-3 py-2 text-[13px]">
            <p className="text-fg">
              <span className="text-muted">
                {ACTOR[a.actor as Actor]?.word ?? a.actor} tried to{" "}
                {ATTEMPTED[a.attempted] ?? a.attempted}{" "}
              </span>
              <span className="font-medium">{a.card_title}</span>
              <span className="text-muted"> → </span>
              <span className="font-medium">{a.option_label}</span>
            </p>
            {a.reason ? <p className="mt-0.5 text-muted">“{a.reason}”</p> : null}
            <p className="mt-1 flex flex-wrap items-center gap-x-1 text-xs text-faint">
              <time dateTime={a.at} title={dateTime(a.at)}>
                {relativeTime(a.at, now)}
              </time>
              {a.expected_head ? (
                <>
                  · it read <Hash value={a.expected_head} prefix="chain" />
                </>
              ) : null}
              {a.head ? (
                <>
                  · the chain was already at <Hash value={a.head} />
                </>
              ) : null}
            </p>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** The vertical line behind the nodes. */
function Rail() {
  return <span aria-hidden className="absolute top-0 bottom-0 left-[17px] w-px bg-line-strong" />;
}

function TimelineEntry({
  entry,
  link,
  isHead,
  answered,
  now,
}: {
  entry: ChainEntry;
  link: { ok: boolean; label: string };
  isHead: boolean;
  /** An agent's request a person answered later. */
  answered: boolean;
  now: number;
}) {
  const status = answered
    ? ANSWERED
    : (STATUS[entry.status] ?? { word: entry.status, tone: "neutral" as const, meaning: "" });
  const actor = ACTOR[entry.actor] ?? { word: entry.actor, long: entry.actor };
  const settled = entry.status === "rejected" || entry.status === "stale";
  return (
    <li className="relative flex items-start gap-3 pb-5">
      <Rail />
      <Tooltip content={`${actor.word}: ${actor.long}`}>
        <span
          role="img"
          tabIndex={0}
          aria-label={actor.word}
          className={cn(
            "relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full border bg-surface [&_svg]:size-4",
            entry.actor === "human" && "border-accent/40 text-accent-strong",
            entry.actor === "agent" && "border-info/40 text-info",
            entry.actor === "system" && "border-line-strong text-muted",
            entry.status === "pending_human" &&
              !answered &&
              "ring-2 ring-warn/40 ring-offset-2 ring-offset-surface",
          )}
        >
          {ACTOR_ICON[entry.actor]}
        </span>
      </Tooltip>

      <article
        className={cn("min-w-0 flex-1 rounded-lg pt-1", settled && "opacity-80")}
        aria-label={`Entry ${entry.seq}`}
      >
        <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <h3 className="min-w-0 text-sm font-semibold text-fg">
            <span className="mr-1.5 font-mono text-[12px] font-medium text-faint tabular">
              #{entry.seq}
            </span>
            {cardTitle(entry)}
          </h3>
          <div className="flex shrink-0 items-center gap-1.5">
            {isHead ? <Badge tone="accent">Head</Badge> : null}
            {entry.undo ? <Badge tone="info">Undo</Badge> : null}
            <Tooltip content={status.meaning}>
              <Badge tone={status.tone} tabIndex={0}>
                {status.word}
              </Badge>
            </Tooltip>
          </div>
        </header>

        <p className="mt-1 text-[13px] text-muted">
          {entry.status === "pending_human"
            ? "Asked for "
            : entry.status === "rejected"
              ? "Turned down "
              : entry.undo
                ? "Back to "
                : "Chose "}
          <span className="font-medium text-fg">{optionLabel(entry)}</span>
          {entry.option_label && entry.option_label !== entry.option ? (
            <span className="ml-1.5 font-mono text-[11.5px] text-faint">{entry.option}</span>
          ) : null}
        </p>

        {entry.reason ? (
          <blockquote className="mt-2 border-l-2 border-line-strong pl-3 text-[13px] text-fg">
            {entry.reason}
          </blockquote>
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

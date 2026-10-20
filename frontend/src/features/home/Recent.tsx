/**
 * Recent workspaces (`GET /api/workspaces`): one card per Studio session or study, newest first,
 * with where it stands. Cards are links (Tab reaches each); the arrow keys, Home and End move
 * between them too.
 */
import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  Check,
  Circle,
  CircleDashed,
  FlaskConical,
  FolderOpen,
  GitBranch,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { Link } from "wouter";
import { Badge, EmptyState, ErrorPanel, Input, SectionTitle, Skeleton } from "@/ui";
import { cn } from "@/lib/cn";
import { dateTime, plural, relativeTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { sectionPath } from "@/shell/sections";
import {
  countsLine,
  stageChip,
  workspaceSection,
  type StageState,
  type StageView,
  type WorkspaceSummary,
} from "./workspace";

/** Show a filter box once the list is longer than this. */
const FILTER_FROM = 6;

const CHIP: Record<StageState, string> = {
  confirmed: "border-ok/25 bg-ok-soft text-ok",
  waiting: "border-accent/30 bg-accent-soft text-accent-strong",
  open: "border-line-strong bg-surface text-muted",
  closed: "border-dashed border-line-strong text-muted",
};

function StageChip({ stage }: { stage: StageView }) {
  const c = stageChip(stage);
  const icon =
    c.state === "confirmed" ? (
      <Check />
    ) : c.state === "waiting" ? (
      <Circle className="fill-current" />
    ) : c.state === "open" ? (
      <Circle />
    ) : (
      <CircleDashed />
    );
  return (
    <li
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs font-medium [&_svg]:size-3",
        CHIP[c.state],
      )}
      title={c.words}
    >
      <span className="inline-flex">{icon}</span>
      <span>
        {c.label}
        {c.state === "waiting" ? <span className="tabular"> · {stage.pending}</span> : null}
      </span>
    </li>
  );
}

function WorkspaceCard({ w, now }: { w: WorkspaceSummary; now: number }) {
  const id = useId();
  const href = sectionPath({ key: w.key, kind: w.kind }, workspaceSection(w));
  const counts = countsLine(w);
  const decisions = w.decisions
    ? `${plural(w.decisions, "decision")} recorded`
    : "No decisions yet";
  const updated = `updated ${relativeTime(w.updated_at, now)}`;
  // What a screen reader hears after the title (the visible parts are icons, chips and badges).
  const details = [
    w.file_name,
    w.is_demo && "demo",
    w.kind === "study" && "analysed outside Studio",
    w.has_audit && "audited",
    w.pending_requests > 0 && `${plural(w.pending_requests, "agent request")} waiting`,
    !w.file_present && "file missing or changed",
    counts && `in the file: ${counts}`,
    ...(w.kind === "session" ? w.stages.map((s) => stageChip(s).words) : []),
    decisions,
    updated,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    // The title is the link, stretched over the whole card (its ::after), so the link's name is
    // the title and the rest of the card is its description.
    <article className="group relative flex h-full flex-col rounded-xl border border-line bg-surface p-4 transition-[border-color,box-shadow,transform] duration-150 ease-out hover:border-line-strong hover:shadow-md has-[a:focus-visible]:border-accent has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-focus motion-safe:hover:-translate-y-px">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-bg-subtle text-muted [&_svg]:size-4"
          aria-hidden
        >
          {w.kind === "session" ? <Sparkles /> : <FlaskConical />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 text-[15px] leading-snug font-semibold tracking-tight text-fg">
            <Link
              href={href}
              data-card
              aria-describedby={`${id}-details`}
              className="outline-none after:absolute after:inset-0 after:rounded-xl after:content-['']"
            >
              {w.title}
            </Link>
          </h3>
          <p
            className="mt-0.5 truncate font-mono text-xs text-muted"
            title={w.file_name ?? undefined}
          >
            {w.file_name ?? "No file name recorded"}
          </p>
        </div>
        <ArrowRight
          className="mt-1 size-4 shrink-0 text-faint transition-[transform,color] duration-150 ease-out group-hover:text-accent motion-safe:group-hover:translate-x-0.5"
          aria-hidden
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {w.is_demo ? <Badge>Demo</Badge> : null}
        {w.kind === "study" ? <Badge tone="info">Analysed outside Studio</Badge> : null}
        {w.has_audit ? (
          <Badge tone="accent" icon={<ShieldCheck />}>
            Audited
          </Badge>
        ) : null}
        {w.pending_requests > 0 ? (
          <Badge tone="warn" icon={<BellRing />}>
            {plural(w.pending_requests, "agent request")} waiting
          </Badge>
        ) : null}
        {!w.file_present ? (
          <Badge tone="warn" icon={<AlertTriangle />}>
            File missing or changed
          </Badge>
        ) : null}
      </div>

      {counts ? (
        <p className="mt-3 text-[13px] text-fg tabular">
          <span className="text-muted">In the file:</span> {counts}
        </p>
      ) : null}

      {w.kind === "session" && w.stages.length ? (
        <ul className="mt-2.5 flex flex-wrap gap-1.5" aria-hidden>
          {w.stages.map((s) => (
            <StageChip key={s.stage} stage={s} />
          ))}
        </ul>
      ) : w.kind === "study" ? (
        <p className="mt-2 text-xs text-muted">
          Results are shown straight away (no blind stages).
        </p>
      ) : null}

      <div className="flex-1" aria-hidden />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line pt-3 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <GitBranch className="size-3.5" aria-hidden />
          {decisions}
        </span>
        <time
          dateTime={new Date(w.updated_at * 1000).toISOString()}
          title={dateTime(w.updated_at)}
          className="tabular"
        >
          {updated}
        </time>
      </div>
      <span id={`${id}-details`} className="sr-only">
        {details}
      </span>
    </article>
  );
}

/** Arrow keys, Home and End move focus between the cards of the list. */
function moveFocus(e: KeyboardEvent<HTMLUListElement>) {
  const keys = ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"];
  if (!keys.includes(e.key)) return;
  const cards = Array.from(e.currentTarget.querySelectorAll<HTMLAnchorElement>("a[data-card]"));
  const i = cards.findIndex((c) => c === document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const next =
    e.key === "Home"
      ? 0
      : e.key === "End"
        ? cards.length - 1
        : e.key === "ArrowDown" || e.key === "ArrowRight"
          ? Math.min(cards.length - 1, i + 1)
          : Math.max(0, i - 1);
  cards[next]?.focus();
}

export function Recent({
  workspaces,
  loading,
  error,
  onRetry,
}: {
  workspaces: WorkspaceSummary[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const now = useNow(60_000);
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!workspaces || !q) return workspaces;
    return workspaces.filter((w) => `${w.title} ${w.file_name ?? ""}`.toLowerCase().includes(q));
  }, [workspaces, filter]);

  return (
    <section aria-labelledby="recent-title">
      <SectionTitle
        id="recent-title"
        hint="Studio sessions and analysed studies on this computer, the most recently changed first."
        actions={
          workspaces && workspaces.length > FILTER_FROM ? (
            <div className="relative w-56">
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint"
                aria-hidden
              />
              <Input
                aria-label="Filter recent workspaces"
                placeholder="Filter by title or file"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-8"
              />
            </div>
          ) : workspaces?.length ? (
            <span className="text-xs text-muted tabular">
              {plural(workspaces.length, "workspace")}
            </span>
          ) : null
        }
      >
        Recent
      </SectionTitle>

      {error && !workspaces ? (
        <ErrorPanel
          error={error}
          title="The list of recent workspaces could not be read"
          onRetry={onRetry}
        />
      ) : loading && !workspaces ? (
        <div className="grid gap-3 md:grid-cols-2" role="status">
          <span className="sr-only">Loading recent workspaces…</span>
          {[0, 1].map((i) => (
            <div
              key={i}
              className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4"
            >
              <Skeleton className="h-5 w-3/5" />
              <Skeleton className="h-3.5 w-2/5" />
              <Skeleton className="h-6 w-4/5" />
            </div>
          ))}
        </div>
      ) : !workspaces?.length ? (
        <EmptyState icon={<FolderOpen />} title="Nothing opened yet">
          Open an RDML file or the demo study above. Every study you open is listed here, with where
          it stands and what is waiting for you.
        </EmptyState>
      ) : !shown?.length ? (
        <EmptyState compact icon={<Search />} title="No workspace matches this filter">
          Try part of the title or the file name.
        </EmptyState>
      ) : (
        <ul
          className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3"
          onKeyDown={moveFocus}
          aria-labelledby="recent-title"
        >
          {shown.map((w) => (
            <li key={w.key} className="min-w-0">
              <WorkspaceCard w={w} now={now} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

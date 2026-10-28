/**
 * The Run Review: one place for the person who reviews someone else's run. The headline genes,
 * the Evidence Ledger (what this study cannot tell you first), what to repeat and why with the
 * repeat plate to download and the Run Gate's lines per plate (`RepeatPlan.tsx`), the part not
 * built yet (and the section that shows it instead), every recorded sign-off, and the sign-off itself: accept,
 * repeat or discuss, with a comment and a name, kept in the decision log as the person's. qPilot
 * never passes or fails a run, so no outcome is drawn as a pass or a fail.
 */
import { ArrowRight, Info, RefreshCw } from "lucide-react";
import { useId, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "wouter";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { count, dateTime, relativeTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { SECTION, sectionPath, type SectionId, type SectionProps } from "@/shell/sections";
import {
  Badge,
  Button,
  ConclusionTag,
  ErrorPanel,
  Field,
  Hash,
  Input,
  LoadingBlock,
  Textarea,
} from "@/ui";
import {
  useRunReview,
  useSignOff,
  type EvidenceItem,
  type EvidenceView,
  type NotBuilt,
  type RunReviewView,
  type SignOff,
  type SignOffOutcome,
} from "./api";
import { FactLine } from "./FactLine";
import { RepeatBlocks } from "./RepeatPlan";
import { EVIDENCE } from "./words";

/** Sign-offs shown before "Show all". */
const RECENT = 3;

export function RunReview({
  workspace,
  workspaceKey,
  studyId,
}: {
  workspace: SectionProps["workspace"];
  workspaceKey: string;
  studyId: string;
}) {
  const review = useRunReview(workspaceKey, studyId);
  if (review.isPending) return <LoadingBlock label="Reading the Run Review" lines={6} />;
  if (review.error)
    return (
      <ErrorPanel
        error={review.error}
        title="The Run Review could not be read"
        onRetry={() => void review.refetch()}
      />
    );
  return <RunReviewBody view={review.data} workspace={workspace} workspaceKey={workspaceKey} />;
}

export function RunReviewBody({
  view,
  workspace,
  workspaceKey,
}: {
  view: RunReviewView;
  workspace: SectionProps["workspace"];
  workspaceKey: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <p className="text-[15px] leading-relaxed text-muted">
          <FactLine text={view.title} />
        </p>
        <p className="flex gap-2 rounded-lg border border-line bg-sunken px-3 py-2 text-[13px] leading-relaxed text-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <span>{view.purpose}</span>
        </p>
      </div>
      <Headline view={view} />
      <Ledger evidence={view.evidence} />
      <RepeatBlocks workspace={workspace} workspaceKey={workspaceKey} studyId={view.study_id} />
      {view.not_built.length ? <NotBuiltList items={view.not_built} workspace={workspace} /> : null}
      <SignOffs view={view} workspaceKey={workspaceKey} />
    </div>
  );
}

function Block({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="rounded-xl border border-line bg-surface p-4">
      <h3 id={id} className="text-[14px] font-semibold text-fg">
        {title}
      </h3>
      {hint ? <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{hint}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

// ---- headline genes --------------------------------------------------------------------------

function Headline({ view }: { view: RunReviewView }) {
  return (
    <Block title="Headline genes">
      {view.headline.length ? (
        <ul className="flex flex-col gap-2" aria-label="Headline genes">
          {view.headline.map((h) => (
            <li key={h.gene} className="flex gap-3 text-[13.5px] leading-relaxed">
              <ConclusionTag conclusion={h.conclusion} className="w-[4.75rem] shrink-0 pt-px" />
              <FactLine text={h.line} className="min-w-0 text-muted" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">This study names no headline genes.</p>
      )}
    </Block>
  );
}

// ---- the Evidence Ledger ---------------------------------------------------------------------

const SOURCE: Record<EvidenceView["source"], string> = {
  kept: "Kept when the study was analysed.",
  rebuilt: "Read again from the input file for this page; nothing was saved.",
  none: "",
};

function Ledger({ evidence }: { evidence: EvidenceView }) {
  const items = evidence.items ?? [];
  const cannot = items.filter((i) => i.cannot_tell);
  const rest = items.filter((i) => !i.cannot_tell);
  return (
    <Block title="Evidence Ledger" hint={evidence.available ? SOURCE[evidence.source] : undefined}>
      {!evidence.available ? (
        <p className="text-[13px] leading-relaxed text-muted">{evidence.note}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-[13.5px] leading-relaxed text-muted">
            {evidence.summary ? (
              <FactLine text={evidence.summary} lead="Evidence Ledger: " />
            ) : (
              evidence.rule
            )}
          </p>
          {cannot.length ? (
            <ItemGroup title="What this study cannot tell you" items={cannot} />
          ) : null}
          {rest.length ? <ItemGroup title="What it has, or does not need" items={rest} /> : null}
        </div>
      )}
    </Block>
  );
}

function ItemGroup({ title, items }: { title: string; items: EvidenceItem[] }) {
  const id = useId();
  return (
    <div>
      <h4 id={id} className="text-[12.5px] font-semibold text-fg">
        {title} <span className="font-normal text-muted">{count(items.length)}</span>
      </h4>
      <ul aria-labelledby={id} className="mt-1 flex flex-col divide-y divide-line">
        {items.map((i) => (
          <EvidenceRow key={i.id} item={i} />
        ))}
      </ul>
    </div>
  );
}

function EvidenceRow({ item: i }: { item: EvidenceItem }) {
  const status = EVIDENCE[i.status] ?? EVIDENCE.unknown;
  return (
    <li className="flex flex-col gap-1 py-2.5" data-evidence={i.id}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
        <span className="font-medium text-fg">{i.title}</span>
        <Badge tone={status.tone}>
          <span aria-hidden>{status.glyph}</span> {i.status_word}
        </Badge>
      </p>
      <p className="text-[13px] leading-relaxed text-muted">
        <FactLine text={i.line} lead={`${i.title}: ${i.status_word}. `} />
      </p>
      {i.miqe.length ? (
        <p className="text-[11.5px] text-muted">MIQE 2.0: {i.miqe.join(", ")}</p>
      ) : null}
    </li>
  );
}

// ---- not built yet ---------------------------------------------------------------------------

function NotBuiltList({
  items,
  workspace,
}: {
  items: NotBuilt[];
  workspace: SectionProps["workspace"];
}) {
  return (
    <Block title="Not on this page yet">
      <ul className="flex flex-col gap-2.5">
        {items.map((n) => {
          const section =
            n.section && n.section in SECTION ? SECTION[n.section as SectionId] : null;
          return (
            <li key={n.id} className="text-[13px] leading-relaxed">
              <p className="font-medium text-fg">{n.title}</p>
              <p className="text-muted">{n.reason}</p>
              {section && workspace ? (
                <Button asChild size="sm" variant="ghost" className="-ml-2 mt-0.5">
                  <Link href={sectionPath(workspace, section.id)}>
                    Open {section.label}
                    <ArrowRight aria-hidden />
                  </Link>
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Block>
  );
}

// ---- sign-offs -------------------------------------------------------------------------------

function SignOffs({ view, workspaceKey }: { view: RunReviewView; workspaceKey: string }) {
  const [all, setAll] = useState(false);
  const now = useNow(60_000);
  const newest = useMemo(() => [...view.sign_offs].sort((a, b) => b.seq - a.seq), [view]);
  const shown = all ? newest : newest.slice(0, RECENT);
  const labels = new Map(view.outcomes.map((o) => [o.id, o.label]));
  return (
    <Block
      title="Sign-offs"
      hint="Each sign-off is kept in the decision log with the reviewer's name and comment."
    >
      <div className="flex flex-col gap-4">
        {newest.length ? (
          <div className="flex flex-col gap-1.5">
            <ol className="flex flex-col gap-2" aria-label="Recorded sign-offs, newest first">
              {shown.map((s) => (
                <SignOffRow key={s.seq} sign={s} label={labels.get(s.outcome)} now={now} />
              ))}
            </ol>
            {newest.length > RECENT ? (
              <Button
                size="sm"
                variant="ghost"
                className="-ml-2 self-start"
                aria-expanded={all}
                onClick={() => setAll((v) => !v)}
              >
                {all ? "Show the newest only" : `Show all ${count(newest.length)} sign-offs`}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-[13px] text-muted">No one has signed off this run yet.</p>
        )}
        {view.can_sign_off ? (
          <SignOffForm view={view} workspaceKey={workspaceKey} />
        ) : (
          <p className="flex gap-2 rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2 text-[13px] leading-relaxed text-fg">
            <Info className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
            <span>{view.why_not}</span>
          </p>
        )}
      </div>
    </Block>
  );
}

function SignOffRow({
  sign: s,
  label,
  now,
}: {
  sign: SignOff;
  label: string | undefined;
  now: number;
}) {
  return (
    <li className="rounded-lg border border-line bg-bg px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
        <Badge tone="neutral">
          <span className="sr-only">Outcome: </span>
          {label ?? s.outcome_word}
        </Badge>
        <span className="font-medium text-fg [overflow-wrap:anywhere]">{s.reviewer}</span>
        <time className="text-muted" dateTime={s.at} title={relativeTime(s.at, now)}>
          {dateTime(s.at)}
        </time>
        <span className="text-[12px] text-muted">
          entry {count(s.seq)} <Hash value={s.hash} length={8} />
        </span>
      </p>
      <p className="mt-1 text-[13.5px] leading-relaxed text-fg [overflow-wrap:anywhere]">
        “{s.comment}”
      </p>
    </li>
  );
}

function SignOffForm({ view, workspaceKey }: { view: RunReviewView; workspaceKey: string }) {
  const id = useId();
  const [outcome, setOutcome] = useState<SignOffOutcome | null>(null);
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("");
  const sign = useSignOff(workspaceKey, view.study_id, () => {
    setComment("");
    setOutcome(null);
  });
  const ready = Boolean(outcome && comment.trim() && reviewer.trim());
  const busy = sign.isPending;
  const error = sign.error;
  const stale = error instanceof ApiError && error.stale;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ready || !outcome || busy) return;
    sign.mutate({
      outcome,
      comment: comment.trim(),
      reviewer: reviewer.trim(),
      head: view.head,
    });
  };

  return (
    <form
      onSubmit={submit}
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-3.5 border-t border-line pt-4"
    >
      <h4 id={`${id}-title`} className="text-[13.5px] font-semibold text-fg">
        Sign off
      </h4>
      <fieldset className="min-w-0" disabled={busy}>
        <legend className="mb-1.5 text-[13px] font-medium text-fg">Outcome</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {view.outcomes.map((o) => {
            const selected = outcome === o.id;
            return (
              <label
                key={o.id}
                className={cn(
                  "flex cursor-pointer gap-2 rounded-lg border p-2.5 transition-colors duration-150",
                  selected
                    ? "border-accent bg-accent-soft/40"
                    : "border-line hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name={`${id}-outcome`}
                  value={o.id}
                  checked={selected}
                  onChange={() => setOutcome(o.id)}
                  aria-labelledby={`${id}-${o.id}`}
                  aria-describedby={`${id}-${o.id}-meaning`}
                  className="mt-0.5 shrink-0 accent-[var(--accent)]"
                />
                <span className="min-w-0">
                  <span id={`${id}-${o.id}`} className="block text-[13px] font-medium text-fg">
                    {o.label}
                  </span>
                  <span
                    id={`${id}-${o.id}-meaning`}
                    className="mt-0.5 block text-[12px] leading-snug text-muted"
                  >
                    {o.meaning}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <Field
        label="Comment"
        hint="Why you chose it: what you looked at, and what to repeat or talk about."
      >
        <Textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          maxLength={view.max_comment}
          showCount
          rows={3}
          required
          disabled={busy}
        />
      </Field>
      <Field
        label="Your name"
        hint="Kept in the decision log with the comment; the log is a shared record."
        className="max-w-sm"
      >
        <Input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          maxLength={view.max_reviewer}
          autoComplete="name"
          required
          disabled={busy}
        />
      </Field>
      {stale ? (
        <p
          role="status"
          className="flex gap-2 rounded-lg border border-info/30 bg-info-soft/50 px-3 py-2 text-[13px] leading-relaxed text-fg"
        >
          <RefreshCw className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <span>{error.message}</span>
        </p>
      ) : error ? (
        <ErrorPanel compact error={error} title="The sign-off was not recorded" />
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Button type="submit" variant="primary" disabled={!ready} loading={busy}>
          Sign off
        </Button>
        <span className="text-[12px] text-muted">
          {ready
            ? "Recorded as yours; it changes no result and no Decision Card."
            : "Choose an outcome, write a comment and your name to sign off."}
        </span>
      </div>
    </form>
  );
}

/**
 * The Decision Cards: the choices that can change a conclusion, ranked by impact. A person picks
 * an option, says why, and decides; an agent's request waits here for Approve or Turn down.
 * `j`/`k` move between cards, `Enter` goes to the reason, `⌘Enter` decides.
 */
import { AlertTriangle, Bot, Check, ChevronDown, CircleCheck, Sparkles, Undo2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, type Schemas } from "@/api/client";
import { useJob } from "@/api/jobs";
import { CALLS, Glyph, type CallKey } from "@/charts";
import { cn } from "@/lib/cn";
import { count, fold } from "@/lib/format";
import { MOD, useHotkeys } from "@/lib/hooks";
import { Badge, Button, Card, Kbd, Textarea, toast } from "@/ui";
import {
  useCardWrite,
  useExplain,
  useModelAnswers,
  type CardView,
  type CardsView,
  type DecisionDone,
} from "./api";
import { FactSource, FactText } from "./FactText";

const MAX_REASON = 500;

/** Requests waiting for a person first, then open cards by rank, then decided ones. */
export function cardOrder(cards: readonly CardView[]): CardView[] {
  const weight = (c: CardView) =>
    c.pending.length || c.card.status === "pending_human" ? 0 : c.card.status === "open" ? 1 : 2;
  return [...cards].sort((a, b) => weight(a) - weight(b) || a.card.rank - b.card.rank);
}

function doneToast(title: string, done: DecisionDone) {
  const s = done.outcome.status;
  if (s === "applied") toast.success(title, { description: done.message, duration: 10_000 });
  else if (s === "pending_human")
    toast.info(title, { description: done.message, duration: 10_000 });
  else if (s === "stale")
    toast.warning("Something was decided since you loaded this", {
      description: "Here is the current state; decide again if you still want to.",
    });
  else toast.error(title, { description: done.message });
}

function errorToast(e: unknown) {
  if (e instanceof ApiError && e.stale)
    toast.warning("Something was decided since you loaded this (another tab or an agent)", {
      description: "Here is the current state.",
    });
  else toast.error(e instanceof Error ? e.message : "The decision could not be saved.");
}

export function DecisionCards({
  view,
  workspaceKey,
  studyId,
  focusCard,
  nextAction,
  className,
}: {
  view: CardsView;
  /** The next-step banner's action label when it points here ("Decide"): lands on the first open card's reason. */
  nextAction?: string | null;
  workspaceKey: string;
  studyId: string;
  /** A card to scroll to and focus (deep link `results/card/<id>`). */
  focusCard?: string | null;
  className?: string;
}) {
  const ordered = useMemo(() => cardOrder(view.cards), [view.cards]);
  const firstOpen = ordered.findIndex((c) => c.card.status === "open" || c.pending.length > 0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const [focus, setFocus] = useState(-1);
  const modelAnswers = useModelAnswers();
  useEffect(() => {
    if (!focusCard) return;
    const i = ordered.findIndex((c) => c.card.id === focusCard);
    const el = refs.current[i];
    if (i < 0 || !el) return;
    el.scrollIntoView({ block: "center" });
    el.focus({ preventScroll: true });
  }, [focusCard, ordered]);
  const move = (d: number) => {
    const next = Math.max(0, Math.min(ordered.length - 1, focus + d));
    setFocus(next);
    refs.current[next]?.focus();
    refs.current[next]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  useHotkeys({ j: () => move(1), k: () => move(-1) }, ordered.length > 0);

  return (
    <section aria-labelledby="cards-title" className={className}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="cards-title" className="text-base font-semibold tracking-tight text-fg">
            Decision Cards
          </h2>
          <p className="mt-0.5 text-[13px] text-muted">
            {view.counter}
            {view.pending_requests
              ? ` · ${count(view.pending_requests)} agent request${view.pending_requests > 1 ? "s" : ""} waiting for you`
              : ""}
          </p>
        </div>
        <p className="hidden text-[12px] text-faint xl:block">
          <Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>{MOD}</Kbd>
          <Kbd>Enter</Kbd> decide
        </p>
      </div>
      {ordered.length === 0 ? (
        <Card className="p-4 text-[13px] text-muted">
          This study has no analysis choices to decide.
        </Card>
      ) : (
        <ol className="space-y-3">
          {ordered.map((c, i) => (
            <li key={c.card.id}>
              {/* a new state from the server (another tab, an agent) starts the form afresh */}
              <DecisionCardItem
                key={`${c.card.status}:${c.card.decision ?? ""}:${c.pending.map((p) => p.seq).join(",")}`}
                ref={(el) => {
                  refs.current[i] = el;
                }}
                view={c}
                head={view.head}
                workspaceKey={workspaceKey}
                studyId={studyId}
                modelAnswers={modelAnswers}
                expanded={c.card.id === focusCard}
                actionLabel={nextAction && i === firstOpen ? nextAction : undefined}
                onFocus={() => setFocus(i)}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const STATUS_BADGE: Record<
  CardView["card"]["status"],
  { label: string; tone: "accent" | "ok" | "warn" | "neutral" }
> = {
  open: { label: "To decide", tone: "accent" },
  decided: { label: "Decided", tone: "ok" },
  auto_decided: { label: "Decided automatically", tone: "neutral" },
  pending_human: { label: "Agent request", tone: "warn" },
};

type Explanation = Schemas["Explanation"];

function DecisionCardItem({
  ref,
  view,
  head,
  workspaceKey,
  studyId,
  modelAnswers,
  expanded,
  actionLabel,
  onFocus,
}: {
  ref: (el: HTMLElement | null) => void;
  /** A focus-target name for this card's reason box (the next-step banner's action). */
  actionLabel?: string;
  view: CardView;
  head: string;
  workspaceKey: string;
  studyId: string;
  modelAnswers: boolean;
  /** Start expanded even when decided (a deep link to this card). */
  expanded?: boolean;
  onFocus: () => void;
}) {
  const card = view.card;
  const request = view.pending[view.pending.length - 1] ?? null;
  const done = card.status === "decided" || card.status === "auto_decided";
  const pending = Boolean(request) || card.status === "pending_human";
  const [open, setOpen] = useState(!done || expanded || pending);
  const [undoing, setUndoing] = useState(false);
  /** A decided card reopened to choose another option (a new chain entry). */
  const [changing, setChanging] = useState(false);
  const chosen = view.options.find((o) => o.chosen)?.id ?? card.decision ?? card.recommended;
  const [option, setOption] = useState(request?.option ?? chosen);
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();
  const write = useCardWrite(workspaceKey, studyId);
  const explain = useExplain(studyId);
  const job = useJob(jobId);
  const explanation = job.data?.status === "done" ? (job.data.result as Explanation | null) : null;

  const labels = useMemo(() => new Map(view.options.map((o) => [o.id, o.label])), [view.options]);
  const keyIds = new Set(
    [card.recommended, chosen, request?.option, option].filter(Boolean) as string[],
  );
  const many = view.options.length > 5;
  const visible = many && !showAll ? view.options.filter((o) => keyIds.has(o.id)) : view.options;
  const flips = view.needs_human;

  const run = (kind: "decide" | "reject" | "undo", opt?: string) => {
    const r = reason.trim();
    const call =
      kind === "decide"
        ? { kind, card: card.id, option: opt!, reason: r, head }
        : kind === "undo"
          ? { kind, card: card.id, reason: r, head }
          : { kind, card: card.id, reason: r, head, option: request?.option ?? null };
    write.mutate(call, {
      onSuccess: (done) => {
        doneToast(view.title, done);
        setReason("");
      },
      onError: errorToast,
    });
  };
  const canSubmit = reason.trim().length > 0 && !write.isPending;
  const onReasonKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) {
      e.preventDefault();
      if (undoing) run("undo");
      else run("decide", pending ? (request?.option ?? option) : option);
    }
  };

  return (
    <Card
      as="article"
      ref={ref as (el: HTMLDivElement | null) => void}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-action={`card:${card.id}`}
      onFocus={onFocus}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) {
          e.preventDefault();
          setOpen(true);
          const el = e.currentTarget;
          // the reason box when there is one, else the card's first action (Change, Undo)
          requestAnimationFrame(() => {
            const target =
              reasonRef.current ?? el.querySelector<HTMLElement>("[data-card-body] button");
            target?.focus();
          });
        }
      }}
      className={cn(
        "outline-none focus-visible:ring-2 focus-visible:ring-focus",
        pending && "border-warn",
        card.status === "open" && flips && "border-accent/50",
      )}
    >
      <div className="flex items-start gap-3 p-4 pb-3">
        <span className="tabular mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-sunken text-[12px] font-semibold text-muted">
          {card.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">
              {view.title}
            </h3>
            <Badge tone={pending ? "warn" : STATUS_BADGE[card.status].tone}>
              {pending ? "Agent request" : STATUS_BADGE[card.status].label}
            </Badge>
          </div>
          <p
            className={cn(
              "mt-1 flex items-start gap-1.5 text-[13px]",
              flips ? "text-fg" : "text-muted",
            )}
          >
            {flips ? (
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
            ) : (
              <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
            )}
            <FactText text={view.impact} />
          </p>
          {(done || pending) && <p className="mt-1 text-[13px] text-muted">{view.status_line}</p>}
        </div>
        {done && !pending && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            icon={
              <ChevronDown
                className={cn("size-4 transition-transform duration-150", open && "rotate-180")}
                aria-hidden
              />
            }
          >
            {open ? "Hide" : "Show"}
          </Button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="space-y-3 px-4 pb-4" data-card-body>
              {request && (
                <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg">
                  <Bot className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                  <span>
                    An agent asked for <strong>{request.option_label}</strong>
                    {request.reason ? <> because: “{request.reason}”</> : null}. It is not applied
                    until a person approves it.
                  </span>
                </div>
              )}

              <fieldset className="min-w-0">
                <legend className="mb-1.5 text-[12px] font-medium text-muted">
                  Options
                  {view.genes.length ? ` · what each gives for ${view.genes.join(", ")}` : ""}
                </legend>
                <div
                  role="radiogroup"
                  aria-label={`${view.title}: options`}
                  className="space-y-1.5"
                >
                  {visible.map((o) => {
                    const selected = o.id === option;
                    const locked = (done && !changing) || pending;
                    return (
                      <label
                        key={o.id}
                        className={cn(
                          "flex flex-col gap-1.5 rounded-lg border p-2.5 transition-colors duration-150",
                          selected ? "border-accent bg-accent-soft/40" : "border-line",
                          locked ? "cursor-default" : "cursor-pointer hover:border-line-strong",
                        )}
                      >
                        <span className="flex items-start gap-2">
                          <input
                            type="radio"
                            name={`opt-${card.id}`}
                            value={o.id}
                            checked={selected}
                            disabled={locked}
                            onChange={() => setOption(o.id)}
                            className="mt-0.5 accent-[var(--accent)]"
                          />
                          <span className="min-w-0 flex-1 text-[13px] text-fg">{o.label}</span>
                          <span className="flex shrink-0 flex-wrap justify-end gap-1">
                            {o.recommended && <Badge tone="accent">Recommended</Badge>}
                            {o.chosen && (
                              <Badge tone="ok" icon={<Check className="size-3" aria-hidden />}>
                                In use
                              </Badge>
                            )}
                            {o.requested && <Badge tone="warn">Agent asked</Badge>}
                            {o.not_recommended && (
                              <Badge tone="danger">Not recommended (MIQE)</Badge>
                            )}
                          </span>
                        </span>
                        {o.effects.length > 0 && (
                          <span className="flex flex-wrap gap-x-3 gap-y-1 pl-6">
                            {o.effects.map((e) => {
                              const c =
                                (e.conclusion as CallKey) in CALLS
                                  ? (e.conclusion as CallKey)
                                  : "none";
                              return (
                                <span
                                  key={e.gene}
                                  className={cn(
                                    "tabular inline-flex items-center gap-1 text-[12px]",
                                    e.changes_call ? "font-semibold text-fg" : "text-muted",
                                  )}
                                >
                                  <span>{e.gene}</span>
                                  <span>{fold(e.fc)}</span>
                                  <Glyph mark={CALLS[c]} size={9} />
                                  <span className={e.changes_call ? "" : "sr-only"}>
                                    {CALLS[c].short}
                                  </span>
                                  {e.changes_call && (
                                    <span className="font-normal text-warn">(changes)</span>
                                  )}
                                </span>
                              );
                            })}
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
                {many && (
                  <button
                    type="button"
                    onClick={() => setShowAll((v) => !v)}
                    className="mt-1.5 text-[12px] font-medium text-accent hover:underline"
                  >
                    {showAll
                      ? "Show fewer options"
                      : `Show all ${count(view.options.length)} options`}
                  </button>
                )}
              </fieldset>

              <details className="group rounded-lg bg-sunken/60 px-3 py-2 text-[13px]">
                <summary className="cursor-pointer font-medium text-muted select-none hover:text-fg">
                  How this was worked out
                </summary>
                <p className="mt-1.5 leading-relaxed text-muted">
                  <FactText text={view.explanation} />
                </p>
              </details>

              {(!done || undoing || changing || pending) && (
                <div className="space-y-2">
                  <label
                    htmlFor={`reason-${card.id}`}
                    className="block text-[12px] font-medium text-muted"
                  >
                    {pending
                      ? "Your reason (required, for either answer)"
                      : undoing
                        ? "Why undo it? (required)"
                        : "Why this option? (required; it goes into the Analysis Record)"}
                  </label>
                  <Textarea
                    id={`reason-${card.id}`}
                    ref={reasonRef}
                    data-action={actionLabel}
                    rows={2}
                    maxLength={MAX_REASON}
                    showCount
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    onKeyDown={onReasonKey}
                    placeholder={
                      pending
                        ? "e.g. the agent's reading matches our protocol"
                        : "e.g. prespecified in our protocol before we saw the data"
                    }
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    {pending && request ? (
                      <>
                        <Button
                          size="sm"
                          disabled={!canSubmit}
                          loading={write.isPending}
                          onClick={() => run("decide", request.option)}
                        >
                          Approve: {request.option_label}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!canSubmit}
                          onClick={() => run("reject")}
                        >
                          Turn down
                        </Button>
                      </>
                    ) : undoing ? (
                      <>
                        <Button
                          size="sm"
                          disabled={!canSubmit}
                          loading={write.isPending}
                          icon={<Undo2 className="size-4" aria-hidden />}
                          onClick={() => run("undo")}
                        >
                          Undo{view.undo_label ? `: back to ${view.undo_label}` : ""}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setUndoing(false)}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          size="sm"
                          disabled={!canSubmit}
                          loading={write.isPending}
                          onClick={() => run("decide", option)}
                        >
                          Decide: {labels.get(option)}
                        </Button>
                        {changing && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setChanging(false);
                              setOption(chosen);
                            }}
                          >
                            Cancel
                          </Button>
                        )}
                      </>
                    )}
                    <span className="text-[12px] text-faint">
                      <Kbd>{MOD}</Kbd>
                      <Kbd>Enter</Kbd>
                    </span>
                  </div>
                </div>
              )}

              {done && !undoing && !changing && !pending && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setChanging(true);
                      requestAnimationFrame(() => reasonRef.current?.focus());
                    }}
                  >
                    Change the decision
                  </Button>
                  {view.undo_option && (
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Undo2 className="size-4" aria-hidden />}
                      onClick={() => {
                        setUndoing(true);
                        requestAnimationFrame(() => reasonRef.current?.focus());
                      }}
                    >
                      Undo{view.undo_label ? `: back to ${view.undo_label}` : ""}
                    </Button>
                  )}
                  {!view.undo_option && (
                    <p className="w-full text-[12px] text-muted">
                      Nothing to undo here: to change it, decide another option (a new entry in the
                      record).
                    </p>
                  )}
                </div>
              )}

              {modelAnswers && (
                <div className="border-t border-line pt-3">
                  {explanation ? (
                    <div className="space-y-1 text-[13px]">
                      <p className="leading-relaxed text-fg">
                        <FactText text={explanation.text} />
                      </p>
                      <FactSource text={explanation.text} />
                      {explanation.note && (
                        <p className="text-[12px] text-muted">{explanation.note}</p>
                      )}
                    </div>
                  ) : job.data?.status === "failed" ? (
                    <p className="text-[13px] text-muted">
                      {job.data.error?.message ?? "The model did not answer."}
                    </p>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Sparkles className="size-4" aria-hidden />}
                      loading={explain.isPending || (Boolean(jobId) && job.data?.status !== "done")}
                      onClick={() =>
                        explain.mutate(card.id, {
                          onSuccess: (r) => setJobId(r.job.id),
                          onError: (e) =>
                            toast.error(
                              e instanceof Error ? e.message : "The model did not answer.",
                            ),
                        })
                      }
                    >
                      Explain with the model
                    </Button>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

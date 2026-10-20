/**
 * The Decision Cards: the choices that can change a conclusion, ranked by impact. A person picks
 * an option, says why, and decides; an agent's request waits here for Approve or Turn down.
 * `j`/`k` move between cards, `Enter` goes to the reason, `⌘Enter` decides.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bot, Check, ChevronDown, CircleCheck, Sparkles, Undo2 } from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError, unwrap } from "@/api/client";
import { CALLS, Glyph, type CallKey } from "@/charts";
import { cn } from "@/lib/cn";
import { count, fold } from "@/lib/format";
import { MOD, useHotkeys } from "@/lib/hooks";
import { Badge, Button, Card, Kbd, Textarea, toast } from "@/ui";
import { useCardAction, type CardView, type CardsView, type DecideOutcome } from "./api";

const MAX_REASON = 500;

function asCall(c: string | undefined): CallKey {
  return c === "up" || c === "down" ? c : "none";
}

/** Pending requests first, then open cards by rank, then decided ones. */
export function cardOrder(cards: readonly CardView[]): CardView[] {
  const weight = (c: CardView) => (c.status === "pending_human" ? 0 : c.status === "open" ? 1 : 2);
  return [...cards].sort((a, b) => weight(a) - weight(b) || a.rank - b.rank);
}

function useModelAnswers(): boolean {
  const q = useQuery({
    queryKey: ["model"],
    queryFn: () => unwrap(api.GET("/api/model")),
    staleTime: 60_000,
  });
  return Boolean(q.data?.answers);
}

function outcomeToast(card: CardView, out: DecideOutcome, label: string) {
  if (out.status === "applied") toast.success(`${card.title}: ${label}`, { description: "Decided and added to the record." });
  else if (out.status === "pending_human") toast.info(`${card.title}: waiting for a person`, { description: out.reason ?? undefined });
  else if (out.status === "stale")
    toast.warning("Something was decided since you loaded this", { description: "Here is the current state; decide again if you still want to." });
  else toast.error(`${card.title}: not applied`, { description: out.reason ?? undefined });
}

function errorToast(e: unknown) {
  if (e instanceof ApiError && e.stale)
    toast.warning("Something was decided since you loaded this (another tab or an agent)", { description: "Here is the current state." });
  else toast.error(e instanceof Error ? e.message : "The decision could not be saved.");
}

export function DecisionCards({
  view,
  workspaceKey,
  studyId,
  headline,
  className,
}: {
  view: CardsView;
  workspaceKey: string;
  studyId: string;
  headline: string[];
  className?: string;
}) {
  const ordered = useMemo(() => cardOrder(view.cards), [view.cards]);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const [focus, setFocus] = useState(0);
  const modelAnswers = useModelAnswers();
  const move = (d: number) => {
    const next = Math.max(0, Math.min(ordered.length - 1, focus + d));
    setFocus(next);
    refs.current[next]?.focus();
    refs.current[next]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  useHotkeys({ j: () => move(1), k: () => move(-1) }, ordered.length > 0);

  const decided = view.cards.filter((c) => c.status === "decided" || c.status === "auto_decided").length;
  const waiting = view.cards.filter((c) => c.status === "pending_human").length;
  return (
    <section aria-labelledby="cards-title" className={className}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="cards-title" className="text-base font-semibold tracking-tight text-fg">
            Decision Cards
          </h2>
          <p className="mt-0.5 text-[13px] text-muted">
            {count(decided)} of {count(view.cards.length)} decided
            {waiting ? ` · ${count(waiting)} agent request${waiting > 1 ? "s" : ""} waiting for you` : ""}. Choices that can change a
            conclusion are always a person&apos;s.
          </p>
        </div>
        <p className="hidden text-[12px] text-faint xl:block">
          <Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>{MOD}</Kbd>
          <Kbd>Enter</Kbd> decide
        </p>
      </div>
      {ordered.length === 0 ? (
        <Card className="p-4 text-[13px] text-muted">This study has no choices to decide: no analysis choice changes a conclusion.</Card>
      ) : (
        <ol className="space-y-3">
          {ordered.map((c, i) => (
            <li key={c.id}>
              {/* a new state from the server (another tab, an agent) starts the form afresh */}
              <DecisionCardItem
                key={`${c.status}:${c.decision ?? ""}:${c.pending_option ?? ""}`}
                ref={(el) => {
                  refs.current[i] = el;
                }}
                card={c}
                head={view.head}
                headline={headline}
                workspaceKey={workspaceKey}
                studyId={studyId}
                modelAnswers={modelAnswers}
                onFocus={() => setFocus(i)}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const STATUS_BADGE: Record<CardView["status"], { label: string; tone: "accent" | "ok" | "warn" | "neutral" }> = {
  open: { label: "To decide", tone: "accent" },
  decided: { label: "Decided", tone: "ok" },
  auto_decided: { label: "Decided automatically", tone: "neutral" },
  pending_human: { label: "Agent request", tone: "warn" },
};

function DecisionCardItem({
  ref,
  card,
  head,
  headline,
  workspaceKey,
  studyId,
  modelAnswers,
  onFocus,
}: {
  ref: (el: HTMLElement | null) => void;
  card: CardView;
  head: string | null;
  headline: string[];
  workspaceKey: string;
  studyId: string;
  modelAnswers: boolean;
  onFocus: () => void;
}) {
  const done = card.status === "decided" || card.status === "auto_decided";
  const pending = card.status === "pending_human";
  const [open, setOpen] = useState(!done);
  const [undoing, setUndoing] = useState(false);
  const initial = pending ? (card.pending_option ?? card.recommended) : (card.decision ?? card.recommended);
  const [option, setOption] = useState(initial);
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [explanation, setExplanation] = useState<{ text: string; by?: string } | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();
  const action = useCardAction(workspaceKey, studyId);

  const labels = useMemo(() => new Map(card.options.map((o) => [o.id, o.label])), [card.options]);
  const genes = useMemo(() => {
    const first = card.options[0]?.per_gene ?? {};
    const names = Object.keys(first);
    return [...headline.filter((g) => names.includes(g)), ...names.filter((g) => !headline.includes(g))];
  }, [card.options, headline]);
  const base = card.options.find((o) => o.id === (card.decision ?? card.recommended)) ?? card.options[0];
  const notRecommended = new Set(Array.isArray(card.evidence?.not_recommended) ? (card.evidence.not_recommended as string[]) : []);
  const keyOptions = new Set([card.recommended, card.decision, card.pending_option, option].filter(Boolean) as string[]);
  const many = card.options.length > 5;
  const visible = many && !showAll ? card.options.filter((o) => keyOptions.has(o.id)) : card.options;
  const flips = Boolean(card.impact?.flips);

  const run = (kind: "decide" | "reject" | "undo", opt?: string) => {
    const label = labels.get(opt ?? "") ?? opt ?? "";
    action.mutate(
      { card: card.id, action: kind, option: opt, reason: reason.trim(), expected_head: head },
      {
        onSuccess: (out) => {
          if (kind === "reject") toast.success(`${card.title}: the agent's request was turned down`);
          else outcomeToast(card, out, kind === "undo" ? `undone, back to ${label}` : label);
          setReason("");
        },
        onError: errorToast,
      },
    );
  };
  const explain = () =>
    action.mutate(
      { card: card.id, action: "explain" },
      {
        onSuccess: (out) => setExplanation({ text: out.text ?? "", by: out.written_by }),
        onError: (e) => toast.error(e instanceof Error ? e.message : "The model did not answer."),
      },
    );
  const canSubmit = reason.trim().length > 0 && !action.isPending;
  const onReasonKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) {
      e.preventDefault();
      if (undoing && card.undo_option) run("undo", card.undo_option);
      else run("decide", option);
    }
  };

  return (
    <Card
      as="article"
      ref={ref as (el: HTMLDivElement | null) => void}
      tabIndex={-1}
      aria-labelledby={titleId}
      onFocus={onFocus}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) {
          e.preventDefault();
          setOpen(true);
          requestAnimationFrame(() => reasonRef.current?.focus());
        }
      }}
      className={cn("outline-none focus-visible:ring-2 focus-visible:ring-focus", pending && "border-warn", card.status === "open" && flips && "border-accent/50")}
    >
      <div className="flex items-start gap-3 p-4 pb-3">
        <span className="tabular mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-sunken text-[12px] font-semibold text-muted">{card.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">
              {card.title}
            </h3>
            <Badge tone={STATUS_BADGE[card.status].tone}>{STATUS_BADGE[card.status].label}</Badge>
          </div>
          <p className={cn("mt-1 flex items-start gap-1.5 text-[13px]", flips ? "text-fg" : "text-muted")}>
            {flips ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden /> : <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />}
            <span>{card.impact_text}</span>
          </p>
          {(done || pending) && <p className="mt-1 text-[13px] text-muted">{card.status_line}</p>}
        </div>
        {done && (
          <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} icon={<ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />}>
            {open ? "Hide" : "Show"}
          </Button>
        )}
      </div>

      {open && (
        <div className="space-y-3 px-4 pb-4">
          {card.explanation_text && <p className="text-[13px] leading-relaxed text-muted">{card.explanation_text}</p>}

          {pending && (
            <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg">
              <Bot className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
              <span>
                An agent asked for <strong>{labels.get(card.pending_option ?? "") ?? "another option"}</strong>. It is not applied until a person
                approves it.
              </span>
            </div>
          )}

          <fieldset className="min-w-0">
            <legend className="mb-1.5 text-[12px] font-medium text-muted">
              Options{genes.length ? ` · what each gives for ${genes.join(", ")}` : ""}
            </legend>
            <div role="radiogroup" aria-label={`${card.title}: options`} className="space-y-1.5">
              {visible.map((o) => {
                const chosen = o.id === option;
                return (
                  <label
                    key={o.id}
                    className={cn(
                      "flex cursor-pointer flex-col gap-1.5 rounded-lg border p-2.5 transition-colors duration-150",
                      chosen ? "border-accent bg-accent-soft/40" : "border-line hover:border-line-strong",
                      done && !undoing && "cursor-default",
                    )}
                  >
                    <span className="flex items-start gap-2">
                      <input
                        type="radio"
                        name={`opt-${card.id}`}
                        value={o.id}
                        checked={chosen}
                        disabled={done && !undoing}
                        onChange={() => setOption(o.id)}
                        className="mt-0.5 accent-[var(--accent)]"
                      />
                      <span className="min-w-0 flex-1 text-[13px] text-fg">{o.label}</span>
                      <span className="flex shrink-0 flex-wrap justify-end gap-1">
                        {o.id === card.recommended && <Badge tone="accent">Recommended</Badge>}
                        {o.id === card.decision && <Badge tone="ok" icon={<Check className="size-3" aria-hidden />}>In use</Badge>}
                        {o.id === card.pending_option && <Badge tone="warn">Agent asked</Badge>}
                        {notRecommended.has(o.id) && <Badge tone="danger">Not recommended (MIQE)</Badge>}
                      </span>
                    </span>
                    {genes.length > 0 && (
                      <span className="flex flex-wrap gap-x-3 gap-y-1 pl-6">
                        {genes.map((g) => {
                          const r = o.per_gene[g];
                          if (!r) return null;
                          const c = asCall(r.conclusion);
                          const changes = base && base.id !== o.id && base.per_gene[g] && base.per_gene[g].conclusion !== r.conclusion;
                          return (
                            <span key={g} className={cn("tabular inline-flex items-center gap-1 text-[12px]", changes ? "font-semibold text-fg" : "text-muted")}>
                              <span>{g}</span>
                              <span>{fold(r.fc)}</span>
                              <Glyph mark={CALLS[c]} size={9} />
                              <span className={changes ? "" : "sr-only"}>{CALLS[c].short}</span>
                              {changes && <span className="text-warn">changes</span>}
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
              <button type="button" onClick={() => setShowAll((v) => !v)} className="mt-1.5 text-[12px] font-medium text-accent hover:underline">
                {showAll ? "Show fewer options" : `Show all ${count(card.options.length)} options`}
              </button>
            )}
          </fieldset>

          {(!done || undoing) && (
            <div className="space-y-2">
              <label htmlFor={`reason-${card.id}`} className="block text-[12px] font-medium text-muted">
                {pending ? "Your reason (required, for either answer)" : undoing ? "Why undo it? (required)" : "Why this option? (required; it goes into the Analysis Record)"}
              </label>
              <Textarea
                id={`reason-${card.id}`}
                ref={reasonRef}
                rows={2}
                maxLength={MAX_REASON}
                showCount
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={onReasonKey}
                placeholder={pending ? "e.g. the agent's reading matches our protocol" : "e.g. prespecified in our protocol before we saw the data"}
              />
              <div className="flex flex-wrap items-center gap-2">
                {pending ? (
                  <>
                    <Button size="sm" disabled={!canSubmit} loading={action.isPending} onClick={() => run("decide", card.pending_option ?? option)}>
                      Approve: {labels.get(card.pending_option ?? option)}
                    </Button>
                    <Button size="sm" variant="secondary" disabled={!canSubmit} onClick={() => run("reject")}>
                      Turn down
                    </Button>
                  </>
                ) : undoing && card.undo_option ? (
                  <>
                    <Button size="sm" disabled={!canSubmit} loading={action.isPending} icon={<Undo2 className="size-4" aria-hidden />} onClick={() => run("undo", card.undo_option!)}>
                      Undo: back to {labels.get(card.undo_option)}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setUndoing(false)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button size="sm" disabled={!canSubmit} loading={action.isPending} onClick={() => run("decide", option)}>
                    Decide: {labels.get(option)}
                  </Button>
                )}
                <span className="text-[12px] text-faint">
                  <Kbd>{MOD}</Kbd>
                  <Kbd>Enter</Kbd>
                </span>
              </div>
            </div>
          )}

          {done && !undoing && (
            <div className="flex flex-wrap gap-2">
              {card.undo_option && (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Undo2 className="size-4" aria-hidden />}
                  onClick={() => {
                    setUndoing(true);
                    setOption(card.undo_option!);
                    requestAnimationFrame(() => reasonRef.current?.focus());
                  }}
                >
                  Undo
                </Button>
              )}
            </div>
          )}

          {modelAnswers && (
            <div className="border-t border-line pt-3">
              {explanation ? (
                <div className="space-y-1 text-[13px]">
                  <p className="leading-relaxed text-fg">{explanation.text}</p>
                  {explanation.by && <p className="text-[12px] text-faint">Written by {explanation.by}; every number in it is checked against the facts.</p>}
                </div>
              ) : (
                <Button size="sm" variant="ghost" icon={<Sparkles className="size-4" aria-hidden />} onClick={explain} loading={action.isPending && action.variables?.action === "explain"}>
                  Explain with the model
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

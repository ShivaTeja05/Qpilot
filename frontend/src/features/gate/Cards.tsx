/**
 * The `gate.rule` Decision Cards in the Decision Cards' visual language: the question, what it
 * changes, each option with its per-gene calls (the calls that change in bold), and how it was
 * worked out. In a Studio session a person decides them here: pick an option, say why, decide.
 * Leaving wells out (or putting them back) becomes curve exclusions in the session's record and
 * the study is analysed again; keeping every well is recorded. An agent's request (asked through
 * MCP) waits on its card for Approve or Turn down. Wells a person left out are listed after the
 * cards, with Put the wells back. A study analysed outside Studio is read-only: its wells are
 * left out by opening its file in Studio, and its calls are followed down to their wells in Trace.
 */
import { Bot, Check, CircleCheck, TriangleAlert, Undo2 } from "lucide-react";
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "wouter";
import { ApiError, type Schemas } from "@/api/client";
import { CALLS, Glyph, type CallKey } from "@/charts";
import { FactText } from "@/features/results/FactText";
import { cn } from "@/lib/cn";
import { dateTime, fold, plural } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { decidedBy } from "@/lib/vocab";
import { sectionPath } from "@/shell/sections";
import { Badge, Button, Card, KeyHint, Textarea, toast } from "@/ui";
import {
  useGateDecide,
  type Consequence,
  type Evaluation,
  type GateCard,
  type GateDecided,
  type GateRequest,
  type GateScope,
  type GateView,
} from "./api";
import { VerdictChip } from "./Pieces";
import { wellText, whereText } from "./words";

type Workspace = Schemas["WorkspaceView"];
type Decide = ReturnType<typeof useGateDecide>;

const MAX_REASON = 500;

const STATUS: Record<string, { label: string; tone: "accent" | "ok" | "warn" | "neutral" }> = {
  open: { label: "A person decides", tone: "accent" },
  decided: { label: "Decided", tone: "ok" },
  auto_decided: { label: "Decided automatically", tone: "neutral" },
  pending_human: { label: "Agent request", tone: "warn" },
};

function callOf(conclusion: string): CallKey {
  return (conclusion as CallKey) in CALLS ? (conclusion as CallKey) : "none";
}

function doneToast(title: string, done: GateDecided) {
  toast.success(title, { description: done.message, duration: 10_000 });
}

function errorToast(e: unknown) {
  if (e instanceof ApiError && e.stale)
    toast.warning("Something changed since you loaded this (another tab, a decision or an agent)", {
      description: "Here are the controls at the analysis in use now.",
    });
  else toast.error(e instanceof Error ? e.message : "The decision could not be saved.");
}

function requestWords(r: GateRequest): string {
  const n = r.wells.length;
  return `${r.option_label} (${plural(n, "well")} ${r.left_out ? "out" : "back in"})`;
}

/** The reason box and the buttons under it (decide, or approve / turn down a request). */
function DecideForm({
  cardId,
  decide,
  label,
  placeholder,
  actions,
  onCancel,
}: {
  cardId: string;
  decide: Decide;
  label: string;
  placeholder: string;
  actions: { label: string; option: string; secondary?: boolean; icon?: ReactNode }[];
  onCancel?: () => void;
}) {
  const [reason, setReason] = useState("");
  const uid = useId();
  const busy = decide.isPending && decide.variables?.card === cardId;
  const canSubmit = reason.trim().length > 0 && !decide.isPending;
  const run = (option: string, title: string) =>
    decide.mutate(
      { card: cardId, option, reason: reason.trim() },
      {
        onSuccess: (done) => {
          doneToast(title, done);
          setReason("");
        },
        onError: errorToast,
      },
    );
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const first = actions[0];
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit && first) {
      e.preventDefault();
      run(first.option, first.label);
    }
  };
  return (
    <div className="space-y-2">
      <label htmlFor={`${uid}-reason`} className="block text-[12px] font-medium text-muted">
        {label}
      </label>
      <Textarea
        id={`${uid}-reason`}
        rows={2}
        maxLength={MAX_REASON}
        showCount
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={onKey}
        placeholder={placeholder}
      />
      <div className="flex flex-wrap items-center gap-2">
        {actions.map((a, i) => (
          <Button
            key={`${a.option}-${i}`}
            size="sm"
            variant={a.secondary ? "secondary" : "primary"}
            disabled={!canSubmit}
            loading={busy && decide.variables?.option === a.option && !a.secondary}
            icon={a.icon}
            onClick={() => run(a.option, a.label)}
          >
            {a.label}
          </Button>
        ))}
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <KeyHint keys={[MOD, "Enter"]} />
      </div>
    </div>
  );
}

function RequestBanner({ requests }: { requests: GateRequest[] }) {
  if (requests.length === 0) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg">
      <Bot className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <span>
        {requests.map((r, i) => (
          <span key={`${r.option}-${r.left_out}`} className="block">
            {i === 0 ? "An agent asked for " : "It also asked for "}
            <strong>{requestWords(r)}</strong>
            {r.reason ? <> because: “{r.reason}”</> : null}.
          </span>
        ))}
        <span className="block text-muted">
          Nothing changes until a person approves it or turns it down.
        </span>
      </span>
    </div>
  );
}

export function GateCardView({
  card: view,
  evaluation,
  consequence,
  workspace,
  excludeIn,
  decide,
}: {
  card: GateCard;
  evaluation: Evaluation | undefined;
  consequence: Consequence | undefined;
  workspace: Workspace;
  excludeIn: GateView["exclude_in"];
  /** The write, when a person can decide this card here (a Studio session); else read-only. */
  decide?: Decide;
}) {
  const card = view.card;
  const requests = consequence?.requests ?? [];
  const pending = requests.length > 0;
  const status = pending ? STATUS.pending_human! : (STATUS[card.status] ?? STATUS.open!);
  const flips = Boolean(card.impact.flips);
  const titleId = `gate-card-${card.id}`;
  const chosen = view.options.find((o) => o.chosen)?.id ?? card.decision ?? card.recommended;
  const done = card.status === "decided" || card.status === "auto_decided";
  const [changing, setChanging] = useState(false);
  const [option, setOption] = useState(requests[0]?.option ?? chosen);
  const canDecide = Boolean(decide && consequence?.can_decide);
  const choosing = canDecide && !pending && (!done || changing);
  const labelOf = (id: string) => view.options.find((o) => o.id === id)?.label ?? id;
  return (
    <Card
      as="article"
      aria-labelledby={titleId}
      className={cn(
        pending && "border-warn",
        card.status === "open" && flips && !pending && "border-accent/50",
      )}
    >
      <div className="flex items-start gap-3 p-4 pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">
              {view.title}
            </h3>
            <Badge tone={status.tone}>
              {card.status === "decided" && !pending ? decidedBy(card.decided_by) : status.label}
            </Badge>
          </div>
          {evaluation && (
            <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              <VerdictChip verdict={evaluation.verdict} />
              <span>
                <span className="font-mono text-[12px]">{evaluation.rule_id}</span>{" "}
                {evaluation.title} · {whereText(evaluation)}
              </span>
            </p>
          )}
          <p
            className={cn(
              "mt-1 flex items-start gap-1.5 text-[13px]",
              flips ? "text-fg" : "text-muted",
            )}
          >
            {flips ? (
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
            ) : (
              <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
            )}
            <FactText text={view.impact} />
          </p>
          <p className="mt-1 text-[13px] text-muted">{view.status_line}</p>
        </div>
      </div>
      <div className="space-y-3 px-4 pb-4">
        <RequestBanner requests={requests} />
        <fieldset className="min-w-0">
          <legend className="mb-1.5 text-[12px] font-medium text-muted">
            Options{view.genes.length ? ` · what each gives for ${view.genes.join(", ")}` : ""}
          </legend>
          <div
            role={choosing ? "radiogroup" : "list"}
            aria-label={`${view.title}: options`}
            className="space-y-1.5"
          >
            {view.options.map((o) => {
              const missing = view.genes.filter((g) => !o.effects.some((e) => e.gene === g));
              const selected = choosing && o.id === option;
              return (
                <label
                  key={o.id}
                  role={choosing ? undefined : "listitem"}
                  className={cn(
                    "flex flex-col gap-1.5 rounded-lg border p-2.5 transition-colors duration-150",
                    selected || (!choosing && o.recommended)
                      ? "border-accent bg-accent-soft/40"
                      : "border-line",
                    choosing ? "cursor-pointer hover:border-line-strong" : "cursor-default",
                  )}
                >
                  <span className="flex items-start gap-2">
                    {choosing && (
                      <input
                        type="radio"
                        name={`gate-opt-${card.id}`}
                        value={o.id}
                        checked={selected}
                        onChange={() => setOption(o.id)}
                        className="mt-0.5 accent-[var(--accent)]"
                      />
                    )}
                    <span className="min-w-0 flex-1 text-[13px] text-fg">{o.label}</span>
                    <span className="flex shrink-0 flex-wrap justify-end gap-1">
                      {o.recommended && <Badge tone="accent">Recommended</Badge>}
                      {o.chosen && (
                        <Badge tone="ok" icon={<Check className="size-3" aria-hidden />}>
                          In use
                        </Badge>
                      )}
                      {o.requested && <Badge tone="warn">Agent asked</Badge>}
                    </span>
                  </span>
                  {(o.effects.length > 0 || missing.length > 0) && (
                    <span className={cn("flex flex-wrap gap-x-3 gap-y-1", choosing && "pl-6")}>
                      {o.effects.map((e) => {
                        const c = callOf(e.conclusion);
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
                      {missing.map((g) => (
                        <span
                          key={g}
                          className="inline-flex items-center gap-1 text-[12px] font-semibold text-fg"
                        >
                          <span>{g}</span>
                          <span>no call: it can no longer be compared</span>
                          <span className="font-normal text-warn">(changes)</span>
                        </span>
                      ))}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>
        <details className="rounded-lg bg-sunken/60 px-3 py-2 text-[13px]">
          <summary className="cursor-pointer font-medium text-muted select-none hover:text-fg">
            How this was worked out
          </summary>
          <p className="mt-1.5 leading-relaxed text-muted">
            <FactText text={view.explanation} />
          </p>
        </details>
        {canDecide && decide && pending ? (
          <DecideForm
            cardId={consequence!.decision_id}
            decide={decide}
            label="Your reason (required, for either answer; it goes into the record)"
            placeholder="e.g. the repeat plate's NTC stayed flat"
            actions={[
              { label: `Approve: ${requests[0]!.option_label}`, option: requests[0]!.option },
              { label: "Turn down", option: chosen, secondary: true },
            ]}
          />
        ) : choosing && decide ? (
          <DecideForm
            key={option}
            cardId={consequence!.decision_id}
            decide={decide}
            label="Why this option? (required; it goes into the record)"
            placeholder="e.g. the NTC amplified within five cycles of the samples on this plate"
            actions={[{ label: `Decide: ${labelOf(option)}`, option }]}
            onCancel={changing ? () => (setChanging(false), setOption(chosen)) : undefined}
          />
        ) : canDecide && done ? (
          <Button size="sm" variant="secondary" onClick={() => setChanging(true)}>
            Change the decision
          </Button>
        ) : (
          <p className="text-[13px]">
            {excludeIn === "curves" ? (
              <Link
                href={sectionPath(workspace, "curves")}
                className="font-medium text-accent hover:underline"
              >
                See the exclusions in Curves
              </Link>
            ) : (
              <Link
                href={sectionPath(workspace, "trace")}
                className="font-medium text-accent hover:underline"
              >
                Follow the calls down to their wells in Trace
              </Link>
            )}
          </p>
        )}
      </div>
    </Card>
  );
}

/** Wells a person left out through a card (the card itself is gone: nothing left to flip). */
function LeftOut({
  consequence: c,
  evaluation,
  decide,
}: {
  consequence: Consequence;
  evaluation: Evaluation | undefined;
  decide?: Decide;
}) {
  const decision = c.decision!;
  const titleId = `gate-left-${c.id}`;
  const [putting, setPutting] = useState(false);
  const requests = c.requests;
  return (
    <Card as="article" aria-labelledby={titleId} className={cn(requests.length && "border-warn")}>
      <div className="space-y-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">
            {decision.label}
          </h3>
          <Badge tone="ok">{decidedBy("human")}</Badge>
        </div>
        {evaluation && (
          <p className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <VerdictChip verdict={evaluation.verdict} />
            <span>
              <span className="font-mono text-[12px]">{c.rule_id}</span> {c.title} ·{" "}
              {whereText(evaluation)}
            </span>
          </p>
        )}
        <p className="text-[13px] text-fg">
          {plural(decision.left_out.length, "well")} left out of the analysis:{" "}
          <span className="text-muted">{decision.left_out.map(wellText).join(", ")}</span>
        </p>
        <p className="text-[13px] text-muted">
          Why: {decision.reason}
          {decision.decided_at ? (
            <span className="text-faint"> · decided {dateTime(decision.decided_at)}</span>
          ) : null}
        </p>
        <RequestBanner requests={requests} />
        {decide && c.can_decide ? (
          requests.length ? (
            <DecideForm
              cardId={c.decision_id}
              decide={decide}
              label="Your reason (required, for either answer; it goes into the record)"
              placeholder="e.g. the repeat plate confirms the contamination"
              actions={[
                { label: `Approve: ${requests[0]!.option_label}`, option: requests[0]!.option },
                { label: "Turn down", option: decision.option ?? "keep", secondary: true },
              ]}
            />
          ) : putting ? (
            <DecideForm
              cardId={c.decision_id}
              decide={decide}
              label="Why put them back? (required; it goes into the record)"
              placeholder="e.g. the repeat plate's NTC stayed flat"
              actions={[
                {
                  label: "Put the wells back",
                  option: "keep",
                  icon: <Undo2 className="size-4" aria-hidden />,
                },
              ]}
              onCancel={() => setPutting(false)}
            />
          ) : (
            <Button
              size="sm"
              variant="secondary"
              icon={<Undo2 className="size-4" aria-hidden />}
              onClick={() => setPutting(true)}
            >
              Put the wells back
            </Button>
          )
        ) : null}
      </div>
    </Card>
  );
}

export function GateCards({
  view,
  workspace,
  scope,
}: {
  view: GateView;
  workspace: Workspace;
  scope?: GateScope;
}) {
  const decide = useGateDecide(
    scope ?? { key: workspace.key, studyId: view.study_id, kind: workspace.kind },
    view,
  );
  const byId = new Map(view.evaluations.map((e) => [e.id, e]));
  const byCard = new Map(view.consequences.filter((c) => c.card_id).map((c) => [c.card_id!, c]));
  const leftOut = view.consequences.filter(
    (c) => !c.card_id && c.decision && c.decision.option !== "keep" && c.decision.left_out.length,
  );
  const writable = view.can_decide ? decide : undefined;
  return (
    <section aria-labelledby="gate-cards-title">
      <div className="mb-3">
        <h2 id="gate-cards-title" className="text-base font-semibold tracking-tight text-fg">
          Decision Cards from the controls
        </h2>
        <p className="mt-0.5 text-[13px] text-muted">
          A card exists only when leaving a rule&rsquo;s wells out can change a conclusion.{" "}
          {view.can_decide
            ? "Only a person decides: choose an option and say why."
            : "Read here; this study was analysed outside Studio, so nothing is decided on this page."}
        </p>
        {view.decide_note && <p className="mt-1 text-[12px] text-muted">{view.decide_note}</p>}
      </div>
      {view.cards.length === 0 && leftOut.length === 0 ? (
        <Card className="p-4 text-[13px] text-muted">
          No control finding can change a conclusion, so there is nothing to decide.
        </Card>
      ) : (
        <ol className="space-y-3">
          {view.cards.map((c) => {
            const consequence = byCard.get(c.card.id);
            return (
              <li
                key={`${c.card.id}:${c.card.status}:${c.card.decision ?? ""}:${consequence?.requests.length ?? 0}`}
              >
                <GateCardView
                  card={c}
                  evaluation={byId.get(consequence?.id ?? "")}
                  consequence={consequence}
                  workspace={workspace}
                  excludeIn={view.exclude_in}
                  decide={writable}
                />
              </li>
            );
          })}
          {leftOut.map((c) => (
            <li key={`left:${c.id}:${c.decision?.decided_at ?? ""}:${c.requests.length}`}>
              <LeftOut consequence={c} evaluation={byId.get(c.id)} decide={writable} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

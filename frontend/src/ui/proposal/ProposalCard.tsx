/**
 * The Studio proposal card (docs/app.md §4, Design): one proposal in six parts.
 *
 *   1. the proposal in plain words, any edit a person made, and the other readings considered
 *   2. Why: every source as a fold-out (quoted file text with its origin and flags, a sheet
 *      cell, a well that opens its curve)
 *   3. Engine check: consistent / contradicted / cannot check, with the rule ids and numbers
 *   4. Consequence: hidden in the blind stages (or the yes/no of "Does this matter?"); the
 *      numbers of a round-trip exclusion once results are visible
 *   5. Level: High / Moderate / Low / Very low and its named reasons
 *   6. Accept · Edit (the payload's fields, re-checked) · Reject (a reason is required)
 *
 * and a footer saying who made it. The card writes nothing itself: the section passes the
 * actions (`onAccept`, `onEdit`, `onReject`), and a refusal thrown by one is shown on the card.
 * Text from a file, a sheet, a model or an agent is rendered as text and never obeyed.
 */
import { Check, Pencil, X } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { JobView } from "@/api/client";
import { useJob } from "@/api/jobs";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/format";
import {
  KIND_TITLE,
  STATUS_WORDS,
  describeProposal,
  effectivePayload,
  isBlindKind,
  makerText,
  type Proposal,
} from "@/lib/vocab";
import { Badge, Kbd, type Tone } from "../Badge";
import { Button } from "../Button";
import { Card } from "../Card";
import { ErrorPanel } from "../ErrorPanel";
import { JobCard } from "../JobCard";
import { Hash } from "../Copy";
import { Textarea } from "../controls";
import { CheckTag, LevelTag } from "../tags";
import { AlternativeStarts, PayloadEditor, diffPayload, type EditOptions, type Payload } from "./edit";
import {
  CheckDetails,
  CheckSummary,
  DetailsView,
  EvidenceList,
  ExclusionConsequence,
  HIDDEN_TEXT,
  MattersLine,
  Part,
  WhySummary,
  exclusionHeadline,
  type ProposalCheck,
  type QuoteLookup,
} from "./parts";

/** The longest reason the decision chain takes (`qpilot.core.decisions.MAX_REASON`). */
export const MAX_REASON = 500;

export type ProposalAction = "accept" | "edit" | "reject";

/** What the inbox can do to a card from the keyboard (`a`, `e`, `x`). */
export interface ProposalCardHandle {
  /** Accept (asks for a reason first when the engine contradicts it). */
  accept: () => void;
  /** Open the editor. */
  edit: () => void;
  /** Open the reject box. */
  reject: () => void;
  /** Move keyboard focus to the card. */
  focus: () => void;
}

export interface ProposalCardProps {
  proposal: Proposal;
  /** Quoted file text by `text_id` (`GET …/quarantine`); `undefined` = still loading. */
  quotes?: QuoteLookup;
  /** Sample-sheet cells → `text_id` (`GET …/quarantine`), for `cell` evidence. */
  sheetCells?: Record<string, string>;
  /**
   * Whether results may be shown (both blind stages confirmed). Design and curve proposals
   * never show more than the yes/no of "Does this matter?", whatever this says.
   */
  resultsVisible?: boolean;
  /** The answer to "Does this matter?" when the section already has it (null: cannot tell yet). */
  matters?: boolean | null;
  /** The running or finished "Does this matter?" job; the card shows it and reads its answer. */
  mattersJob?: string | null;
  /** Ask "Does this matter?" (offered for a design proposal with another reading). */
  onAskMatters?: () => void;
  /** Why a round-trip consequence no longer holds; its numbers are then not shown. */
  stale?: string | null;
  /** Accept as proposed. Throw (an `ApiError`, or an `Error` with the refusal in words) to refuse. */
  onAccept?: (reason: string) => Promise<unknown>;
  /** Accept with these payload fields changed (only the changed ones are passed). */
  onEdit?: (edits: Payload, reason: string) => Promise<unknown>;
  /** Reject with a reason (required). */
  onReject?: (reason: string) => Promise<unknown>;
  /** The engine's check of an edited reading, before anything is written (optional). */
  onCheckEdit?: (edits: Payload) => Promise<ProposalCheck>;
  /** Open a well's curve (`run_id/well`), from well evidence and from wells in a check. */
  onOpenWell?: (wellKey: string) => void;
  /** Suggestions for the editor (groups, units, rules). */
  editOptions?: EditOptions;
  /** Replace the editor for a kind the default editor does not suit. */
  renderEditor?: (props: { value: Payload; onChange: (next: Payload) => void }) => ReactNode;
  /** The inbox's current card: a ring, scrolled into view, keyboard hints shown. */
  focused?: boolean;
  /** Called when the card is clicked or receives focus (the inbox moves its cursor here). */
  onFocusCard?: () => void;
  /**
   * Replace part 4 for a kind this card does not describe well enough (return null to keep
   * the default). Called only when results may be shown or the kind is not blind.
   */
  renderConsequence?: (p: Proposal) => { summary: ReactNode; details?: ReactNode; tone?: "warn" } | null;
  /** Actions that need a reason for this proposal (on top of the chain's own rules). */
  requireReason?: ProposalAction[];
  /** The reason box's question, per action. */
  reasonLabels?: Partial<Record<ProposalAction, string>>;
  /** Hide Accept / Edit / Reject (a read-only list). */
  readOnly?: boolean;
  /** Heading level of the proposal sentence (default 3). */
  headingLevel?: 2 | 3 | 4;
  /** Extra content under the proposal (a curve, a table). */
  children?: ReactNode;
  /** Extra footer content (e.g. "What the model saw"). */
  footer?: ReactNode;
  className?: string;
}

const STATUS_TONE: Record<Proposal["status"], Tone> = {
  proposed: "accent",
  accepted: "ok",
  edited: "ok",
  rejected: "neutral",
  superseded: "neutral",
};

/** A `{matters: bool|null}` job result (or a bare boolean) → the answer. */
function readMatters(result: unknown): boolean | null | undefined {
  if (typeof result === "boolean") return result;
  if (result && typeof result === "object" && "matters" in result) {
    const m = (result as { matters: unknown }).matters;
    return typeof m === "boolean" ? m : null;
  }
  return undefined;
}

function ReasonBox({
  id,
  label,
  value,
  onChange,
  required,
  suggestions,
  autoFocus,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  suggestions?: string[];
  autoFocus?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-fg">
        {label}
        {required ? null : <span className="ml-1 font-normal text-faint">(optional)</span>}
      </label>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={MAX_REASON}
        showCount
        rows={2}
        required={required}
        aria-required={required || undefined}
        autoFocus={autoFocus}
        className="min-h-14"
      />
      {suggestions?.length ? (
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange(s)}
              className="max-w-full truncate rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-xs text-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** One proposal, its evidence, the engine's check, and the person's three choices. */
export const ProposalCard = forwardRef<ProposalCardHandle, ProposalCardProps>(function ProposalCard(
  {
    proposal: p,
    quotes,
    sheetCells,
    resultsVisible = false,
    matters,
    mattersJob,
    onAskMatters,
    stale,
    onAccept,
    onEdit,
    onReject,
    onCheckEdit,
    onOpenWell,
    editOptions,
    renderEditor,
    renderConsequence,
    requireReason,
    reasonLabels,
    focused,
    onFocusCard,
    readOnly,
    headingLevel = 3,
    children,
    footer,
    className,
  },
  ref,
) {
  const rootRef = useRef<HTMLDivElement>(null);
  const uid = useId();
  const [mode, setMode] = useState<ProposalAction | null>(null);
  const [busy, setBusy] = useState<ProposalAction | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState<Payload>(() => effectivePayload(p));
  // The engine's answer for one edited reading (`key` = the edits as JSON).
  const [recheck, setRecheck] = useState<{ key: string; check?: ProposalCheck; failed?: boolean } | null>(null);

  const pending = p.status === "proposed";
  const contradicted = p.check.status === "contradicted";
  // The server refuses an exclusion accepted without a reason; ask for it here.
  const needs = new Set<ProposalAction>(requireReason ?? (p.kind === "prism.exclusion_reason" ? ["accept", "edit"] : []));
  const acceptNeedsReason = needs.has("accept");
  const labels: Partial<Record<ProposalAction, string>> = {
    ...(p.kind === "prism.exclusion_reason"
      ? { accept: "Say why this value was excluded in Prism (kept in the record).", edit: "Say why (kept in the record)." }
      : {}),
    ...reasonLabels,
  };
  const blind = isBlindKind(p);
  const editable = Boolean(onEdit) && p.kind !== "stage.confirm" && Object.keys(p.payload).length > 0;
  const canAct = pending && !readOnly;

  // The "Does this matter?" job, followed here so the section only has to start it.
  const job = useJob(mattersJob ?? null);
  const jobView = job.data as JobView | undefined;
  const ownMatters = p.consequence && (p.consequence as Record<string, unknown>).matters === true ? true : undefined;
  const mattersValue: boolean | null | undefined =
    ownMatters ?? (matters !== undefined ? matters : jobView?.status === "done" ? readMatters(jobView.result) : undefined);
  const asking = jobView != null && (jobView.status === "queued" || jobView.status === "running");

  const close = useCallback(() => {
    setMode(null);
    setError(null);
    setReason("");
    setRecheck(null);
  }, []);

  const run = useCallback(
    async (action: ProposalAction, call: () => Promise<unknown>) => {
      setBusy(action);
      setError(null);
      try {
        await call();
        close();
      } catch (err) {
        setError(err);
      } finally {
        setBusy(null);
      }
    },
    [close],
  );

  const startAccept = useCallback(() => {
    if (!canAct || !onAccept || busy) return;
    if (contradicted || acceptNeedsReason) {
      setError(null);
      setMode("accept");
      return;
    }
    void run("accept", () => onAccept(""));
  }, [canAct, onAccept, busy, contradicted, acceptNeedsReason, run]);

  const startEdit = useCallback(() => {
    if (!canAct || !editable || busy) return;
    setDraft(effectivePayload(p));
    setError(null);
    setMode("edit");
  }, [canAct, editable, busy, p]);

  const startReject = useCallback(() => {
    if (!canAct || !onReject || busy) return;
    setError(null);
    setMode("reject");
  }, [canAct, onReject, busy]);

  useImperativeHandle(
    ref,
    () => ({
      accept: startAccept,
      edit: startEdit,
      reject: startReject,
      focus: () => rootRef.current?.focus({ preventScroll: false }),
    }),
    [startAccept, startEdit, startReject],
  );

  // The engine's re-check of an edit, a moment after the fields stop changing.
  const edits = mode === "edit" ? diffPayload(p.payload as Payload, draft) : {};
  const editKey = JSON.stringify(edits);
  const checking = mode === "edit" && Boolean(onCheckEdit) && editKey !== "{}";
  useEffect(() => {
    if (!checking || !onCheckEdit) return;
    let live = true;
    const timer = setTimeout(() => {
      onCheckEdit(JSON.parse(editKey) as Payload).then(
        (check) => live && setRecheck({ key: editKey, check }),
        () => live && setRecheck({ key: editKey, failed: true }),
      );
    }, 400);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [checking, editKey, onCheckEdit]);
  const recheckNow = checking && recheck?.key === editKey ? recheck : null;
  const recheckStatus = !checking ? "idle" : !recheckNow ? "checking" : recheckNow.failed ? "failed" : "done";

  const editContradicted = recheckNow?.check?.status === "contradicted";
  const reasonRequired =
    mode === "reject" ||
    (mode === "accept" && (contradicted || needs.has("accept"))) ||
    (mode === "edit" && (contradicted || editContradicted || needs.has("edit")));
  const changed = editKey !== "{}";
  const canSubmit = !busy && (!reasonRequired || reason.trim().length > 0) && (mode !== "edit" || changed);

  const submit = () => {
    if (!canSubmit) return;
    const r = reason.trim();
    if (mode === "accept" && onAccept) void run("accept", () => onAccept(r));
    if (mode === "reject" && onReject) void run("reject", () => onReject(r));
    if (mode === "edit" && onEdit) void run("edit", () => onEdit(JSON.parse(editKey) as Payload, r));
  };

  const onFormKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
      rootRef.current?.focus();
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  const H = `h${headingLevel}` as "h3";
  const titleId = `${uid}-title`;
  const question = p.kind.startsWith("prism.") && typeof p.payload.question === "string" ? p.payload.question : null;
  const consequence = (p.consequence ?? null) as Record<string, unknown> | null;

  // ---- part 4: the consequence ----
  let consequenceSummary: ReactNode;
  let consequenceFold: ReactNode = null;
  let consequenceSide: ReactNode = null;
  let consequenceTone: "warn" | undefined;
  if (blind) {
    consequenceSummary = <MattersLine matters={mattersValue} />;
    consequenceTone = mattersValue === true ? "warn" : undefined;
    const askable = p.kind.startsWith("design.") && p.alternatives.length > 0 && pending && onAskMatters;
    if (askable && mattersValue === undefined && !asking && !ownMatters) {
      consequenceSide = (
        <Button size="sm" variant="secondary" onClick={onAskMatters}>
          Does this matter?
        </Button>
      );
    }
  } else if (!stale && renderConsequence && renderConsequence(p)) {
    const custom = renderConsequence(p)!;
    consequenceSummary = custom.summary;
    consequenceFold = custom.details ?? null;
    consequenceTone = custom.tone;
  } else if (stale) {
    consequenceSummary = (
      <span className="text-warn">
        <strong>Out of date:</strong> {stale}. Its numbers are not shown, and accepting it is refused until they are computed again.
      </span>
    );
  } else if (!consequence) {
    consequenceSummary = <span className="text-muted">No consequence is computed for this kind of proposal.</span>;
  } else if (!resultsVisible) {
    consequenceSummary = <span className="text-muted">{HIDDEN_TEXT}</span>;
  } else if (p.kind === "prism.exclusion_reason" && "fc_before" in consequence) {
    consequenceSummary = exclusionHeadline(consequence);
    consequenceFold = <ExclusionConsequence c={consequence} />;
  } else if (p.kind === "prism.value_edit") {
    consequenceSummary = (
      <span>
        The value no longer matches the record: qPilot exported{" "}
        <span className="font-mono tabular">{String(consequence.exported ?? "—")}</span>, Prism sent back{" "}
        <span className="font-mono tabular">{String(consequence.returned ?? "—")}</span>.
      </span>
    );
  } else {
    consequenceSummary = <span className="text-muted">What accepting it changes, in numbers.</span>;
    consequenceFold = <DetailsView details={consequence} onOpenWell={onOpenWell} hide={["basis"]} />;
  }

  return (
    <Card
      as="article"
      ref={rootRef}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-proposal={p.id}
      data-focused={focused || undefined}
      onFocus={(e) => {
        if (e.target === e.currentTarget) onFocusCard?.();
      }}
      onMouseDown={() => onFocusCard?.()}
      className={cn(
        "relative scroll-mt-24 outline-none transition-shadow duration-150",
        focused && "ring-2 ring-focus/70 ring-offset-2 ring-offset-bg",
        !pending && "bg-surface-2",
        className,
      )}
    >
      {contradicted && pending ? (
        <span aria-hidden className="absolute top-4 bottom-4 left-0 w-[3px] rounded-r bg-danger" />
      ) : null}
      <div className="px-4 pt-3.5 pb-3 sm:px-5">
        {/* 1. The proposal */}
        <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          <div className="min-w-0 flex-1">
            <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
              <span className="shrink-0 font-medium tracking-wider text-faint uppercase">{KIND_TITLE[p.kind] ?? p.kind}</span>
              <span aria-hidden className="text-faint">
                ·
              </span>
              <span className="truncate font-mono">{p.subject}</span>
            </p>
            <H id={titleId} className="mt-1 text-[15px] leading-snug font-semibold text-fg">
              {describeProposal(p)}
            </H>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {pending ? null : (
              <Badge tone={STATUS_TONE[p.status]}>{STATUS_WORDS[p.status]}</Badge>
            )}
            <CheckTag status={p.check.status} />
          </div>
        </header>

        {question ? (
          <p className="mt-2 rounded-lg border border-info/25 bg-info-soft px-3 py-2 text-[13px] text-fg">{question}</p>
        ) : null}
        {p.edits && Object.keys(p.edits).length ? (
          <p className="mt-2 text-[13px] text-fg">
            <span className="font-medium">As edited by a person:</span> {describeProposal(p, effectivePayload(p))}
          </p>
        ) : null}
        {p.alternatives.length ? (
          <div className="mt-2 text-[13px] text-muted">
            <span className="font-medium text-fg">
              {p.alternatives.length === 1 ? "Other reading considered:" : "Other readings considered:"}
            </span>{" "}
            {p.alternatives.length === 1 ? (
              describeProposal(p, { ...(p.payload as Payload), ...p.alternatives[0] })
            ) : (
              <ul className="mt-1 list-disc pl-5">
                {p.alternatives.slice(0, 6).map((alt, i) => (
                  <li key={i}>{describeProposal(p, { ...(p.payload as Payload), ...alt })}</li>
                ))}
                {p.alternatives.length > 6 ? <li>… and {p.alternatives.length - 6} more</li> : null}
              </ul>
            )}
          </div>
        ) : null}
        {!pending ? (
          <p className="mt-2 text-[13px] text-muted">
            {STATUS_WORDS[p.status]}
            {p.decided_by === "human" ? " by a person" : ""}
            {p.decided_at ? ` · ${relativeTime(p.decided_at)}` : ""}
            {p.reason ? (
              <>
                {" — "}
                <span className="text-fg">“{p.reason}”</span>
              </>
            ) : null}
          </p>
        ) : null}
        {children ? <div className="mt-3">{children}</div> : null}

        {/* 2–5 */}
        <div className="mt-2 divide-y divide-line border-t border-line">
          <Part label="Why" summary={<WhySummary evidence={p.evidence} quotes={quotes} />}>
            {p.evidence.length ? (
              <EvidenceList evidence={p.evidence} quotes={quotes} sheetCells={sheetCells} onOpenWell={onOpenWell} />
            ) : null}
          </Part>
          <Part
            label="Engine check"
            tone={contradicted ? "danger" : undefined}
            summary={<CheckSummary check={p.check} />}
          >
            {stale ? null : <CheckDetails check={p.check} onOpenWell={onOpenWell} />}
          </Part>
          <Part label="Consequence" tone={consequenceTone} summary={consequenceSummary} side={consequenceSide}>
            {consequenceFold}
          </Part>
          {mattersJob && jobView && jobView.status !== "done" ? (
            <div className="pb-2.5 sm:pl-[128px]">
              <JobCard job={jobView} />
            </div>
          ) : null}
          <Part
            label="Level"
            summary={
              <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <LevelTag level={p.level} />
                {p.reasons.length === 1 ? <span className="text-muted">{p.reasons[0]}</span> : null}
              </span>
            }
          >
            {p.reasons.length > 1 ? (
              <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
                {p.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
          </Part>
        </div>

        {/* 6. The person's choice */}
        {canAct ? (
          mode ? (
            <div
              className="mt-1 flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-3"
              onKeyDown={onFormKey}
              role="group"
              aria-label={mode === "edit" ? "Edit the proposal" : mode === "reject" ? "Reject the proposal" : "Accept the proposal"}
            >
              {mode === "accept" ? (
                <ReasonBox
                  id={`${uid}-reason`}
                  label={
                    contradicted
                      ? "The engine's check contradicts this proposal. Say why you accept it anyway."
                      : (labels.accept ?? "Why you accept it")
                  }
                  value={reason}
                  onChange={setReason}
                  required
                  autoFocus
                />
              ) : null}
              {mode === "reject" ? (
                <ReasonBox
                  id={`${uid}-reason`}
                  label={labels.reject ?? "Why do you reject it?"}
                  value={reason}
                  onChange={setReason}
                  required
                  autoFocus
                  suggestions={contradicted ? ["Contradicted by the engine check"] : undefined}
                />
              ) : null}
              {mode === "edit" ? (
                <>
                  <AlternativeStarts proposal={p} onPick={setDraft} />
                  {renderEditor ? (
                    renderEditor({ value: draft, onChange: setDraft })
                  ) : (
                    <PayloadEditor proposal={p} value={draft} onChange={setDraft} options={editOptions} />
                  )}
                  <div className="rounded-md border border-line bg-surface px-3 py-2 text-[13px]">
                    {changed ? (
                      <>
                        <span className="font-medium text-fg">As edited:</span> {describeProposal(p, draft)}
                        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted" aria-live="polite">
                          {recheckStatus === "checking" ? "The engine is checking the edit…" : null}
                          {recheckStatus === "done" && recheckNow?.check ? (
                            <>
                              <CheckTag status={recheckNow.check.status} />
                              <span>{recheckNow.check.note}</span>
                            </>
                          ) : null}
                          {recheckStatus === "failed" ? "The edit could not be checked now; it is checked again when you accept." : null}
                          {recheckStatus === "idle" && !onCheckEdit ? "The engine checks the edit when you accept it." : null}
                        </div>
                      </>
                    ) : (
                      <span className="text-muted">Change a field to edit the proposal.</span>
                    )}
                  </div>
                  <ReasonBox
                    id={`${uid}-reason`}
                    label={
                      editContradicted
                        ? "The engine's check contradicts the edit. Say why you accept it anyway."
                        : contradicted
                          ? "The engine's check contradicted the proposal. Say why you accept your edit."
                          : (labels.edit ?? "Why you changed it")
                    }
                    value={reason}
                    onChange={setReason}
                    required={reasonRequired}
                  />
                </>
              ) : null}
              {error ? <ErrorPanel error={error} compact title="Not done" /> : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={mode === "reject" ? "danger" : "primary"}
                  onClick={submit}
                  disabled={!canSubmit}
                  loading={busy === mode}
                  icon={mode === "reject" ? <X /> : <Check />}
                >
                  {mode === "accept" ? (contradicted ? "Accept anyway" : "Accept") : mode === "reject" ? "Reject" : "Accept the edit"}
                </Button>
                <Button variant="ghost" onClick={close} disabled={Boolean(busy)}>
                  Cancel
                </Button>
                <span className="ml-auto hidden text-xs text-faint sm:inline">
                  <Kbd>⌘</Kbd>
                  <Kbd>↵</Kbd> to confirm · <Kbd>Esc</Kbd> to cancel
                </span>
              </div>
            </div>
          ) : (
            <div className="mt-1 flex flex-wrap items-center gap-2 pt-1">
              {onAccept ? (
                <Button
                  variant={contradicted ? "secondary" : "primary"}
                  icon={<Check />}
                  onClick={startAccept}
                  loading={busy === "accept"}
                  disabled={Boolean(busy)}
                  aria-keyshortcuts="a"
                >
                  {contradicted ? "Accept anyway…" : needs.has("accept") ? "Accept…" : "Accept"}
                </Button>
              ) : null}
              {editable ? (
                <Button icon={<Pencil />} onClick={startEdit} disabled={Boolean(busy)} aria-keyshortcuts="e">
                  Edit…
                </Button>
              ) : null}
              {onReject ? (
                <Button icon={<X />} onClick={startReject} disabled={Boolean(busy)} aria-keyshortcuts="x">
                  Reject…
                </Button>
              ) : null}
              {focused ? (
                <span className="ml-auto hidden items-center gap-1 text-xs text-faint sm:inline-flex">
                  <Kbd>a</Kbd> accept <Kbd>e</Kbd> edit <Kbd>x</Kbd> reject
                </span>
              ) : null}
              {error && !mode ? <ErrorPanel error={error} compact title="Not done" className="w-full" /> : null}
            </div>
          )
        ) : null}
      </div>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-b-xl border-t border-line bg-surface-2 px-4 py-2 text-xs text-muted sm:px-5">
        <span className="min-w-0">{makerText(p.made_by)}</span>
        {p.created_at ? <span className="text-faint">proposed {relativeTime(p.created_at)}</span> : null}
        <span className="ml-auto inline-flex items-center">
          <Hash value={p.id} length={10} prefix="id" />
        </span>
        {footer}
      </footer>
    </Card>
  );
});

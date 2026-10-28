/**
 * A Studio stage's inbox (Design, Curves, the Prism round trip): every pending proposal as a
 * {@link ProposalCard}, contradicted first, with filters, `j`/`k` to move and `a`/`e`/`x` to
 * act on the focused card; the proposals already decided fold away under the list.
 */
import { CheckCircle2, ChevronRight, Inbox, Search, X } from "lucide-react";
import { AnimatePresence, MotionConfig, motion, useIsPresent } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count, dateTime, relativeTime } from "@/lib/format";
import { useHotkeys } from "@/lib/hooks";
import {
  CHECK,
  KIND_TITLE,
  STATUS_WORDS,
  deciderWords,
  describeProposal,
  effectivePayload,
  type CheckStatus,
  type Proposal,
} from "@/lib/vocab";
import { Badge, Kbd } from "../Badge";
import { Button } from "../Button";
import { ErrorPanel } from "../ErrorPanel";
import { Input, Select } from "../controls";
import { EmptyState, LoadingBlock } from "../feedback";
import { CheckTag } from "../tags";
import type { EditOptions } from "./edit";
import {
  isWarming,
  useCheckEdit,
  useMattersJobs,
  useProposalActions,
  useQuotes,
  useStageProposals,
  type InboxStage,
} from "./hooks";
import { Warming } from "./parts";
import { ProposalCard, type ProposalCardHandle, type ProposalCardProps } from "./ProposalCard";
import { refutedGroups, refutedWords } from "./groups";

const PAGE = 20;
type CheckFilter = "all" | CheckStatus;

/**
 * A card's content, inert from the moment it leaves the list: a decided card never offers
 * Accept or Reject again while its exit animation runs (or, in a background tab where the
 * browser pauses animations, while it waits to run).
 */
function Present({ children }: { children: ReactNode }) {
  const present = useIsPresent();
  return (
    <div inert={!present} aria-hidden={present ? undefined : true}>
      {children}
    </div>
  );
}

/** How a card leaves: animated alone; several at once (a bulk decision) leave at once. */
const LEAVE = {
  exit: (many: boolean) =>
    many
      ? { opacity: 0, height: 0, marginTop: 0, transition: { duration: 0 } }
      : { opacity: 0, height: 0, marginTop: 0, transition: { duration: 0.18 } },
};

/** A filter the section sets from outside (a well clicked on the plate map, say). */
export interface InboxFilter {
  /** What the filter shows, in words ("sample 1496"). */
  label: string;
  match: (p: Proposal) => boolean;
}

export interface StageInboxProps {
  /** The session id. */
  sid: string;
  stage: InboxStage;
  /** Whether results may be shown (from the workspace frame). */
  resultsVisible?: boolean;
  /** Open a well's curve (`run_id/well`). */
  onOpenWell?: (wellKey: string) => void;
  /** Shown when the stage has no proposal at all (what to do, with the propose button). */
  empty?: ReactNode;
  /** Shown above the decided list when nothing is waiting (e.g. the confirm step). */
  allDecided?: ReactNode;
  /** A filter set from outside, with a way to clear it. */
  filter?: InboxFilter | null;
  onClearFilter?: () => void;
  /** Called when the focused card changes (e.g. to highlight its wells). */
  onFocusProposal?: (p: Proposal | null) => void;
  /** Extra content inside a card, under the proposal. */
  cardExtra?: (p: Proposal) => ReactNode;
  /** Card props a stage needs for some kinds (renderEditor, renderConsequence, reason rules). */
  cardProps?: (p: Proposal) => Partial<ProposalCardProps>;
  editOptions?: EditOptions;
  /** Turn the inbox keys off (another inbox on the page owns them). */
  hotkeys?: boolean;
  /** Accessible name of the list. */
  label?: string;
  /**
   * Proposals are still arriving (a propose job runs): keep them in arrival order, so cards
   * do not jump while the person reads; the usual order (contradicted first) returns after.
   */
  arriving?: boolean;
}

const searchable = (p: Proposal) =>
  `${p.subject} ${describeProposal(p)} ${KIND_TITLE[p.kind] ?? ""}`.toLowerCase();

/** The inbox of one stage, read from `GET /api/sessions/{sid}/proposals?stage=`. */
export function StageInbox({
  sid,
  stage,
  resultsVisible = false,
  onOpenWell,
  empty,
  allDecided,
  filter,
  onClearFilter,
  onFocusProposal,
  cardExtra,
  cardProps,
  editOptions,
  hotkeys = true,
  label = "Proposals waiting for you",
  arriving = false,
}: StageInboxProps) {
  const list = useStageProposals(sid, stage);
  const { lookup, sheetCells } = useQuotes(sid);
  const actions = useProposalActions(sid, list.data?.head, stage);
  const matters = useMattersJobs(sid);
  const checkEdit = useCheckEdit(sid);
  const [check, setCheck] = useState<CheckFilter>("all");
  const [kind, setKind] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  // The focused card, by id and by its place (used once it leaves the list: the next one).
  const [focusAt, setFocusAt] = useState<{ id: string | null; index: number }>({
    id: null,
    index: 0,
  });
  const refs = useRef(new Map<string, ProposalCardHandle>());

  const all = useMemo(() => list.data?.proposals ?? [], [list.data]);
  // A waiting confirm step is the confirm dialog's (ConfirmStage), not a card of the inbox.
  const pendingAll = useMemo(() => {
    const waiting = all.filter((p) => p.status === "proposed" && p.kind !== "stage.confirm");
    return arriving
      ? [...waiting].sort((a, b) => a.created_at.localeCompare(b.created_at))
      : waiting;
  }, [all, arriving]);
  const decided = useMemo(() => all.filter((p) => p.status !== "proposed"), [all]);

  const byCheck = useMemo(() => {
    const n: Record<CheckStatus, number> = { contradicted: 0, cannot_check: 0, consistent: 0 };
    for (const p of pendingAll) n[p.check.status] += 1;
    return n;
  }, [pendingAll]);
  const kinds = useMemo(() => {
    const n = new Map<string, number>();
    for (const p of pendingAll) n.set(p.kind, (n.get(p.kind) ?? 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1]);
  }, [pendingAll]);

  // A filter whose last proposal was just decided falls back to everything waiting.
  const checkNow: CheckFilter = check !== "all" && byCheck[check] === 0 ? "all" : check;
  const kindNow = kind !== "all" && !kinds.some(([k]) => k === kind) ? "all" : kind;
  const pending = useMemo(() => {
    const q = query.trim().toLowerCase();
    return pendingAll.filter(
      (p) =>
        (checkNow === "all" || p.check.status === checkNow) &&
        (kindNow === "all" || p.kind === kindNow) &&
        (!filter || filter.match(p)) &&
        (!q || searchable(p).includes(q)),
    );
  }, [pendingAll, checkNow, kindNow, filter, query]);
  // Many refuted well calls of one target read the same way fold into one line each (the
  // engine refutes every one); "Show all" opens that group's cards. Folding decides nothing.
  const [unfolded, setUnfolded] = useState<ReadonlySet<string>>(() => new Set());
  const folded = useMemo(
    () => (arriving ? [] : refutedGroups(pending).filter((g) => !unfolded.has(g.key))),
    [pending, unfolded, arriving],
  );
  const listed = useMemo(() => {
    const hidden = new Set(folded.flatMap((g) => g.ids));
    return hidden.size ? pending.filter((p) => !hidden.has(p.id)) : pending;
  }, [pending, folded]);
  const visible = listed.slice(0, shown);
  // Several cards leaving at once (a bulk accept or reject) leave without an animation.
  const idsKey = visible.map((p) => p.id).join(" ");
  const [lastShown, setLastShown] = useState({ key: idsKey, many: false });
  let manyLeaving = lastShown.many;
  if (lastShown.key !== idsKey) {
    const kept = new Set(visible.map((p) => p.id));
    manyLeaving = lastShown.key.split(" ").filter((id) => id && !kept.has(id)).length > 1;
    setLastShown({ key: idsKey, many: manyLeaving });
  }

  const focusIndex = visible.findIndex((p) => p.id === focusAt.id);
  // No card is focused until the person moves (j/k) or clicks one.
  const effectiveIndex =
    focusIndex >= 0 ? focusIndex : focusAt.id ? Math.min(focusAt.index, visible.length - 1) : -1;
  const focused = effectiveIndex >= 0 ? visible[effectiveIndex] : undefined;
  useEffect(() => {
    onFocusProposal?.(focused ?? null);
  }, [focused, onFocusProposal]);

  const move = (delta: number) => {
    if (!listed.length) return;
    const next = Math.max(
      0,
      Math.min(listed.length - 1, (effectiveIndex < 0 ? -1 : effectiveIndex) + delta),
    );
    if (next >= shown) setShown((n) => n + PAGE);
    const p = listed[next];
    if (p) {
      setFocusAt({ id: p.id, index: next });
      requestAnimationFrame(() => refs.current.get(p.id)?.focus());
    }
  };

  useHotkeys(
    {
      j: () => move(1),
      k: () => move(-1),
      a: () => focused && refs.current.get(focused.id)?.accept(),
      e: () => focused && refs.current.get(focused.id)?.edit(),
      x: () => focused && refs.current.get(focused.id)?.reject(),
    },
    hotkeys && listed.length > 0,
  );

  if (list.isPending) return <LoadingBlock label="Reading the proposals" lines={6} />;
  if (isWarming(list.error)) return <Warming message={list.error.message} />;
  if (list.error) return <ErrorPanel error={list.error} onRetry={() => void list.refetch()} />;
  if (!all.length) {
    return (
      <>
        {empty ?? (
          <EmptyState icon={<Inbox />} title="No proposals in this stage yet">
            Ask for proposals first.
          </EmptyState>
        )}
      </>
    );
  }

  const filtered =
    checkNow !== "all" || kindNow !== "all" || Boolean(query.trim()) || Boolean(filter);
  const checkOptions: { value: CheckFilter; label: string; n: number }[] = [
    { value: "all", label: "All waiting", n: pendingAll.length },
    { value: "contradicted", label: CHECK.contradicted.word, n: byCheck.contradicted },
    { value: "cannot_check", label: CHECK.cannot_check.word, n: byCheck.cannot_check },
    { value: "consistent", label: CHECK.consistent.word, n: byCheck.consistent },
  ];

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex flex-col gap-4">
        {pendingAll.length ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <div
                role="group"
                aria-label="Show by engine check"
                className="flex flex-wrap gap-1.5"
              >
                {checkOptions.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    aria-pressed={checkNow === o.value}
                    disabled={o.value !== "all" && o.n === 0}
                    onClick={() => {
                      setCheck(o.value);
                      setShown(PAGE);
                    }}
                    className={cn(
                      "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors disabled:opacity-40",
                      checkNow === o.value
                        ? "border-accent/40 bg-accent-soft text-accent-strong"
                        : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg",
                    )}
                  >
                    {o.label}
                    <span className="font-mono text-xs tabular">{count(o.n)}</span>
                  </button>
                ))}
              </div>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                {kinds.length > 1 ? (
                  <Select
                    size="sm"
                    label="Kind of proposal"
                    className="w-48"
                    value={kindNow}
                    onValueChange={(v) => {
                      setKind(v);
                      setShown(PAGE);
                    }}
                    options={[
                      { value: "all", label: `Every kind (${count(pendingAll.length)})` },
                      ...kinds.map(([k, n]) => ({
                        value: k,
                        label: `${KIND_TITLE[k as Proposal["kind"]] ?? k} (${count(n)})`,
                      })),
                    ]}
                  />
                ) : null}
                <div className="relative">
                  <Search
                    className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint"
                    aria-hidden
                  />
                  <Input
                    type="search"
                    aria-label="Find a proposal (sample, target, words)"
                    placeholder="Find a sample, target…"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setShown(PAGE);
                    }}
                    className="h-7 w-52 pl-8 text-[13px]"
                  />
                </div>
              </div>
            </div>
            {filter ? (
              <div className="flex items-center gap-2 text-[13px] text-muted">
                <span>
                  Showing proposals about{" "}
                  <span className="font-medium text-fg">{filter.label}</span>
                </span>
                {onClearFilter ? (
                  <Button size="sm" variant="ghost" icon={<X />} onClick={onClearFilter}>
                    Show all
                  </Button>
                ) : null}
              </div>
            ) : null}
            {arriving ? (
              <p
                className="rounded-lg border border-info/25 bg-info-soft/50 px-3 py-1.5 text-[13px] text-fg"
                aria-live="polite"
              >
                Proposals are still arriving ({count(pendingAll.length)} so far). They stay in
                arrival order until the job ends; then the contradicted ones come first.
              </p>
            ) : null}
            <p className="text-xs text-faint" aria-live={arriving ? undefined : "polite"}>
              {filtered
                ? `${count(pending.length)} of ${count(pendingAll.length)} waiting`
                : `${count(pendingAll.length)} waiting`}
              {" · "}
              {arriving ? "in arrival order" : "contradicted first"}
              <span className="hidden sm:inline pointer-coarse:hidden">
                {" · "}
                <Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>a</Kbd> <Kbd>e</Kbd> <Kbd>x</Kbd> accept,
                edit, reject
              </span>
            </p>
          </div>
        ) : null}

        {pendingAll.length && !pending.length ? (
          <EmptyState compact icon={<Search />} title="No waiting proposal matches">
            Clear the filters to see all {count(pendingAll.length)}.
          </EmptyState>
        ) : null}

        {folded.length ? (
          <ul aria-label="Refuted proposals, folded" className="flex flex-col gap-2">
            {folded.map((g) => (
              <li
                key={g.key}
                className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <p className="text-[13px] text-muted">
                  <CheckTag status="contradicted" />{" "}
                  <span className="text-fg">{refutedWords(g)}</span> Each still waits for you: open
                  them one by one, or reject them together with one reason (Reject contradicted…
                  above).
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  className="self-start sm:self-center"
                  onClick={() => setUnfolded((s) => new Set([...s, g.key]))}
                >
                  Show all {count(g.ids.length)}
                </Button>
              </li>
            ))}
          </ul>
        ) : null}

        {listed.length ? (
          <ul aria-label={label} className="flex flex-col gap-3">
            <AnimatePresence initial={false} custom={manyLeaving}>
              {visible.map((p) => (
                <motion.li
                  key={p.id}
                  layout="position"
                  // No fade-in: a card is readable at full contrast from its first frame (axe
                  // measured cards still fading in). Only a card that leaves is animated.
                  initial={false}
                  variants={LEAVE}
                  exit="exit"
                  custom={manyLeaving}
                  transition={{ duration: 0.16, ease: "easeOut" }}
                >
                  <Present>
                    <ProposalCard
                      ref={(h) => {
                        if (h) refs.current.set(p.id, h);
                        else refs.current.delete(p.id);
                      }}
                      proposal={p}
                      quotes={lookup}
                      sheetCells={sheetCells}
                      resultsVisible={resultsVisible}
                      focused={focused?.id === p.id}
                      onFocusCard={() => setFocusAt({ id: p.id, index: visible.indexOf(p) })}
                      onAccept={(reason) => actions.accept(p.id, reason)}
                      onEdit={(edits, reason) => actions.edit(p.id, edits, reason)}
                      onReject={(reason) => actions.reject(p.id, reason)}
                      onCheckEdit={(edits) => checkEdit(p.id, edits)}
                      onAskMatters={() => void matters.ask(p.id)}
                      mattersJob={matters.jobOf(p.id)}
                      onOpenWell={onOpenWell}
                      editOptions={editOptions}
                      {...cardProps?.(p)}
                    >
                      {cardExtra?.(p)}
                    </ProposalCard>
                  </Present>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        ) : null}
        {listed.length > shown ? (
          <Button
            variant="secondary"
            className="self-center"
            onClick={() => setShown((s) => s + PAGE)}
          >
            Show {count(Math.min(PAGE, listed.length - shown))} more ({count(listed.length - shown)}{" "}
            not shown)
          </Button>
        ) : null}

        {!pendingAll.length ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 rounded-xl border border-ok/25 bg-ok-soft/50 p-4">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden />
              <div>
                <p className="text-sm font-semibold text-fg">Nothing is waiting in this stage</p>
                <p className="mt-0.5 text-[13px] text-muted">
                  Every proposal is decided ({count(decided.length)}). They are listed below with
                  the reasons given.
                </p>
              </div>
            </div>
            {allDecided}
          </div>
        ) : null}

        <DecidedList
          proposals={decided}
          quotes={lookup}
          sheetCells={sheetCells}
          resultsVisible={resultsVisible}
          onOpenWell={onOpenWell}
        />
      </div>
    </MotionConfig>
  );
}

/** Who decided and when, in words: "Rejected by you · 20 Oct 2026, 21:24 (2 h ago)". */
export function decidedLine(
  p: Pick<Proposal, "status" | "decided_by" | "decided_at" | "superseded_by">,
): string {
  const who =
    p.status === "superseded"
      ? `replaced by a newer proposal${p.superseded_by ? ` (${p.superseded_by})` : ""}`
      : p.decided_by === "human"
        ? `${STATUS_WORDS[p.status]} by ${deciderWords("human")}`
        : STATUS_WORDS[p.status];
  const when = p.decided_at ? ` · ${dateTime(p.decided_at)} (${relativeTime(p.decided_at)})` : "";
  return `${who.charAt(0).toUpperCase()}${who.slice(1)}${when}`;
}

const DECIDED_TONE = {
  accepted: "ok",
  edited: "ok",
  rejected: "neutral",
  superseded: "neutral",
  proposed: "accent",
} as const;

/**
 * What was already decided in the stage (folded, as the old Studio page had it): each accepted,
 * edited or rejected proposal with who decided, when, and the reason given; filters by kind and
 * decision; a line opens the read-only card.
 */
export function DecidedList({
  proposals,
  quotes,
  sheetCells,
  resultsVisible,
  onOpenWell,
}: {
  proposals: Proposal[];
  quotes?: ProposalCardProps["quotes"];
  sheetCells?: Record<string, string>;
  resultsVisible?: boolean;
  onOpenWell?: (well: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [shown, setShown] = useState(50);
  const [kind, setKind] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  if (!proposals.length) return null;
  const byStatus = new Map<string, number>();
  for (const p of proposals) byStatus.set(p.status, (byStatus.get(p.status) ?? 0) + 1);
  const byKind = new Map<string, number>();
  for (const p of proposals) byKind.set(p.kind, (byKind.get(p.kind) ?? 0) + 1);
  const listed = proposals.filter(
    (p) => (kind === "all" || p.kind === kind) && (status === "all" || p.status === status),
  );
  const chip = (active: boolean) =>
    cn(
      "inline-flex h-6 items-center gap-1 rounded-full border px-2.5 text-xs font-medium transition-colors",
      active
        ? "border-accent/40 bg-accent-soft text-accent-strong"
        : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg",
    );
  return (
    <section className="rounded-xl border border-line bg-surface">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left hover:bg-surface-2"
      >
        <ChevronRight
          aria-hidden
          className={cn("size-4 text-muted transition-transform duration-150", open && "rotate-90")}
        />
        <span className="text-sm font-semibold text-fg">
          Decided in this stage ({count(proposals.length)})
        </span>
        <span className="ml-auto flex flex-wrap justify-end gap-1.5">
          {[...byStatus].map(([s, n]) => (
            <Badge key={s} tone={DECIDED_TONE[s as Proposal["status"]]}>
              {STATUS_WORDS[s as Proposal["status"]]} {count(n)}
            </Badge>
          ))}
        </span>
      </button>
      {open ? (
        <div className="border-t border-line">
          <div className="flex flex-col gap-2 border-b border-line px-4 py-2.5">
            {byKind.size > 1 ? (
              <div role="group" aria-label="Show by kind" className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  aria-pressed={kind === "all"}
                  className={chip(kind === "all")}
                  onClick={() => setKind("all")}
                >
                  Every kind <span className="font-mono tabular">{count(proposals.length)}</span>
                </button>
                {[...byKind].map(([k, n]) => (
                  <button
                    key={k}
                    type="button"
                    aria-pressed={kind === k}
                    className={chip(kind === k)}
                    onClick={() => setKind(k)}
                  >
                    {KIND_TITLE[k as Proposal["kind"]] ?? k}{" "}
                    <span className="font-mono tabular">{count(n)}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {byStatus.size > 1 ? (
              <div role="group" aria-label="Show by decision" className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  aria-pressed={status === "all"}
                  className={chip(status === "all")}
                  onClick={() => setStatus("all")}
                >
                  Every decision
                </button>
                {[...byStatus].map(([st, n]) => (
                  <button
                    key={st}
                    type="button"
                    aria-pressed={status === st}
                    className={chip(status === st)}
                    onClick={() => setStatus(st)}
                  >
                    {STATUS_WORDS[st as Proposal["status"]]}{" "}
                    <span className="font-mono tabular">{count(n)}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <ol className="divide-y divide-line">
            {listed.slice(0, shown).map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  aria-expanded={openId === p.id}
                  onClick={() => setOpenId((id) => (id === p.id ? null : p.id))}
                  className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-left text-[13px] hover:bg-surface-2"
                >
                  <Badge tone={DECIDED_TONE[p.status]}>{STATUS_WORDS[p.status]}</Badge>
                  <span className="min-w-0 flex-1 text-fg">
                    {p.status === "edited"
                      ? describeProposal(p, effectivePayload(p))
                      : describeProposal(p)}
                  </span>
                  <CheckTag status={p.check.status} />
                  {p.status === "edited" ? (
                    <span className="basis-full pl-1 text-muted">
                      — as proposed: {describeProposal(p)}
                    </span>
                  ) : null}
                  {p.reason ? (
                    <span className="basis-full pl-1 text-muted">— reason: “{p.reason}”</span>
                  ) : null}
                  <span className="basis-full pl-1 text-xs text-faint">{decidedLine(p)}</span>
                </button>
                {openId === p.id ? (
                  <div className="px-3 pb-3">
                    <ProposalCard
                      proposal={p}
                      quotes={quotes}
                      sheetCells={sheetCells}
                      resultsVisible={resultsVisible}
                      onOpenWell={onOpenWell}
                      readOnly
                      headingLevel={4}
                    />
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
          {listed.length > shown ? (
            <div className="border-t border-line p-2 text-center">
              <Button size="sm" variant="ghost" onClick={() => setShown((s) => s + 100)}>
                Show more ({count(listed.length - shown)} not shown)
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

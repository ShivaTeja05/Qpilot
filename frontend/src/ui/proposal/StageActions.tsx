/**
 * A stage's two bulk actions and its confirm step. Each shows exactly what it covers first and
 * then does exactly that: "Accept all consistent…" accepts the listed ids (one record entry
 * each), "Reject contradicted AI calls…" rejects the listed ones with one reason (the AI's calls,
 * or, by the person's choice, every contradicted proposal, the rules' too), "Confirm this
 * stage…" shows what the confirm covers and waits for "Yes, confirm".
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, CheckCircle2, Lock, ShieldCheck, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError, api, unwrap, type Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import {
  CURVE_JUDGE,
  KIND_TITLE,
  STAGE_LABEL,
  describeProposal,
  type Proposal,
  type StageName,
} from "@/lib/vocab";
import { useFocusTarget } from "@/shell/actions";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Hash } from "../Copy";
import { ErrorPanel } from "../ErrorPanel";
import { LoadingBlock } from "../feedback";
import { Dialog } from "../overlay";
import { SegmentedControl, Textarea } from "../controls";
import { CheckTag } from "../tags";
import { toast } from "../Toaster";
import { MAX_REASON } from "./ProposalCard";
import { StageSummary } from "./summary";
import { useStageProposals, type ConfirmableStage, type InboxStage } from "./hooks";

type BulkAction = "accept" | "reject";
/** Reject: the contradicted proposals of a model or an agent (`ai`), or every one (`all`). */
export type BulkMakers = Schemas["BulkRequest"]["makers"];
type StageView = Schemas["StageView"];

/** The label of the reject button: the spec's words while an AI call is contradicted. */
export const REJECT_AI_LABEL = "Reject contradicted AI calls…";
export const REJECT_ALL_LABEL = "Reject contradicted proposals…";

const SCOPE_WORDS: Record<BulkMakers, string> = {
  ai: "Only proposals made by a model or an agent are listed.",
  all: "Every contradicted proposal is listed, the ones qPilot's rules made too.",
};

/** Who made a proposal, in a word or two (for a list line). */
function makerWord(m: Proposal["made_by"]): string {
  if (m.kind === "rule") return "rule";
  if (m.kind === "agent") return m.agent ? `agent ${m.agent}` : "agent";
  return m.provider === CURVE_JUDGE ? "Curve Judge" : "model";
}

const BULK: Record<
  BulkAction,
  { button: string; title: string; go: (n: number) => string; empty: string }
> = {
  accept: {
    button: "Accept all consistent…",
    title: "Accept all consistent proposals",
    go: (n) => `Accept these ${count(n)}`,
    empty: "No waiting proposal is consistent with the engine's checks.",
  },
  reject: {
    button: REJECT_AI_LABEL,
    title: "Reject contradicted proposals",
    go: (n) => `Reject these ${count(n)}`,
    empty: "No waiting proposal from a model or an agent is contradicted.",
  },
};

/** One bulk action: its button, then a dialog listing exactly what it will do. */
export function BulkAction({
  sid,
  stage,
  action,
  disabled,
  size = "md",
  aiContradicted,
  contradicted,
}: {
  sid: string;
  stage: InboxStage;
  action: BulkAction;
  disabled?: boolean;
  size?: "sm" | "md";
  /** Reject: how many contradicted proposals of a model or an agent wait (labels the scopes). */
  aiContradicted?: number;
  /** Reject: how many contradicted proposals wait in all, the rules' too. */
  contradicted?: number;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [changed, setChanged] = useState(false);
  // Reject's scope: the AI's calls while any is contradicted, else every contradicted proposal.
  const [chosen, setChosen] = useState<BulkMakers | null>(null);
  const makers: BulkMakers =
    chosen ?? (aiContradicted === 0 && (contradicted ?? 0) > 0 ? "all" : "ai");
  const button = useRef<HTMLButtonElement>(null);
  const label =
    action === "reject" && makers === "all" && aiContradicted === 0
      ? REJECT_ALL_LABEL
      : BULK[action].button;
  useFocusTarget(BULK[action].button, button);
  const list = useQuery({
    queryKey: ["w", sid, "bulk", action, stage, action === "reject" ? makers : "consistent"],
    // Not while its own write runs: every proposal it decides re-reads the session.
    enabled: open && !busy,
    queryFn: async () => {
      const query = action === "reject" ? { stage, makers } : { stage };
      const data = await unwrap(
        api.GET("/api/sessions/{sid}/bulk/{action}", { params: { path: { sid, action }, query } }),
      );
      // The scope travels with the list, so the write names exactly the list shown.
      return { ...data, makers };
    },
    staleTime: 0,
  });
  const words = BULK[action];
  const ids = list.data?.ids ?? [];
  const go = async () => {
    if (!list.data) return;
    setBusy(true);
    setError(null);
    try {
      const done = await unwrap(
        api.POST("/api/sessions/{sid}/bulk/{action}", {
          params: { path: { sid, action } },
          // Exactly the list shown, with the scope it was listed under.
          body: {
            stage,
            ids,
            reason: reason.trim(),
            makers: list.data.makers,
            expected_head: list.data.head,
          },
        }),
      );
      await refreshWorkspace(qc, sid);
      toast.success(done.message);
      setOpen(false);
      setReason("");
    } catch (err) {
      if (err instanceof ApiError && err.stale) {
        // The list changed (another tab or an agent): show the current one, decide again.
        setChanged(true);
        void list.refetch();
        void refreshWorkspace(qc, sid);
      } else if (err instanceof ApiError && err.needsKey) {
        reportWriteError(qc, err, sid);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  };
  const needsReason = action === "reject";
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) {
          setError(null);
          setChanged(false);
        }
      }}
      size="lg"
      trigger={
        <Button
          ref={button}
          size={size}
          variant="secondary"
          icon={action === "accept" ? <CheckCheck /> : <XCircle />}
          disabled={disabled}
          data-action={words.button}
        >
          {label}
        </Button>
      }
      title={
        action === "accept"
          ? words.title
          : makers === "ai"
            ? "Reject the AI's contradicted calls"
            : words.title
      }
      description={
        action === "accept"
          ? "Exactly the proposals listed here are accepted, one record entry each."
          : `Exactly these proposals are rejected, one record entry each, all with the one reason you give. ${SCOPE_WORDS[makers]}`
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={action === "accept" ? "primary" : "danger"}
            onClick={() => void go()}
            loading={busy}
            disabled={!ids.length || list.isFetching || (needsReason && !reason.trim())}
          >
            {words.go(ids.length)}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {action === "reject" ? (
          <div className="flex flex-col gap-1.5">
            <span id={`bulk-scope-${sid}-${stage}`} className="text-[13px] font-medium text-fg">
              Which contradicted proposals
            </span>
            <SegmentedControl<BulkMakers>
              label="Which contradicted proposals"
              value={makers}
              onValueChange={(v) => {
                setChosen(v);
                setChanged(false);
                setError(null);
              }}
              options={[
                {
                  value: "ai",
                  label: `The AI's calls${aiContradicted != null ? ` · ${count(aiContradicted)}` : ""}`,
                  title:
                    "Contradicted proposals made by a model (the Design Interpreter, the Curve Judge) or an agent",
                },
                {
                  value: "all",
                  label: `Every contradicted proposal, rules included${contradicted != null ? ` · ${count(contradicted)}` : ""}`,
                  title: "Also the contradicted proposals qPilot's own rules made",
                },
              ]}
            />
          </div>
        ) : null}
        {changed ? (
          <p
            role="status"
            className="rounded-lg border border-info/30 bg-info-soft px-3 py-2 text-[13px] text-fg"
          >
            The list changed since it was shown (another tab or an agent decided something). This is
            the current list; look at it again before you go on.
          </p>
        ) : null}
        {list.isPending ? <LoadingBlock label="Listing the proposals" /> : null}
        {list.error ? (
          <ErrorPanel error={list.error} compact onRetry={() => void list.refetch()} />
        ) : null}
        {list.data ? (
          ids.length ? (
            <>
              <p className="text-[13px] text-muted">{list.data.message}</p>
              <ProposalLines
                proposals={list.data.proposals}
                descriptions={list.data.descriptions}
                showMaker={action === "reject"}
              />
            </>
          ) : (
            <p className="text-[13px] text-muted">
              {action === "reject" && makers === "all"
                ? "No waiting proposal of this stage is contradicted."
                : words.empty}
            </p>
          )
        ) : null}
        {needsReason && ids.length ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`bulk-reason-${sid}`} className="text-[13px] font-medium text-fg">
              One reason for all of them
            </label>
            <Textarea
              id={`bulk-reason-${sid}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={MAX_REASON}
              showCount
              rows={2}
              required
            />
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setReason("Contradicted by the engine check")}
                className="rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-xs text-muted hover:border-line-strong hover:text-fg"
              >
                Contradicted by the engine check
              </button>
            </div>
          </div>
        ) : null}
        {error ? <ErrorPanel error={error} compact title="Not done" /> : null}
      </div>
    </Dialog>
  );
}

/** A numbered list of proposals with their checks: what a bulk action or a confirm covers. */
export function ProposalLines({
  proposals,
  descriptions,
  max = 400,
  showMaker,
}: {
  proposals: Proposal[];
  descriptions?: Record<string, string>;
  max?: number;
  /** Say who made each one (rule, model, Curve Judge, agent). */
  showMaker?: boolean;
}) {
  const kinds = new Map<string, number>();
  for (const p of proposals) kinds.set(p.kind, (kinds.get(p.kind) ?? 0) + 1);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {[...kinds].map(([k, n]) => (
          <Badge key={k}>
            {KIND_TITLE[k as Proposal["kind"]] ?? k} · {count(n)}
          </Badge>
        ))}
      </div>
      <ol className="max-h-[46vh] list-decimal divide-y divide-line overflow-y-auto rounded-lg border border-line pl-9 qp-scroll">
        {proposals.slice(0, max).map((p) => (
          <li
            key={p.id}
            className="py-1.5 pr-3 text-[13px] text-fg marker:text-xs marker:text-faint"
          >
            <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="min-w-0">{descriptions?.[p.id] ?? describeProposal(p)}</span>
              <span className="flex shrink-0 items-center gap-2">
                {showMaker ? (
                  <span className="text-xs text-muted">made by {makerWord(p.made_by)}</span>
                ) : null}
                <CheckTag status={p.check.status} />
              </span>
            </span>
          </li>
        ))}
      </ol>
      {proposals.length > max ? (
        <p className="text-xs text-muted">… and {count(proposals.length - max)} more.</p>
      ) : null}
    </div>
  );
}

/**
 * Both bulk actions of a stage, side by side; each is off when the inbox shows nothing it
 * would cover (the dialog still lists exactly what the server says it covers).
 */
export function BulkActions({
  sid,
  stage,
  pending,
}: {
  sid: string;
  stage: InboxStage;
  /** Optional: how many proposals wait (0 turns both off); the inbox's own list decides otherwise. */
  pending?: number;
}) {
  const list = useStageProposals(sid, stage);
  const waiting = (list.data?.proposals ?? []).filter(
    (p) => p.status === "proposed" && p.kind !== "stage.confirm",
  );
  const consistent = waiting.filter((p) => p.check.status === "consistent").length;
  const contradicted = waiting.filter((p) => p.check.status === "contradicted");
  const aiContradicted = contradicted.filter((p) => p.made_by.kind !== "rule").length;
  const none = pending === 0;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <BulkAction sid={sid} stage={stage} action="accept" disabled={none || !consistent} />
      <BulkAction
        sid={sid}
        stage={stage}
        action="reject"
        disabled={none || !contradicted.length}
        aiContradicted={aiContradicted}
        contradicted={contradicted.length}
      />
    </div>
  );
}

/**
 * The stage's confirm: confirmed (a badge), not reachable (why), proposals still waiting (how
 * many), or "Confirm this stage…" → what it covers → "Yes, confirm".
 */
export function ConfirmStage({
  sid,
  stage,
  status,
  size = "md",
}: {
  sid: string;
  stage: ConfirmableStage;
  /** The stage's state from the workspace frame. */
  status: StageView | undefined;
  size?: "sm" | "md";
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<Schemas["ConfirmView"] | null>(null);
  const [busy, setBusy] = useState<"prepare" | "confirm" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const button = useRef<HTMLButtonElement>(null);
  useFocusTarget("Confirm this stage…", button);
  const label = STAGE_LABEL[stage as StageName] ?? stage;
  const waiting = useQuery({
    queryKey: ["w", sid, "confirm", stage],
    enabled: Boolean(status?.open && !status.confirmed),
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/confirm/{stage}", { params: { path: { sid, stage } } })),
  });

  if (!status) return null;
  if (status.confirmed) {
    return (
      <Badge tone="ok" icon={<CheckCircle2 />} className="h-7 px-2.5 text-[13px]">
        {label} confirmed
      </Badge>
    );
  }
  if (!status.open) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
        <Lock className="size-3.5" aria-hidden /> {label} is not open yet
      </span>
    );
  }
  const ready = waiting.data?.ready ? waiting.data : null;
  // The server counts a waiting confirm step as pending; it is not a proposal to decide first.
  const waitingProposals = Math.max(0, status.pending - (ready ? 1 : 0));
  const blocked = !ready && (waitingProposals > 0 || status.blockers.length > 0);

  const prepare = async () => {
    setError(null);
    if (ready) {
      setView(ready);
      setOpen(true);
      return;
    }
    setBusy("prepare");
    try {
      const v = await unwrap(
        api.POST("/api/sessions/{sid}/confirm/{stage}", { params: { path: { sid, stage } } }),
      );
      setView(v);
      setOpen(true);
      void qc.invalidateQueries({ queryKey: ["w", sid, "confirm", stage] });
    } catch (err) {
      reportWriteError(qc, err, sid);
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    if (!view?.proposal) return;
    setBusy("confirm");
    setError(null);
    try {
      const done = await unwrap(
        api.POST("/api/sessions/{sid}/confirm/{stage}/accept", {
          params: { path: { sid, stage } },
          body: { proposal_id: view.proposal.id, expected_head: view.head },
        }),
      );
      await refreshWorkspace(qc, sid);
      toast.success(done.message);
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.stale) {
        void refreshWorkspace(qc, sid);
        try {
          setView(
            await unwrap(
              api.GET("/api/sessions/{sid}/confirm/{stage}", { params: { path: { sid, stage } } }),
            ),
          );
        } catch {
          /* the panel below says what happened */
        }
      }
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const hash = view?.proposal?.payload?.design_hash;
  return (
    <>
      <div className="flex flex-col items-start gap-1">
        <Button
          ref={button}
          size={size}
          variant={blocked ? "secondary" : "primary"}
          icon={<ShieldCheck />}
          onClick={() => void prepare()}
          loading={busy === "prepare"}
          disabled={blocked}
          data-action="Confirm this stage…"
        >
          {ready ? "Review the confirm step…" : "Confirm this stage…"}
        </Button>
        {blocked ? (
          <span className="text-xs text-muted">
            {waitingProposals
              ? `Decide the ${count(waitingProposals)} waiting proposal${waitingProposals === 1 ? "" : "s"} first.`
              : `${status.blockers[0]?.replace(/^./, (c) => c.toUpperCase()) ?? ""}.`}
          </span>
        ) : null}
      </div>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setError(null);
        }}
        size="lg"
        title={`Confirm the ${label.toLowerCase()}`}
        description={view?.message}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy === "confirm"}>
              Not now
            </Button>
            <Button
              variant="primary"
              icon={<ShieldCheck />}
              onClick={() => void confirm()}
              loading={busy === "confirm"}
              disabled={!view?.ready}
            >
              Yes, confirm
            </Button>
          </>
        }
      >
        {view ? (
          <div className="flex flex-col gap-3">
            {stage === "design" || stage === "curves" ? (
              <p className="text-[13px] text-muted">
                {stage === "design"
                  ? "Confirming freezes this design. The curves stage opens next; results stay hidden until the curves are confirmed too."
                  : "Confirming freezes the amplification calls. With the design confirmed as well, the results are analysed and shown."}{" "}
                A decision made later re-opens the stage.
              </p>
            ) : null}
            {typeof hash === "string" ? (
              <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
                It confirms the {stage === "design" ? "design" : "curve calls"} with fingerprint{" "}
                <Hash value={hash} length={12} />
              </p>
            ) : null}
            {view.warnings.map((w) => (
              <p
                key={w}
                className={cn(
                  "rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] text-fg",
                )}
              >
                {w}
              </p>
            ))}
            {stage === "design" || stage === "curves" ? (
              <section
                aria-labelledby={`confirm-summary-${sid}`}
                className="rounded-lg border border-line bg-surface-2 p-3"
              >
                <h3
                  id={`confirm-summary-${sid}`}
                  className="mb-2 text-[13px] font-semibold text-fg"
                >
                  {stage === "design" ? "The design this gives" : "The curve calls this gives"}
                </h3>
                <StageSummary stage={stage} proposals={view.covers} />
              </section>
            ) : null}
            {view.covers.length ? (
              <>
                <p className="text-[13px] font-medium text-fg">
                  It covers {count(view.covers.length)} accepted proposal
                  {view.covers.length === 1 ? "" : "s"}:
                </p>
                <ProposalLines proposals={view.covers} descriptions={view.descriptions} />
              </>
            ) : (
              <p className="text-[13px] text-muted">
                It covers no accepted proposal of this stage.
              </p>
            )}
            {error ? (
              <ErrorPanel
                error={error}
                compact
                title={error instanceof ApiError && error.stale ? undefined : "Not confirmed"}
              />
            ) : null}
          </div>
        ) : null}
      </Dialog>
    </>
  );
}

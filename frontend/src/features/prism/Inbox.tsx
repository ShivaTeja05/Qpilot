/**
 * The Prism stages' proposals (the drafted project, the round trip's questions) with Accept and
 * Reject as a person. Each card says what accepting does, the engine's numbers for it, its level
 * and who made it. To be rendered through design's shared ProposalCard once it lands; the Prism
 * consequence block stays here.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useId, useState } from "react";
import { api, ApiError, unwrap } from "@/api/client";
import { Badge, Button, Card, CardBody, Field, LevelTag, Textarea, toast } from "@/ui";
import { errorMessage } from "@/ui";
import {
  describeProposal,
  effectivePayload,
  KIND_TITLE,
  makerText,
  STATUS_WORDS,
} from "@/lib/vocab";
import type { Proposal } from "./api";
import { PrismConsequence } from "./Consequence";

/** `keep` records a value changed in Prism as a manual edit (an edit of the proposal's action). */
type Action = "accept" | "reject" | "keep";

/** Accept or reject one proposal as a person; the inbox head guards against a stale view. */
export function useDecide(sid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      pid,
      action,
      reason,
      head,
    }: {
      pid: string;
      action: Action;
      reason: string;
      head: string | null;
    }) => {
      const params = { path: { sid, pid } };
      const body = { reason, expected_head: head };
      if (action === "keep") {
        const edit = { ...body, edits: { action: "keep" } };
        return unwrap(api.POST("/api/sessions/{sid}/proposals/{pid}/edit", { params, body: edit }));
      }
      return unwrap(
        action === "accept"
          ? api.POST("/api/sessions/{sid}/proposals/{pid}/accept", { params, body })
          : api.POST("/api/sessions/{sid}/proposals/{pid}/reject", { params, body }),
      );
    },
    onSuccess: (done) => {
      toast.success(done.message);
      void qc.invalidateQueries({ queryKey: ["w", sid] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.stale) {
        toast.info(
          "Something was decided since you loaded this (another tab or an agent). Here is the current state.",
        );
      } else {
        toast.error(errorMessage(error));
      }
      void qc.invalidateQueries({ queryKey: ["w", sid] });
    },
  });
}

/** The question a proposal asks (round trip), or its proposal in words. */
export function proposalWords(p: Proposal): string {
  const payload = effectivePayload(p);
  if (typeof payload.question === "string" && payload.question) return payload.question;
  return describeProposal(p, payload);
}

export function ProposalItem({
  sid,
  proposal,
  head,
  note,
}: {
  sid: string;
  proposal: Proposal;
  head: string | null;
  /** A line above the card's words (e.g. "About an earlier analysis"). */
  note?: string;
}) {
  const decide = useDecide(sid);
  const [mode, setMode] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const pending = proposal.status === "proposed";
  const roundTrip = proposal.kind !== "prism.project";
  // the server refuses an exclusion accepted without its reason, and every rejection without one
  const needsReason =
    mode === "reject" || (mode === "accept" && proposal.kind === "prism.exclusion_reason");
  const actions: { action: Action; label: string }[] =
    proposal.kind === "prism.exclusion_reason"
      ? [
          { action: "accept", label: "Exclude it" },
          { action: "reject", label: "Keep the value" },
        ]
      : proposal.kind === "prism.value_edit"
        ? [
            { action: "accept", label: "Restore qPilot's value" },
            { action: "keep", label: "Keep it as a manual edit" },
          ]
        : [
            { action: "accept", label: "Accept" },
            { action: "reject", label: "Reject" },
          ];
  const labelOf = (a: Action) => actions.find((x) => x.action === a)?.label ?? a;

  const submit = () => {
    if (!mode) return;
    decide.mutate(
      { pid: proposal.id, action: mode, reason: reason.trim(), head },
      {
        onSuccess: () => {
          setMode(null);
          setReason("");
        },
      },
    );
  };

  return (
    <Card
      as="article"
      aria-label={KIND_TITLE[proposal.kind]}
      className={pending ? undefined : "bg-surface-2"}
    >
      <CardBody className="flex flex-col gap-3 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wider text-faint">
            {KIND_TITLE[proposal.kind]}
          </span>
          <Badge tone={pending ? "accent" : proposal.status === "rejected" ? "neutral" : "ok"}>
            {STATUS_WORDS[proposal.status]}
          </Badge>
          <LevelTag level={proposal.level} className="ml-auto" />
        </div>
        {note ? <p className="text-[12px] text-muted">{note}</p> : null}
        <p className="text-[14px] leading-snug text-fg">{proposalWords(proposal)}</p>

        {roundTrip ? (
          <section aria-label="What it changes" className="rounded-lg border border-line p-3">
            <h4 className="mb-2 text-[12px] font-semibold text-fg">What accepting it changes</h4>
            <PrismConsequence proposal={proposal} />
          </section>
        ) : null}

        {proposal.reasons.length ? (
          <ul className="list-disc pl-5 text-[12.5px] text-muted">
            {proposal.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        ) : null}
        {proposal.check.note ? (
          <p className="text-[12.5px] text-muted">{proposal.check.note}</p>
        ) : null}
        {proposal.reason ? (
          <p className="text-[12.5px] text-fg">
            <span className="text-muted">Reason given: </span>
            {proposal.reason}
          </p>
        ) : null}

        {pending ? (
          mode ? (
            <div className="flex flex-col gap-2">
              <Field
                label={needsReason ? "Reason (kept in the record)" : "Reason (optional)"}
                htmlFor={reasonId}
                hint={
                  mode === "accept" && proposal.kind === "prism.exclusion_reason"
                    ? "Say why this value was excluded in Prism; whether that is justified is your call."
                    : undefined
                }
              >
                <Textarea
                  id={reasonId}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={500}
                  showCount
                  rows={2}
                  autoFocus
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant={mode === "accept" ? "primary" : "secondary"}
                  size="sm"
                  loading={decide.isPending}
                  disabled={needsReason && !reason.trim()}
                  onClick={submit}
                >
                  {labelOf(mode)}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setMode(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {actions.map(({ action, label }, i) => (
                <Button
                  key={action}
                  size="sm"
                  variant={i === 0 ? "primary" : "secondary"}
                  icon={i === 0 ? <Check /> : <X />}
                  onClick={() => setMode(action)}
                >
                  {label}…
                </Button>
              ))}
            </div>
          )
        ) : null}
        <p className="border-t border-line pt-2 text-[12px] text-faint">
          {makerText(proposal.made_by)}
        </p>
      </CardBody>
    </Card>
  );
}

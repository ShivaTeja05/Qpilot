/**
 * One agent request waiting for a person: what the agent asked for and why, then Approve or
 * Turn down, each with the person's own reason (required, kept in the record).
 */
import { Bot, Check, X } from "lucide-react";
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { dateTime, relativeTime, shortHash } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { cardTitle, optionLabel } from "@/features/record/words";
import { Button, ErrorPanel, Kbd, Textarea, toast } from "@/ui";
import { useApprove, useTurnDown } from "./api";
import type { PendingRequest } from "./types";

const MAX_REASON = 500;

type Mode = "approve" | "turn_down" | null;

export function RequestItem({
  request,
  now,
  studyNote,
  seeCard,
}: {
  request: PendingRequest;
  now: number;
  /** Which study it is about, when that is not the open one. */
  studyNote?: ReactNode;
  /** A link to the card in Results (what each option changes). */
  seeCard?: ReactNode;
}) {
  const [mode, setMode] = useState<Mode>(null);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const approve = useApprove();
  const turnDown = useTurnDown();
  const busy = approve.isPending || turnDown.isPending;
  const error = mode === "approve" ? approve.error : mode === "turn_down" ? turnDown.error : null;
  const title = cardTitle(request);
  const option = optionLabel(request);
  const trimmed = reason.trim();

  const submit = () => {
    if (!mode || !trimmed || busy) return;
    const call = mode === "approve" ? approve : turnDown;
    call.mutate(
      { request, reason: trimmed },
      {
        onSuccess: (outcome) => {
          if (outcome.status === "stale") {
            toast.warning("Something was decided on this card first; here is the current state.");
            return;
          }
          toast.success(
            mode === "approve" ? `Approved: ${title} → ${option}` : `Turned down: ${title} → ${option}`,
            { description: outcome.chain_head ? `Added to the record (chain ${shortHash(outcome.chain_head)}).` : undefined },
          );
          setMode(null);
          setReason("");
        },
      },
    );
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
    if (e.key === "Escape") setMode(null);
  };

  return (
    <li className="rounded-xl border border-warn/30 bg-surface">
      <div className="flex items-start gap-3 p-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full border border-info/40 text-info [&_svg]:size-4" aria-hidden>
          <Bot />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <p className="text-[13px] text-muted">
              <span className="font-medium text-fg">{request.agent || "An agent"}</span> asks for a choice that can change a conclusion
              {studyNote ? <> · {studyNote}</> : null}
            </p>
            <time className="text-xs text-muted" dateTime={request.at} title={dateTime(request.at)}>
              {relativeTime(request.at, now)}
            </time>
          </div>
          <h3 className="mt-1.5 text-sm font-semibold text-fg">{title}</h3>
          <p className="mt-0.5 text-[13px] text-muted">
            Use <span className="font-medium text-fg">{option}</span>
            {request.option_label && request.option_label !== request.option ? (
              <span className="ml-1.5 font-mono text-[11.5px] text-faint">{request.option}</span>
            ) : null}
          </p>
          {request.reason ? (
            <blockquote className="mt-2 border-l-2 border-info/40 pl-3 text-[13px] text-fg">
              <span className="sr-only">The agent's reason: </span>
              {request.reason}
            </blockquote>
          ) : null}

          {mode ? (
            <div className="mt-3 flex flex-col gap-2">
              <label htmlFor={reasonId} className="text-[13px] font-medium text-fg">
                {mode === "approve" ? "Why you approve it" : "Why you turn it down"}
                <span className="ml-1 font-normal text-muted">(required, kept in the record)</span>
              </label>
              <Textarea
                id={reasonId}
                autoFocus
                rows={2}
                maxLength={MAX_REASON}
                showCount
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={onKey}
              />
              {error ? <ErrorPanel compact error={error} /> : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={mode === "approve" ? "primary" : "danger"}
                  size="sm"
                  loading={busy}
                  disabled={!trimmed}
                  onClick={submit}
                  icon={mode === "approve" ? <Check /> : <X />}
                >
                  {mode === "approve" ? `Approve: use ${option}` : "Turn it down"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setMode(null)} disabled={busy}>
                  Cancel
                </Button>
                <span className="ml-auto hidden text-xs text-faint sm:inline">
                  <Kbd>{MOD}</Kbd> <Kbd>Enter</Kbd> to confirm
                </span>
              </div>
            </div>
          ) : (
            <div className={cn("mt-3 flex flex-wrap items-center gap-2")}>
              <Button size="sm" variant="primary" icon={<Check />} onClick={() => setMode("approve")}>
                Approve…
              </Button>
              <Button size="sm" variant="secondary" icon={<X />} onClick={() => setMode("turn_down")}>
                Turn down…
              </Button>
              {seeCard}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * Review the draft before anything is recorded: what each change does, the engine's check of
 * each (consistent / contradicted / cannot check, with its words), the waiting proposals it
 * settles, and what is refused. One reason for all of it; "Record" writes it as the person's
 * decisions (one record entry per item, all or nothing).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { count } from "@/lib/format";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { Badge, Button, CheckTag, Dialog, ErrorPanel, LoadingBlock, Textarea, toast } from "@/ui";
import { MAX_REASON } from "@/ui/proposal";
import { withoutItem, type Draft, type EditItem } from "./draft";
import { checkDesign, setDesign, type DesignPlan } from "./editorApi";

const QUICK_REASONS = [
  "As pipetted: my plate layout",
  "From my lab notebook",
  "From the sample sheet I keep",
];

const ACTION_WORDS: Record<string, string> = {
  new: "your choice, recorded",
  accept: "accepts the waiting proposal that says the same",
  keep: "already so; rejects the waiting proposals that say otherwise",
  unchanged: "already so; nothing to record",
};

export function ReviewDialog({
  sid,
  draft,
  open,
  onOpenChange,
  onRecorded,
  onDraft,
}: {
  sid: string;
  draft: Draft;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** After the changes are recorded (the draft is cleared by the caller). */
  onRecorded: () => void;
  onDraft: (next: Draft) => void;
}) {
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [reason, setReason] = useState("");
  // "Record them anyway" holds for the draft it was given for, never for a later one.
  const [anywayFor, setAnywayFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState(false);
  const items: EditItem[] = [...draft.values()];
  const key = items.map((i) => `${i.kind}|${i.subject}|${JSON.stringify(i.payload)}`).join("\n");
  // The engine's check of exactly this draft, read when the dialog opens (writes nothing).
  const checked = useQuery({
    queryKey: ["w", sid, "design-check", key],
    enabled: open && items.length > 0,
    queryFn: () => checkDesign(sid, items),
    staleTime: 0,
    gcTime: 0,
  });
  const plan: DesignPlan | null = checked.data ?? null;
  const anyway = anywayFor === key;
  const check = () => void checked.refetch();
  const refused = plan?.items.filter((p) => p.action === "refused") ?? [];
  const toRecord = plan?.items.filter((p) => p.action === "new" || p.action === "accept") ?? [];
  const settled = plan?.items.filter((p) => p.action === "keep" || p.action === "unchanged") ?? [];
  const contradicted = toRecord.filter((p) => p.check?.status === "contradicted");
  const writes = toRecord.length + (plan?.n_rejects ?? 0);
  const ready = plan && !refused.length && writes > 0 && (!contradicted.length || anyway);

  const record = async () => {
    if (!plan) return;
    if (!reason.trim()) {
      setMissing(true);
      document.getElementById(`design-reason-${sid}`)?.focus();
      return;
    }
    setBusy(true);
    try {
      const done = await setDesign(sid, items, reason.trim(), plan.head, anyway);
      await refreshWorkspace(qc, sid);
      toast.success(done.message);
      setReason("");
      onRecorded();
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError && err.stale) {
        void refreshWorkspace(qc, sid);
        toast.info("Something was decided since you checked", {
          description: "Here is the check again on the current inbox: look again, then record.",
        });
        void check();
      } else if (err instanceof ApiError && err.needsKey) {
        reportWriteError(qc, err, sid);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (o) setError(null);
        onOpenChange(o);
      }}
      size="xl"
      title="Review and record your changes"
      description="The engine checks every change first. Nothing is recorded until you press Record; then each change is your decision, with your reason, in the record."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!ready} onClick={() => void record()}>
            {toRecord.length
              ? `Record ${count(toRecord.length)} change${toRecord.length === 1 ? "" : "s"}`
              : writes
                ? `Reject ${count(writes)} waiting proposal${writes === 1 ? "" : "s"}`
                : "Nothing to record"}
          </Button>
        </>
      }
    >
      {error || checked.error ? (
        <ErrorPanel error={error ?? checked.error} compact onRetry={() => void check()} />
      ) : null}
      {!plan && !error && !checked.error ? (
        <LoadingBlock label="The engine is checking your changes" lines={4} />
      ) : null}
      {plan ? (
        <div className="flex flex-col gap-4">
          <p className="text-[13px] text-fg">{plan.message}</p>
          {refused.length ? (
            <section aria-labelledby="refused-head" className="flex flex-col gap-2">
              <h3
                id="refused-head"
                className="flex items-center gap-1.5 text-sm font-semibold text-danger"
              >
                <XCircle className="size-4" aria-hidden /> Refused ({count(refused.length)})
              </h3>
              <ul className="flex flex-col gap-1.5 text-[13px]">
                {refused.map((p) => (
                  <li
                    key={`${p.kind}|${p.subject}`}
                    className="rounded-lg border border-danger/25 bg-danger-soft/40 px-3 py-2"
                  >
                    <p className="text-fg">{p.words}</p>
                    <p className="text-muted">{p.refusal}</p>
                  </li>
                ))}
              </ul>
              <div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    // The draft changes, so the check (keyed by the draft) runs again.
                    let next = draft;
                    for (const p of refused) next = withoutItem(next, p);
                    onDraft(next);
                  }}
                >
                  Remove the refused changes
                </Button>
              </div>
            </section>
          ) : null}
          {toRecord.length ? (
            <section aria-labelledby="record-head" className="flex flex-col gap-2">
              <h3
                id="record-head"
                className="flex items-center gap-1.5 text-sm font-semibold text-fg"
              >
                <CheckCircle2 className="size-4 text-ok" aria-hidden /> To record (
                {count(toRecord.length)})
              </h3>
              {/* A list that scrolls is reachable with the keyboard (axe scrollable-region-focusable). */}
              <ul
                tabIndex={0}
                aria-labelledby="record-head"
                className="flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-lg text-[13px] outline-none qp-scroll focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {toRecord.map((p) => (
                  <li
                    key={`${p.kind}|${p.subject}`}
                    className="flex flex-col gap-1 rounded-lg border border-line px-3 py-2"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="min-w-0 text-fg">{p.words}</span>
                      {p.check ? <CheckTag status={p.check.status} /> : null}
                    </div>
                    <p className="text-xs text-muted">
                      {ACTION_WORDS[p.action]}
                      {p.rejects.length
                        ? ` · rejects ${count(p.rejects.length)} waiting proposal${p.rejects.length === 1 ? "" : "s"} that say${p.rejects.length === 1 ? "s" : ""} otherwise`
                        : ""}
                      {p.check?.note ? ` · engine: ${p.check.note}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {settled.length ? (
            <details className="text-[13px] text-muted">
              <summary className="cursor-pointer">
                {count(settled.length)} already so
                {settled.some((p) => p.rejects.length)
                  ? " (waiting proposals that say otherwise are rejected)"
                  : ""}
              </summary>
              <ul className="mt-1 list-disc pl-5">
                {settled.slice(0, 50).map((p) => (
                  <li key={`${p.kind}|${p.subject}`}>
                    {p.words} — {ACTION_WORDS[p.action]}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {contradicted.length ? (
            <label className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft/40 p-3 text-[13px] text-fg">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-[var(--accent)]"
                checked={anyway}
                onChange={(e) => setAnywayFor(e.target.checked ? key : null)}
              />
              <span>
                <ShieldAlert className="mr-1 inline size-4 text-warn" aria-hidden />
                The engine's check contradicts {count(contradicted.length)} of these. I have read
                why, and record them anyway with my reason.
              </span>
            </label>
          ) : null}
          {writes ? (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`design-reason-${sid}`} className="text-[13px] font-medium text-fg">
                Why (kept with every change in the record)
              </label>
              <div className="flex flex-wrap gap-1.5">
                {QUICK_REASONS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => {
                      setReason(r);
                      setMissing(false);
                    }}
                    className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs text-muted hover:border-line-strong hover:text-fg"
                  >
                    {r}
                  </button>
                ))}
              </div>
              <Textarea
                id={`design-reason-${sid}`}
                rows={2}
                value={reason}
                maxLength={MAX_REASON}
                onChange={(e) => {
                  setReason(e.target.value);
                  setMissing(false);
                }}
                aria-invalid={missing}
              />
              {missing ? (
                <p className="text-xs text-danger" role="alert">
                  Say why first: the reason is kept with every change.
                </p>
              ) : null}
            </div>
          ) : (
            <Badge tone="neutral">Everything here is already in the design.</Badge>
          )}
        </div>
      ) : null}
    </Dialog>
  );
}

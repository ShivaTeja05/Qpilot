/**
 * Applying a Trace decision in a Studio session (`POST …/where-to-look/decide` and `…/put-back`,
 * Run Gate's path): a person picks what to do at a place and says why; a set-aside leaves the
 * place's wells out of the analysis (one curve exclusion per well, accepted by the person with
 * the reason, in the session's record) and the study is analysed again, with the person's
 * Decision Card choices carried to the new analysis. "Keep" puts back what a person left out at
 * the place, or records the keep. Reading a well from the sample's other reference wells is a
 * what-if only: the analysis keeps a well or leaves it out, so that option is shown, not chosen.
 *
 * {@link SetAsideList} lists what a person set aside from Trace that is out of the analysis now,
 * each with Put the wells back: it does not depend on what is traced (a gene whose comparison a
 * set-aside removed cannot be traced any more, and its wells can still be put back).
 */
import { useQueryClient } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { count, dateTime, plural } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { refreshWorkspace } from "@/shell/writes";
import { Badge, Button, KeyHint, Textarea, toast } from "@/ui";
import {
  usePutBack,
  useSetAside,
  type SetAside,
  type TraceDecided,
  type TraceScope,
  type WherePlace,
} from "./api";

const MAX_REASON = 500;

/** What an option does to the analysis when a person applies it, in words. */
export function appliedWords(option: WherePlace["options"][number]): string {
  if (!option.applies) return "A what-if only: the analysis keeps a well or leaves it out.";
  if (option.id === "keep")
    return "Keeps the wells in the analysis (puts back what you left out here).";
  if (option.id === "set_aside")
    return `Leaves out every well of the sample (${plural(option.n_wells, "well")}): it is in no comparison.`;
  return `Leaves out ${option.n_wells === 1 ? "this well" : `this well and its replicates (${plural(option.n_wells, "well")})`}.`;
}

export function decidedToast(done: TraceDecided) {
  const title =
    done.status === "left_out"
      ? "Left out of the analysis"
      : done.status === "put_back"
        ? "Put back into the analysis"
        : "Kept, with your reason";
  toast.success(title, { description: done.message, duration: 10_000 });
}

/** The options of one place and the reason box: a person's decision, applied. */
export function DecidePanel({
  place,
  busy,
  onDecide,
  onCancel,
}: {
  place: WherePlace;
  busy: boolean;
  onDecide: (option: string, reason: string) => void;
  onCancel: () => void;
}) {
  const uid = useId();
  const [option, setOption] = useState("keep");
  const [reason, setReason] = useState("");
  const chosen = place.options.find((o) => o.id === option);
  const canSubmit = Boolean(chosen?.applies) && reason.trim().length > 0 && !busy;
  const submit = () => {
    if (canSubmit) onDecide(option, reason.trim());
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };
  return (
    <div className="mt-3 flex flex-col gap-3 rounded-lg border border-accent/40 bg-accent-soft/20 p-3">
      <fieldset className="min-w-0">
        <legend className="mb-1.5 text-[12px] font-medium text-muted">
          What to do at this place
        </legend>
        <div role="radiogroup" aria-label="What to do at this place" className="space-y-1.5">
          {place.options.map((o) => (
            <label
              key={o.id}
              className={cn(
                "flex items-start gap-2 rounded-lg border p-2 text-[13px] transition-colors duration-150",
                o.id === option ? "border-accent bg-surface" : "border-line",
                o.applies ? "cursor-pointer hover:border-line-strong" : "cursor-not-allowed",
              )}
            >
              <input
                type="radio"
                name={`${uid}-option`}
                value={o.id}
                checked={o.id === option}
                disabled={!o.applies}
                onChange={() => setOption(o.id)}
                className="mt-0.5 accent-[var(--accent)]"
              />
              <span className="min-w-0 flex-1">
                <span className={cn("block", o.applies ? "text-fg" : "text-muted")}>
                  {o.label}
                  {o.id === "keep" ? (
                    <Badge tone="accent" className="ml-2 align-middle">
                      Recommended
                    </Badge>
                  ) : null}
                </span>
                <span className="block text-[12px] text-muted">
                  {appliedWords(o)}{" "}
                  {o.changed_calls.length
                    ? `It changes ${o.changed_calls.length === 1 ? "the call of" : "the calls of"} ${o.changed_calls.join(", ")}.`
                    : o.id === "keep"
                      ? ""
                      : "It changes no call."}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="space-y-1.5">
        <label htmlFor={`${uid}-reason`} className="block text-[12px] font-medium text-muted">
          Why this option? (required; it goes into the session&rsquo;s record)
        </label>
        <Textarea
          id={`${uid}-reason`}
          rows={2}
          maxLength={MAX_REASON}
          showCount
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          onKeyDown={onKey}
          placeholder="e.g. the HMBS curve of this well never rose; the other four reference wells read normally"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={!canSubmit} loading={busy} onClick={submit}>
          Decide: {chosen?.label ?? option}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <KeyHint keys={[MOD, "Enter"]} />
      </div>
    </div>
  );
}

function wellsWords(entry: SetAside): string {
  const n = entry.wells.length;
  if (entry.option === "set_aside") return `every well of the sample (${plural(n, "well")})`;
  return n === 1 ? "1 well" : `${count(n)} wells (the well and its replicates)`;
}

function placeOf(entry: SetAside): string {
  return [
    `Sample ${entry.sample}`,
    entry.plate ? `plate ${entry.plate}` : null,
    entry.well ? `well ${entry.well}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function SetAsideRow({
  entry,
  scope,
  inbox,
}: {
  entry: SetAside;
  scope: TraceScope;
  inbox: string | null;
}) {
  const qc = useQueryClient();
  const uid = useId();
  const [putting, setPutting] = useState(false);
  const [reason, setReason] = useState("");
  const put = usePutBack(scope);
  const canSubmit = reason.trim().length > 0 && !put.isPending;
  const submit = () => {
    if (!canSubmit) return;
    put.mutate(
      { card_id: entry.card_id, reason: reason.trim(), expected_inbox: inbox },
      {
        onSuccess: (done) => {
          decidedToast(done);
          setReason("");
          setPutting(false);
          void refreshWorkspace(qc, scope.key);
        },
        onError: (e) => {
          if (e instanceof ApiError && e.stale) {
            toast.warning("Something changed since you loaded this", {
              description:
                "Here is what is set aside now; put the wells back again if you still want to.",
            });
            void refreshWorkspace(qc, scope.key);
          } else toast.error(e instanceof Error ? e.message : "The wells were not put back.");
        },
      },
    );
  };
  return (
    <li className="rounded-lg border border-line bg-surface p-3 text-[13px]">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-medium text-fg">{placeOf(entry)}</span>
        {entry.target ? <span className="text-muted">({entry.target})</span> : null}
        <Badge tone="ok">Left out by a person</Badge>
      </p>
      <p className="mt-1 text-fg">
        {entry.option_label}: {wellsWords(entry)} out of the analysis
        {entry.matters ? "; when you decided, this changed a call." : "."}
      </p>
      <p className="mt-1 text-muted">
        Why: {entry.reason}
        {entry.decided_at ? (
          <span className="text-faint"> · decided {dateTime(entry.decided_at)}</span>
        ) : null}
      </p>
      {putting ? (
        <div className="mt-2 space-y-1.5">
          <label htmlFor={`${uid}-reason`} className="block text-[12px] font-medium text-muted">
            Why put them back? (required; it goes into the session&rsquo;s record)
          </label>
          <Textarea
            id={`${uid}-reason`}
            rows={2}
            maxLength={MAX_REASON}
            showCount
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="e.g. the repeat plate gave the same value"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              icon={<Undo2 className="size-4" aria-hidden />}
              disabled={!canSubmit}
              loading={put.isPending}
              onClick={submit}
            >
              Put the wells back
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPutting(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button
          size="sm"
          variant="secondary"
          className="mt-2"
          icon={<Undo2 className="size-4" aria-hidden />}
          onClick={() => setPutting(true)}
        >
          Put the wells back<span className="sr-only">: {placeOf(entry)}</span>
        </Button>
      )}
    </li>
  );
}

/** What a person set aside from Trace in this session, each with Put the wells back. */
export function SetAsideList({
  scope,
  heading: H = "h3",
}: {
  scope: TraceScope;
  /** Its heading's level (one below the panel it sits in). */
  heading?: "h3" | "h4";
}) {
  const ids = useId();
  const q = useSetAside(scope);
  const view = q.data;
  if (!view || !view.can_apply || view.set_aside.length === 0) return null;
  return (
    <section
      aria-labelledby={`${ids}-title`}
      className="rounded-lg border border-line bg-sunken/40 p-3"
    >
      <H id={`${ids}-title`} className="text-[13px] font-semibold text-fg">
        Set aside from Trace
      </H>
      <p className="mt-0.5 text-[12px] text-muted">
        Wells you left out of the analysis from Where to look. Putting them back analyses the study
        again with them.
      </p>
      <ul className="mt-2 flex flex-col gap-2">
        {view.set_aside.map((entry) => (
          <SetAsideRow
            key={entry.card_id}
            entry={entry}
            scope={scope}
            inbox={view.inbox_head ?? null}
          />
        ))}
      </ul>
    </section>
  );
}

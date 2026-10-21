/**
 * The Import Trust card (`capture.import_trust`; api `qpilot/web/routers/trust.py`): a session
 * opened from an instrument export whose curves were most likely baseline-subtracted before export
 * (or whose processing qPilot could not tell) asks a person what that means for the analysis.
 * Shown first in the Decision Cards column: it is decided only once the results are visible, and
 * the confidence cap it sets is what every gene's level and reasons on this page say.
 *
 * Options: re-export the raw curves (the vendor's recipe; this analysis stays as it is), analyse
 * the curves as they are (capped at Moderate), or use the instrument's Cq values only (a new
 * analysis, capped at Low). A person picks one and says why; an agent's request (over MCP) waits
 * here for Approve or Turn down. Nothing is shown for a study whose curves call for no card.
 */
import { Bot, Check, FileDown } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { dateTime } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { Badge, Button, Card, ErrorPanel, Kbd, LevelTag, Textarea, toast } from "@/ui";
import {
  useImportTrust,
  useTrustWrite,
  type TrustOption,
  type TrustRequest,
  type TrustView,
  type TrustWrite,
} from "./api";

const MAX_REASON = 500;
const PLACEHOLDER: Record<string, string> = {
  reexport_raw: "e.g. we will re-export from CFX Maestro without baseline subtraction",
  analyse_as_is: "e.g. no raw export exists for this run; the cap is acceptable for a screen",
  cq_only: "e.g. the export holds baseline-subtracted curves; we report the instrument's Cq",
};
const TITLE_ID = "import-trust-card";

const STATUS: Record<string, { label: string; tone: "accent" | "ok" | "warn" }> = {
  open: { label: "A person decides", tone: "accent" },
  decided: { label: "Decided by a person", tone: "ok" },
  pending_human: { label: "Agent request", tone: "warn" },
};

function errorToast(e: unknown) {
  if (e instanceof ApiError && e.stale)
    toast.warning("Something changed since you loaded this (another tab, a decision or an agent)", {
      description: "Here is the Import Trust card at the analysis in use now.",
    });
  else toast.error(e instanceof Error ? e.message : "The decision could not be saved.");
}

function Requests({ requests }: { requests: TrustRequest[] }) {
  if (!requests.length) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg">
      <Bot className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <span>
        {requests.map((r, i) => (
          <span key={r.proposal_id} className="block">
            {i === 0 ? "An agent asked to " : "It also asked to "}
            <strong>{r.option_label.toLowerCase()}</strong>
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

function OptionRow({
  option: o,
  choosing,
  selected,
  requested,
  onSelect,
}: {
  option: TrustOption;
  choosing: boolean;
  selected: boolean;
  requested: boolean;
  onSelect: () => void;
}) {
  return (
    <label
      role={choosing ? undefined : "listitem"}
      className={cn(
        "flex flex-col gap-1 rounded-lg border p-2.5 transition-colors duration-150",
        selected || (!choosing && o.in_use) ? "border-accent bg-accent-soft/40" : "border-line",
        choosing && o.available ? "cursor-pointer hover:border-line-strong" : "cursor-default",
        !o.available && "opacity-70",
      )}
    >
      <span className="flex items-start gap-2">
        {choosing && (
          <input
            type="radio"
            name="import-trust-option"
            value={o.id}
            checked={selected}
            disabled={!o.available}
            onChange={onSelect}
            className="mt-0.5 accent-[var(--accent)]"
          />
        )}
        <span className="min-w-0 flex-1 text-[13px] font-medium text-fg">{o.label}</span>
        <span className="flex shrink-0 flex-wrap justify-end gap-1">
          {o.recommended && <Badge tone="accent">Recommended</Badge>}
          {o.in_use && (
            <Badge tone="ok" icon={<Check className="size-3" aria-hidden />}>
              In use
            </Badge>
          )}
          {requested && <Badge tone="warn">Agent asked</Badge>}
        </span>
      </span>
      <span className={cn("text-[12px] leading-relaxed text-muted", choosing && "pl-6")}>
        {o.effect}
      </span>
      <span
        className={cn(
          "flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]",
          choosing && "pl-6",
        )}
      >
        <span className="text-muted">Confidence at most</span>
        <LevelTag level={o.cap} className="text-[12px]" />
        {o.new_analysis && <span className="text-muted">· analyses the study again</span>}
      </span>
      {!o.available && o.why_not && (
        <span className={cn("text-[12px] text-warn", choosing && "pl-6")}>{o.why_not}</span>
      )}
    </label>
  );
}

/** The reason box and the buttons under it (decide, or approve / turn down a request). */
function DecideForm({
  write,
  label,
  placeholder,
  actions,
  note,
  onCancel,
}: {
  write: ReturnType<typeof useTrustWrite>;
  label: string;
  placeholder: string;
  actions: { label: string; make: (reason: string) => TrustWrite; secondary?: boolean }[];
  note?: string;
  onCancel?: () => void;
}) {
  const [reason, setReason] = useState("");
  const uid = useId();
  const canSubmit = reason.trim().length > 0 && !write.isPending;
  const run = (make: (reason: string) => TrustWrite, title: string) =>
    write.mutate(make(reason.trim()), {
      onSuccess: (done) => {
        toast.success(title, { description: done.message, duration: 10_000 });
        setReason("");
        onCancel?.();
      },
      onError: errorToast,
    });
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const first = actions[0];
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit && first) {
      e.preventDefault();
      run(first.make, first.label);
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
        {actions.map((a) => (
          <Button
            key={a.label}
            size="sm"
            variant={a.secondary ? "secondary" : "primary"}
            disabled={!canSubmit}
            loading={write.isPending && !a.secondary}
            onClick={() => run(a.make, a.label)}
          >
            {a.label}
          </Button>
        ))}
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <span className="text-[12px] text-faint">
          <Kbd>{MOD}</Kbd>
          <Kbd>Enter</Kbd>
        </span>
      </div>
      {note && <p className="text-[12px] text-muted">{note}</p>}
    </div>
  );
}

export function ImportTrustView({
  view,
  write,
}: {
  view: TrustView;
  /** The write, when a person can decide the card here; else read-only. */
  write?: ReturnType<typeof useTrustWrite>;
}) {
  const requests = view.requests;
  const pending = requests.length > 0;
  const status = STATUS[view.status] ?? STATUS.open!;
  const inUse = view.in_use ?? "analyse_as_is";
  const [changing, setChanging] = useState(false);
  const [option, setOption] = useState<string>(
    requests[0]?.option ??
      (view.decision ? inUse : (view.options.find((o) => o.recommended)?.id ?? inUse)),
  );
  const canDecide = Boolean(write && view.can_decide);
  const choosing = canDecide && !pending && (!view.decision || changing);
  const chosen = view.options.find((o) => o.id === option);
  const labelOf = (id: string) => view.options.find((o) => o.id === id)?.label ?? id;
  const showRecipe = option === "reexport_raw" || inUse === "reexport_raw";
  const asked = new Set(requests.map((r) => r.option));
  return (
    <Card
      as="article"
      aria-labelledby={TITLE_ID}
      className={cn(pending ? "border-warn" : !view.decision && "border-accent/50")}
    >
      <div className="space-y-1 p-4 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={TITLE_ID} className="text-[15px] font-semibold tracking-tight text-fg">
            Import Trust: {view.question}
          </h3>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
        <p className="text-[13px] text-fg">
          <span className="font-medium">{view.verdict_title}</span>
          <span className="text-muted"> · {view.connector_label} export</span>
        </p>
        <p className="text-[13px] leading-relaxed text-muted">{view.verdict_meaning}</p>
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 pt-1 text-[13px] text-fg">
          <span>Every gene's confidence here is at most</span>
          <LevelTag level={view.cap} />
          <span className="text-muted">· in use: {labelOf(inUse)}</span>
        </p>
        {view.why && <p className="text-[13px] text-warn">{view.why}</p>}
      </div>
      <div className="space-y-3 px-4 pb-4">
        <Requests requests={requests} />
        <fieldset className="min-w-0">
          <legend className="mb-1.5 text-[12px] font-medium text-muted">Options</legend>
          <div
            role={choosing ? "radiogroup" : "list"}
            aria-label="Import Trust: options"
            className="space-y-1.5"
          >
            {view.options.map((o) => (
              <OptionRow
                key={o.id}
                option={o}
                choosing={choosing}
                selected={choosing && o.id === option}
                requested={asked.has(o.id)}
                onSelect={() => setOption(o.id)}
              />
            ))}
          </div>
        </fieldset>
        {showRecipe && (
          <div className="flex items-start gap-2 rounded-lg bg-sunken/60 px-3 py-2 text-[13px]">
            <FileDown className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
            <p className="leading-relaxed text-fg">
              <span className="font-medium">How to re-export the raw curves: </span>
              {view.recipe}
            </p>
          </div>
        )}
        {view.decision && !changing && (
          <p className="text-[13px] text-muted">
            <span className="text-fg">Decided by a person: {view.decision.label}.</span> Why:{" "}
            {view.decision.reason}
            {view.decision.decided_at ? (
              <span className="text-faint"> · decided {dateTime(view.decision.decided_at)}</span>
            ) : null}
          </p>
        )}
        {canDecide && write && pending ? (
          <DecideForm
            write={write}
            label="Your reason (required, for either answer; it goes into the record)"
            placeholder="e.g. the export holds Delta Rn; we report the instrument's Cq values"
            actions={[
              {
                label: `Approve: ${requests[0]!.option_label}`,
                make: (reason) => ({ kind: "decide", option: requests[0]!.option, reason }),
              },
              {
                label: "Turn down",
                secondary: true,
                make: (reason) => ({
                  kind: "turn_down",
                  proposal: requests[0]!.proposal_id,
                  reason,
                }),
              },
            ]}
            note={view.decide_note}
          />
        ) : choosing && write ? (
          <DecideForm
            key={option}
            write={write}
            label="Why this option? (required; it goes into the record)"
            placeholder={PLACEHOLDER[option] ?? ""}
            actions={[
              {
                label: `Decide: ${labelOf(option)}`,
                make: (reason) => ({ kind: "decide", option, reason }),
              },
            ]}
            note={chosen?.new_analysis ? view.decide_note : undefined}
            onCancel={changing ? () => (setChanging(false), setOption(inUse)) : undefined}
          />
        ) : canDecide && view.decision ? (
          <Button size="sm" variant="secondary" onClick={() => setChanging(true)}>
            Change the decision
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

/** The card for the open study, when its curves call for one (else nothing). */
export function ImportTrustCard({
  workspaceKey,
  studyId,
  isSession,
}: {
  workspaceKey: string;
  studyId: string;
  isSession: boolean;
}) {
  const q = useImportTrust(isSession ? workspaceKey : "", isSession ? studyId : null);
  const write = useTrustWrite(workspaceKey, studyId, q.data);
  if (!isSession) return null;
  if (q.error)
    return (
      <ErrorPanel
        error={q.error}
        title="The Import Trust card could not be read"
        onRetry={() => void q.refetch()}
        compact
      />
    );
  if (!q.data?.applies) return null;
  return (
    <ImportTrustView key={`${q.data.study_id}:${q.data.inbox_head}`} view={q.data} write={write} />
  );
}

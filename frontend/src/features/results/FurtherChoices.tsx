/**
 * Further choices the grid tests on request (docs/app.md §4 Results): "Also test efficiency
 * models". qPilot turns each Cq into a quantity with LinRegPCR's mean efficiency of each assay;
 * the other efficiency models are tested only when a person asks. The rule proposes testing them
 * (or stopping), the engine checks the proposal, and a person accepts it in the choices stage;
 * then the study is analysed again with the choice as one more dimension of the grid, and its
 * Decision Card says what each model changes. Every number here is a fact from the result.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, FlaskConical } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { api, unwrap, type Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { EFFICIENCY_MODEL_WORDS, effectivePayload, type Proposal } from "@/lib/vocab";
import { sectionPath } from "@/shell/sections";
import { Badge, Button, Card, CommandLine, ErrorPanel, Switch, toast, type Tone } from "@/ui";
import {
  ProposalCard,
  decidedLine,
  useCheckEdit,
  useProposalActions,
  useQuotes,
  useStageProposals,
  type Payload,
} from "@/ui/proposal";
import type { ResultsView } from "./api";
import { FactText } from "./FactText";

export type AxisView = NonNullable<ResultsView["axes"]>[number];
type Workspace = Schemas["WorkspaceView"];

/** The axis's state as a badge: what the grid does with it now. */
export const AXIS_STATUS: Record<AxisView["status"], { word: string; tone: Tone }> = {
  off: { word: "Not tested", tone: "neutral" },
  swept: { word: "Tested in the grid", tone: "accent" },
  screened_out: { word: "Tried; changes nothing", tone: "ok" },
  not_applicable: { word: "Does not apply here", tone: "neutral" },
  single_option: { word: "Not tested", tone: "neutral" },
};

/** What accepting a proposal does, said on the card before anyone decides. */
export function consequenceWords(on: boolean): string {
  return on
    ? "Accepting analyses the study again with the efficiency models as one more choice of the " +
        "grid. The analysis in use stays LinRegPCR's mean efficiency until you decide its card. " +
        "The cards of that analysis start undecided; your decisions here stay with this analysis " +
        "and come back if you stop testing."
    : "Accepting goes back to the analysis without the efficiency models, with the decisions " +
        "you made there.";
}

/** Whether a choice.axis payload asks to test the axis (more than the primary option). */
export function asksToTest(p: Pick<Proposal, "payload" | "edits">): boolean {
  const options = effectivePayload(p).options;
  return Array.isArray(options) && options.length > 1;
}

/** Ticks for the options of the axis: the primary is always in, each other one optional. */
export function OptionsEditor({
  axis,
  value,
  onChange,
}: {
  axis: AxisView;
  value: Payload;
  onChange: (next: Payload) => void;
}) {
  const chosen = new Set(Array.isArray(value.options) ? value.options.map(String) : []);
  const primary = axis.options.find((o) => o.primary)?.id ?? "linregpcr";
  const offered = axis.options.filter((o) => !o.primary && !o.unavailable);
  const set = (option: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(option);
    else next.delete(option);
    // primary first, then the catalogue's order
    const ordered = [primary, ...axis.options.map((o) => o.id).filter((o) => o !== primary)];
    onChange({ ...value, options: ordered.filter((o) => o === primary || next.has(o)) });
  };
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-[13px] font-medium text-fg">Efficiency models to test</legend>
      <p className="text-[13px] text-muted">
        {EFFICIENCY_MODEL_WORDS[primary] ?? primary} stays in: it is the analysis in use.
      </p>
      {offered.map((o) => (
        <Switch
          key={o.id}
          checked={chosen.has(o.id)}
          onCheckedChange={(on) => set(o.id, on)}
          label={o.label}
          hint={o.tier === "common_practice" ? "Common practice, not measured." : undefined}
        />
      ))}
    </fieldset>
  );
}

function OptionRow({ option }: { option: AxisView["options"][number] }) {
  const state = option.primary
    ? "In use"
    : option.unavailable
      ? "Does not apply"
      : option.tested
        ? "Tested"
        : "Not tested";
  return (
    <li className="flex flex-col gap-0.5 border-t border-line py-2 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-fg">{option.label}</span>
        <span className={cn("text-xs", option.primary ? "font-medium text-fg" : "text-muted")}>
          {state}
        </span>
      </div>
      {option.unavailable ? <p className="text-xs text-muted">{option.unavailable}</p> : null}
      {option.flips && option.tested ? (
        <p className="text-xs text-muted">
          Alone, it changes{" "}
          <span
            className="tabular font-medium text-fg"
            title={`From the result: ${option.flips.path}`}
          >
            {option.flips.text}
          </span>{" "}
          {Number(option.flips.value) === 1 ? "call" : "calls"}.
        </p>
      ) : null}
    </li>
  );
}

function ProposeButton({ axis, sid, on }: { axis: AxisView; sid: string; on: boolean }) {
  const qc = useQueryClient();
  const propose = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/sessions/{sid}/propose/axis", {
          params: { path: { sid } },
          body: { axis: axis.name as "efficiency", on },
        }),
      ),
    onSuccess: (done) => toast.success(done.message),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", sid] }),
  });
  return (
    <div className="space-y-2">
      <Button
        variant={on ? "primary" : "secondary"}
        size="sm"
        loading={propose.isPending}
        onClick={() => propose.mutate()}
      >
        {on ? "Propose testing the efficiency models" : "Propose to stop testing them"}
      </Button>
      <p className="text-xs text-muted">
        qPilot proposes and checks; nothing changes until you accept the proposal.
      </p>
      {propose.error ? <ErrorPanel error={propose.error} title="Not proposed" compact /> : null}
    </div>
  );
}

function AxisProposals({
  axis,
  sid,
  pending,
}: {
  axis: AxisView;
  sid: string;
  pending: Proposal[];
}) {
  const list = useStageProposals(sid, "choices");
  const actions = useProposalActions(sid, list.data?.head, "choices");
  const checkEdit = useCheckEdit(sid);
  const { lookup, sheetCells } = useQuotes(sid);
  return (
    <ul aria-label="Proposals waiting for you" className="flex flex-col gap-3">
      {pending.map((p) => (
        <li key={p.id}>
          <ProposalCard
            proposal={p}
            quotes={lookup}
            sheetCells={sheetCells}
            resultsVisible
            headingLevel={3}
            onAccept={(reason) => actions.accept(p.id, reason)}
            onEdit={(edits, reason) => actions.edit(p.id, edits, reason)}
            onReject={(reason) => actions.reject(p.id, reason)}
            onCheckEdit={checkEdit ? (edits) => checkEdit(p.id, edits) : undefined}
            renderEditor={({ value, onChange }) => (
              <OptionsEditor axis={axis} value={value} onChange={onChange} />
            )}
            renderConsequence={(q) => ({ summary: consequenceWords(asksToTest(q)) })}
          />
        </li>
      ))}
    </ul>
  );
}

/** One further choice: what the grid does with it, its options, and the way to change that. */
export function AxisPanel({ axis, workspace }: { axis: AxisView; workspace: Workspace }) {
  const titleId = `axis-${axis.name}`;
  const sid = axis.can_propose && workspace.kind === "session" ? workspace.key : null;
  const list = useStageProposals(sid, "choices");
  const mine = (list.data?.proposals ?? []).filter(
    (p) => p.kind === "choice.axis" && p.subject === axis.name,
  );
  const pending = mine.filter((p) => p.status === "proposed");
  const decided = mine.filter((p) => p.status !== "proposed");
  const [showDecided, setShowDecided] = useState(false);
  const status = AXIS_STATUS[axis.status];
  const testing = axis.status !== "off";
  return (
    <Card as="section" aria-labelledby={titleId} className="space-y-3 p-4 text-[13px]">
      <div className="flex items-start gap-3">
        <FlaskConical className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id={titleId} className="text-sm font-semibold text-fg">
              Also test efficiency models
            </h2>
            <Badge tone={status.tone}>{status.word}</Badge>
          </div>
          <p className="text-muted">{axis.title}.</p>
        </div>
      </div>
      <p className="text-fg">
        <FactText text={axis.text} />
      </p>
      <ul aria-label="Efficiency models" className="rounded-lg border border-line px-3 py-2">
        {axis.options.map((o) => (
          <OptionRow key={o.id} option={o} />
        ))}
      </ul>
      {axis.notes.map((n, i) => (
        <p key={i} className="text-xs text-muted">
          <FactText text={n} />
        </p>
      ))}
      {axis.card_id ? (
        <Link
          href={sectionPath(workspace, "results", "card", axis.card_id)}
          className="inline-flex items-center gap-1 font-medium text-accent underline"
        >
          Go to its Decision Card
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      ) : null}
      {sid ? (
        list.error ? (
          <ErrorPanel error={list.error} title="The proposals could not be read" compact />
        ) : pending.length ? (
          <AxisProposals axis={axis} sid={sid} pending={pending} />
        ) : list.data ? (
          <ProposeButton axis={axis} sid={sid} on={!testing} />
        ) : null
      ) : axis.command ? (
        <div className="space-y-1.5">
          <p className="text-muted">
            This study was analysed outside Studio. To test the efficiency models, run:
          </p>
          <CommandLine command={axis.command} />
        </div>
      ) : null}
      {decided.length ? (
        <div>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={showDecided}
            onClick={() => setShowDecided((v) => !v)}
          >
            {showDecided ? "Hide" : "Show"} what was decided ({decided.length})
          </Button>
          {showDecided ? (
            <ul className="mt-2 space-y-2">
              {decided.map((p) => (
                <li key={p.id} className="rounded-lg border border-line px-3 py-2">
                  <p className="text-fg">
                    {asksToTest(p) ? "Test the efficiency models" : "Stop testing them"}
                  </p>
                  <p className="text-xs text-muted">{decidedLine(p)}</p>
                  {p.reason ? <p className="text-xs text-muted">Reason: {p.reason}</p> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/** Every further choice the API offers for this study (today: the efficiency models). */
export function FurtherChoices({ view, workspace }: { view: ResultsView; workspace: Workspace }) {
  const axes = view.axes ?? [];
  if (!axes.length) return null;
  return (
    <>
      {axes.map((axis) => (
        <AxisPanel key={axis.name} axis={axis} workspace={workspace} />
      ))}
    </>
  );
}

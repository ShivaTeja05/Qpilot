/**
 * Further choices the grid tests on request (docs/app.md §4 Results): "Also test efficiency
 * models", "Also test other normalisers" (NormFinder's and geNorm's best pairs, the global mean)
 * and "Also test corrections between plates". qPilot uses LinRegPCR's mean efficiency, the
 * reference genes chosen and no plate correction; the others are tested only when a person
 * asks. The rule proposes testing them (or stopping), the engine checks the proposal, and a
 * person accepts it in the choices stage; then the study is analysed again with the choice as
 * one more dimension of the grid, and its Decision Card says what each option changes. Every
 * number here is a fact from the result.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, FlaskConical } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { api, unwrap, type Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { AXIS_OPTION_WORDS, effectivePayload, type Proposal } from "@/lib/vocab";
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

/** How each further choice is named on the page (the efficiency models came first). */
export interface AxisWords {
  heading: string;
  /** The options as a group, inside a sentence ("the efficiency models"). */
  noun: string;
  /** The analysis in use, inside a sentence. */
  inUse: string;
  list: string;
  legend: string;
}
const EFFICIENCY_UI: AxisWords = {
  heading: "Also test efficiency models",
  noun: "the efficiency models",
  inUse: "LinRegPCR's mean efficiency",
  list: "Efficiency models",
  legend: "Efficiency models to test",
};
export const AXIS_UI: Record<string, AxisWords> = {
  efficiency: EFFICIENCY_UI,
  normaliser: {
    heading: "Also test other normalisers",
    noun: "the other normalisers",
    inUse: "the reference genes chosen",
    list: "Normalisers",
    legend: "Normalisers to test",
  },
  interrun: {
    heading: "Also test corrections between plates",
    noun: "the corrections between plates",
    inUse: "no correction between plates",
    list: "Corrections between plates",
    legend: "Corrections to test",
  },
};
export const axisWords = (name: string): AxisWords => AXIS_UI[name] ?? EFFICIENCY_UI;

/** What accepting a proposal does, said on the card before anyone decides. */
export function consequenceWords(on: boolean, axis = "efficiency"): string {
  const w = axisWords(axis);
  return on
    ? `Accepting analyses the study again with ${w.noun} as one more choice of the ` +
        `grid. The analysis in use stays ${w.inUse} until you decide its card. ` +
        "What you decided on the other cards is carried over, unless that choice matters more in " +
        "the new analysis: then its card asks you again. Confirm the choices again afterwards."
    : `Accepting goes back to the analysis without ${w.noun}; what you decided on ` +
        "the cards is carried back the same way.";
}

/** Whether a choice.axis payload asks to test the axis (more than the primary option). */
export function asksToTest(p: Pick<Proposal, "payload" | "edits">): boolean {
  const options = effectivePayload(p).options;
  return Array.isArray(options) && options.length > 1;
}

/** Every option a choice.axis proposal names, in its payload or its other readings. */
export function namedOptions(p: Pick<Proposal, "payload" | "alternatives">): string[] {
  const readings = [p.payload, ...(p.alternatives ?? [])] as Payload[];
  return [
    ...new Set(readings.flatMap((r) => (Array.isArray(r.options) ? r.options.map(String) : []))),
  ];
}

/** Ticks for the options of the axis: the primary is always in, each other one optional. */
export function OptionsEditor({
  axis,
  value,
  onChange,
  allowed,
}: {
  axis: AxisView;
  value: Payload;
  onChange: (next: Payload) => void;
  /** The models the proposal names (its payload and its other reading): the ones that apply. */
  allowed?: string[];
}) {
  const chosen = new Set(Array.isArray(value.options) ? value.options.map(String) : []);
  const primary = axis.options.find((o) => o.primary)?.id ?? "linregpcr";
  const words = AXIS_OPTION_WORDS[axis.name] ?? {};
  const offered = axis.options.filter(
    (o) => !o.primary && !o.unavailable && (!allowed || allowed.includes(o.id)),
  );
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
      <legend className="mb-1 text-[13px] font-medium text-fg">
        {axisWords(axis.name).legend}
      </legend>
      <p className="text-[13px] text-muted">
        {upperFirst(words[primary] ?? primary)} stays in: it is the analysis in use.
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

function upperFirst(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
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
      {option.unavailable ? (
        <p className="text-xs text-muted">
          {option.unavailable.charAt(0).toUpperCase() + option.unavailable.slice(1)}.
        </p>
      ) : null}
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
          body: { axis: axis.name as "efficiency" | "normaliser" | "interrun", on },
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
        {on ? `Propose testing ${axisWords(axis.name).noun}` : "Propose to stop testing them"}
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
              <OptionsEditor
                axis={axis}
                value={value}
                onChange={onChange}
                allowed={namedOptions(p)}
              />
            )}
            renderConsequence={(q) => ({ summary: consequenceWords(asksToTest(q), axis.name) })}
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
  const words = axisWords(axis.name);
  return (
    <Card as="section" aria-labelledby={titleId} className="space-y-3 p-4 text-[13px]">
      <div className="flex items-start gap-3">
        <FlaskConical className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id={titleId} className="text-sm font-semibold text-fg">
              {words.heading}
            </h2>
            <Badge tone={status.tone}>{status.word}</Badge>
          </div>
          <p className="text-muted">{axis.title}.</p>
        </div>
      </div>
      <p className="text-fg">
        <FactText text={axis.text} />
      </p>
      <ul aria-label={words.list} className="rounded-lg border border-line px-3 py-2">
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
            This study was analysed outside Studio. To test {words.noun}, run:
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
                    {asksToTest(p) ? `Test ${words.noun}` : "Stop testing them"}
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

/** Every further choice the API offers for this study (efficiency, normaliser, plates). */
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

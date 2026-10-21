/**
 * The rule checks as a scannable list: a verdict chip, the rule and where it looked, how many
 * wells it points at and (for a warn or a fail) what leaving them out changes. Each row opens to
 * the reason in words (every number a cited fact), the wells, and the consequence test's options.
 * Filters: verdict (problems first by default), rule, and the plate picked in the plate strip.
 */
import { ChevronDown } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { FactText } from "@/features/results/FactText";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import { Badge, Button, Card, CardHeader, SegmentedControl, Select } from "@/ui";
import type { Consequence, Evaluation, GateView, RunFile } from "./api";
import { ClassChip, VerdictChip } from "./Pieces";
import {
  VERDICT_WORD,
  filterEvaluations,
  leadOption,
  plateLabel,
  runSourceText,
  verdictCounts,
  wellText,
  whereText,
  type RuleFilter,
  type VerdictFilter,
} from "./words";

const PAGE = 60;
/** Wells shown as chips before the rest fold away (a whole run can be hundreds of wells). */
const WELLS_SHOWN = 24;

function WellChips({ wells }: { wells: readonly string[] }) {
  const chip = (w: string) => (
    <li
      key={w}
      className="rounded border border-line bg-surface px-1.5 font-mono text-[11px] text-fg"
    >
      {wellText(w)}
    </li>
  );
  if (wells.length <= WELLS_SHOWN) {
    return <ul className="mt-1 flex flex-wrap gap-1">{wells.map(chip)}</ul>;
  }
  return (
    <>
      <ul className="mt-1 flex flex-wrap gap-1">{wells.slice(0, WELLS_SHOWN).map(chip)}</ul>
      <details className="mt-1 text-[12px] text-muted">
        <summary className="cursor-pointer select-none hover:text-fg">
          and {plural(wells.length - WELLS_SHOWN, "more well")}
        </summary>
        <ul className="mt-1 flex flex-wrap gap-1">{wells.slice(WELLS_SHOWN).map(chip)}</ul>
      </details>
    </>
  );
}

export function ConsequenceBlock({
  consequence,
  headingLevel = 3,
}: {
  consequence: Consequence;
  headingLevel?: 3 | 4;
}) {
  const H = `h${headingLevel}` as "h3" | "h4";
  return (
    <div className="rounded-lg border border-line bg-sunken/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <H className="text-[13px] font-semibold text-fg">What leaving the wells out changes</H>
        <ClassChip value={consequence.consequence} />
      </div>
      <p className="mt-1 text-[13px] text-muted">{consequence.triage_text}</p>
      <ul className="mt-2 flex flex-col gap-2">
        {consequence.options.map((o) => (
          <li key={o.id} className="text-[13px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-fg">{o.label}</span>
              {consequence.rescue_option === o.id && <Badge tone="accent">Moves least</Badge>}
            </div>
            <p className="mt-0.5 text-fg">
              <FactText text={o.text} />
            </p>
            {o.excluded.length > 0 && (
              <details className="mt-1 text-[12px] text-muted">
                <summary className="cursor-pointer select-none hover:text-fg">
                  The {plural(o.excluded.length, "well")} it leaves out
                </summary>
                <WellChips wells={o.excluded} />
              </details>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RuleRow({
  evaluation: e,
  consequence,
  run,
  onLinkRun,
  open,
  onToggle,
  focus,
}: {
  evaluation: Evaluation;
  consequence: Consequence | undefined;
  /** For a G-INSTR check: the run file it read for its plate. */
  run?: RunFile;
  onLinkRun?: (plate: string) => void;
  open: boolean;
  onToggle: () => void;
  focus: boolean;
}) {
  const bodyId = useId();
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!focus || !ref.current) return;
    ref.current.scrollIntoView?.({ block: "center" });
    ref.current.focus({ preventScroll: true });
  }, [focus]);
  const lead = consequence ? leadOption(consequence) : undefined;
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        ref={ref}
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
        className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-sunken/60"
      >
        <span className="w-[7.5rem] shrink-0 pt-0.5">
          <VerdictChip verdict={e.verdict} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-medium text-fg">
            <span className="font-mono text-[12px] text-muted">{e.rule_id}</span> {e.title}
          </span>
          <span className="block text-[12px] text-muted">
            {whereText(e)}
            {e.flagged.length > 0 && <> · points at {plural(e.flagged.length, "well")}</>}
          </span>
          {lead && consequence && (
            <span className="mt-0.5 block text-[12px] text-fg">
              <FactText text={lead.text} />
            </span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "mt-1 size-4 shrink-0 text-muted transition-transform duration-150",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {open && (
        <div id={bodyId} className="flex flex-col gap-3 px-4 pb-4 sm:pl-[9.25rem]">
          <p className="text-[13px] leading-relaxed text-fg">
            <FactText text={e.reason} />
          </p>
          {e.verdict === "not_applicable" && e.code && (
            <p className="text-[12px] text-muted">
              Not applicable because: <span className="font-mono">{e.code.replace(/_/g, " ")}</span>
            </p>
          )}
          {e.flagged.length > 0 && (
            <div>
              <h3 className="text-[12px] font-medium text-muted">
                The {plural(e.flagged.length, "well")} this rule points at
              </h3>
              <WellChips wells={e.flagged} />
            </div>
          )}
          {run && (
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
              <span>Run file read: {runSourceText(run)}.</span>
              {onLinkRun && (
                <Button size="sm" variant="secondary" onClick={() => onLinkRun(run.plate)}>
                  {run.source === "linked" ? "Link another run file" : "Link a run file"} for this
                  plate
                </Button>
              )}
            </div>
          )}
          {consequence && <ConsequenceBlock consequence={consequence} />}
        </div>
      )}
    </li>
  );
}

export function RuleList({
  view,
  filter,
  onFilter,
  focusId,
  onLinkRun,
}: {
  view: GateView;
  filter: RuleFilter;
  onFilter: (f: RuleFilter) => void;
  /** An evaluation to open, scroll to and focus (from the consequences list). */
  focusId: string | null;
  /** Link a run file to a plate (G-INSTR's checks offer it). */
  onLinkRun?: (plate: string) => void;
}) {
  /** Rows a person opened or closed; the row asked for from elsewhere starts open. */
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const isOpen = (id: string) => toggled.get(id) ?? id === focusId;
  /** How many rows show, for the filter they were shown for (a new filter starts again). */
  const signature = `${filter.verdict}|${filter.rule}|${filter.plate ?? ""}`;
  const [page, setPage] = useState({ signature, n: PAGE });
  const shown = page.signature === signature ? page.n : PAGE;
  const consequences = useMemo(
    () => new Map(view.consequences.map((c) => [c.id, c])),
    [view.consequences],
  );
  const runs = useMemo(
    () => new Map(view.runs.filter((r) => r.evaluation).map((r) => [r.evaluation!, r])),
    [view.runs],
  );
  const rows = useMemo(
    () => filterEvaluations(view.evaluations, filter),
    [view.evaluations, filter],
  );
  const counts = useMemo(
    () =>
      verdictCounts(
        view.evaluations.filter(
          (e) =>
            (filter.rule === "all" || e.rule_id === filter.rule) &&
            (filter.plate === null || e.plate === filter.plate),
        ),
      ),
    [view.evaluations, filter.rule, filter.plate],
  );
  const toggle = (id: string) => setToggled((m) => new Map(m).set(id, !isOpen(id)));
  const verdictOptions: { value: VerdictFilter; label: string }[] = [
    { value: "attention", label: `Warn or fail (${count(counts.fail + counts.warn)})` },
    { value: "fail", label: `${VERDICT_WORD.fail} (${count(counts.fail)})` },
    { value: "warn", label: `${VERDICT_WORD.warn} (${count(counts.warn)})` },
    { value: "pass", label: `${VERDICT_WORD.pass} (${count(counts.pass)})` },
    {
      value: "not_applicable",
      label: `${VERDICT_WORD.not_applicable} (${count(counts.not_applicable)})`,
    },
    { value: "all", label: "All" },
  ];
  const ruleOptions = [
    { value: "all", label: "Every rule" },
    ...view.pack.rules.map((r) => ({ value: r.rule_id, label: `${r.rule_id} · ${r.title}` })),
  ];
  return (
    <Card as="section" aria-labelledby="gate-rules-title">
      <CardHeader
        id="gate-rules-title"
        title="Rule checks"
        hint={`${plural(view.evaluations.length, "check")} of ${plural(view.pack.rules.length, "rule")} on ${plural(view.plates.length, "plate")}; open a row for the reason and the wells.`}
      />
      <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
        <SegmentedControl
          size="sm"
          label="Show checks by verdict"
          value={filter.verdict}
          onValueChange={(verdict) => onFilter({ ...filter, verdict })}
          options={verdictOptions}
          className="max-w-full flex-wrap"
        />
        <Select
          size="sm"
          label="Show checks of one rule"
          value={filter.rule}
          onValueChange={(rule) => onFilter({ ...filter, rule })}
          options={ruleOptions}
          className="w-[16rem] max-w-full"
        />
        {filter.plate && (
          <Button size="sm" variant="ghost" onClick={() => onFilter({ ...filter, plate: null })}>
            Every plate (now: {plateLabel(filter.plate)})
          </Button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="border-t border-line px-4 py-6 text-[13px] text-muted">
          No rule check matches these filters.
          {filter.verdict === "attention" ? " Nothing warns or fails here." : ""}
        </p>
      ) : (
        <ul className="border-t border-line" aria-label="Rule checks">
          {rows.slice(0, shown).map((e) => (
            <RuleRow
              key={e.id}
              evaluation={e}
              consequence={e.consequence ? consequences.get(e.consequence) : undefined}
              run={runs.get(e.id)}
              onLinkRun={onLinkRun}
              open={isOpen(e.id)}
              onToggle={() => toggle(e.id)}
              focus={focusId === e.id}
            />
          ))}
        </ul>
      )}
      {rows.length > shown && (
        <div className="border-t border-line px-4 py-3">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setPage({ signature, n: shown + PAGE })}
          >
            Show {count(Math.min(PAGE, rows.length - shown))} more of {count(rows.length - shown)}
          </Button>
        </div>
      )}
    </Card>
  );
}

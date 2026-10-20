/**
 * The power explorer: the change worth finding, the power, the samples per group and the genes;
 * the server answers with the plan (numbers from `qpilot.qpcr.plan`), drawn as power curves at
 * this study's own noise, with what this study's own size can already detect.
 */
import { AlertTriangle, Plus, X } from "lucide-react";
import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { count, fold, percent } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  LoadingBlock,
  SegmentedControl,
  Select,
  Switch,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import type { PlannerView, PlanView } from "./api";
import { NumberField } from "./NumberField";
import { PowerChart } from "./PowerChart";
import { StopSlider } from "./StopSlider";
import { FOLD_STOPS, N_STOPS, POWER_STOPS, changeWords, nearestStop } from "./words";

export interface ExplorerState {
  foldIndex: number;
  direction: "up" | "down";
  powerIndex: number;
  autoN: boolean;
  nIndex: number;
  genes: string[];
  plates: number | null;
}

export interface ExplorerProps {
  view: PlannerView;
  plan: PlanView | undefined;
  planError: unknown;
  fetching: boolean;
  state: ExplorerState;
  onChange: (next: Partial<ExplorerState>) => void;
  lead: string | null;
  onLead: (gene: string) => void;
}

export function Explorer({
  view,
  plan,
  planError,
  fetching,
  state,
  onChange,
  lead,
  onLead,
}: ExplorerProps) {
  const magnitude = FOLD_STOPS[state.foldIndex]!;
  const others = useMemo(
    () =>
      view.genes
        .map((g) => g.gene)
        .filter((g) => !state.genes.includes(g))
        .sort((a, b) => a.localeCompare(b)),
    [view.genes, state.genes],
  );
  const leadRow = plan?.genes.find((g) => g.gene === lead) ?? plan?.genes.find((g) => g.focus);
  const nCurrent = view.groups.map((g) => g.n);

  return (
    <Card as="section" aria-labelledby="planner-explorer">
      <CardHeader
        id="planner-explorer"
        title="How many samples, and what they can detect"
        hint="Move the sliders: every number is qPilot's plan arithmetic and its simulation of qPilot's own conclusion rule, at the noise each gene showed in this study."
      />
      <CardBody className="grid gap-6 xl:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]">
        {/* the choices */}
        <div className="grid content-start gap-5 sm:grid-cols-2 xl:grid-cols-1">
          <div>
            <StopSlider
              label="Change worth finding"
              stops={FOLD_STOPS}
              index={state.foldIndex}
              onIndexChange={(i) => onChange({ foldIndex: i })}
              format={(v) => fold(v)}
              valueText={changeWords(magnitude, state.direction)}
            />
            <SegmentedControl
              label="Direction"
              size="sm"
              className="mt-2"
              value={state.direction}
              onValueChange={(d) => onChange({ direction: d })}
              options={[
                { value: "up", label: "▲ higher" },
                { value: "down", label: "▼ lower" },
              ]}
            />
          </div>
          <StopSlider
            label="Power"
            stops={POWER_STOPS}
            index={state.powerIndex}
            onIndexChange={(i) => onChange({ powerIndex: i })}
            format={(v) => percent(v)}
            hint="How often the experiment should find the change when it is real."
          />
          <div>
            <StopSlider
              label="Samples per group"
              stops={N_STOPS}
              index={state.autoN && plan ? nearestStop(N_STOPS, plan.n_plan) : state.nIndex}
              onIndexChange={(i) => onChange({ nIndex: i, autoN: false })}
              format={(v) => count(v)}
              valueText={
                state.autoN
                  ? plan
                    ? `${count(plan.n_plan)} (what the genes need)`
                    : "what the genes need"
                  : count(N_STOPS[state.nIndex]!)
              }
              dimmed={state.autoN}
            />
            <Switch
              className="mt-2"
              checked={state.autoN}
              onCheckedChange={(on) =>
                onChange(
                  on
                    ? { autoN: true }
                    : { autoN: false, nIndex: nearestStop(N_STOPS, plan?.n_plan ?? 12) },
                )
              }
              label="Size it for the chosen genes"
              hint={plan?.n_plan_reason ? `The plan uses ${plan.n_plan_reason}.` : undefined}
            />
          </div>

          <fieldset>
            <legend className="text-[13px] font-medium text-fg">
              Genes in the next experiment
            </legend>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {state.genes.map((g) => (
                <li key={g}>
                  <span
                    className={cn(
                      "inline-flex h-7 items-center gap-1 rounded-full border pl-2.5 pr-1 text-[12px]",
                      g === (leadRow?.gene ?? lead)
                        ? "border-accent bg-accent-soft text-fg"
                        : "border-line bg-surface text-fg",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => onLead(g)}
                      className="font-medium outline-none focus-visible:underline"
                      aria-label={`Show ${g} on the chart`}
                    >
                      {g}
                    </button>
                    <button
                      type="button"
                      onClick={() => onChange({ genes: state.genes.filter((x) => x !== g) })}
                      disabled={state.genes.length <= 1}
                      aria-label={`Remove ${g}`}
                      className="inline-flex size-5 items-center justify-center rounded-full text-muted hover:bg-bg-subtle hover:text-fg disabled:opacity-40"
                    >
                      <X size={12} aria-hidden />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            {others.length ? (
              <div className="mt-2 flex items-center gap-2">
                <Plus size={14} className="text-muted" aria-hidden />
                <Select
                  size="sm"
                  label="Add a gene"
                  placeholder="Add a gene…"
                  value={undefined}
                  onValueChange={(g) => onChange({ genes: [...state.genes, g] })}
                  options={others.map((g) => ({ value: g, label: g }))}
                  className="w-48"
                />
              </div>
            ) : null}
          </fieldset>

          <div className="flex flex-col gap-1 text-[13px]">
            <label htmlFor="planner-plates" className="font-medium text-fg">
              Plates you have (optional)
            </label>
            <NumberField
              id="planner-plates"
              value={state.plates}
              min={1}
              max={64}
              allowEmpty
              placeholder="any"
              onCommit={(v) => onChange({ plates: v })}
            />
          </div>
        </div>

        {/* the answer */}
        <div className={cn("min-w-0 space-y-4", fetching && "opacity-80 transition-opacity")}>
          {planError ? (
            <ErrorPanel error={planError} title="This plan cannot be computed" compact />
          ) : !plan ? (
            <LoadingBlock label="Computing the plan" lines={6} />
          ) : (
            <>
              <p className="text-[16px] leading-snug font-medium text-fg">{plan.headline}</p>
              {leadRow && leadRow.current_mde_fold > 0 ? (
                <p className="text-[14px] leading-snug text-muted">
                  With this study’s own samples ({nCurrent.map((n) => count(n)).join(" vs ")}),{" "}
                  <span className="font-medium text-fg">{leadRow.gene}</span> can already detect
                  changes of{" "}
                  <span className="font-mono font-semibold text-fg tabular">
                    ≥ {fold(leadRow.current_mde_fold)}
                  </span>{" "}
                  (p &lt; {plan.alpha}, {percent(plan.power)} power); qPilot calls a true{" "}
                  {fold(plan.target)} change there {percent(leadRow.current_p_called)} of the time.
                </p>
              ) : null}
              {plan.ceiling ? (
                <p className="flex gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] leading-snug text-fg">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
                  <span>{plan.ceiling}</span>
                </p>
              ) : null}
              {plan.focus.length > plan.curves.length ? (
                <p className="text-[12px] text-muted">
                  The chart draws the first {count(plan.curves.length)} chosen genes; the tables
                  below have all {count(plan.focus.length)}.
                </p>
              ) : null}
              {plan.curves.length ? (
                <PowerChart
                  curves={plan.curves}
                  power={plan.power}
                  nPlan={plan.n_plan}
                  nEquivalent={plan.n_equivalent}
                  nCurrent={plan.n_current}
                  focus={leadRow?.gene ?? null}
                  onFocus={onLead}
                  minFold={plan.min_fold}
                  targetText={fold(plan.target)}
                />
              ) : null}
              <p className="text-[12px] text-muted">
                Each curve point is {count(plan.curve_reps)} simulated studies; the table’s chances
                are {count(plan.table_reps)} each. Solid: called by qPilot’s rule (p &lt;{" "}
                {plan.alpha} and at least {plan.min_fold}-fold, the right way); dashed: only
                significant.
              </p>
              <Chosen plan={plan} onLead={onLead} />
              {plan.layout ? (
                <p className="text-[13px] text-muted">
                  At {count(plan.n_plan)} per group these genes need{" "}
                  <span className="font-mono font-semibold text-fg tabular">
                    {count(plan.layout.plates)}
                  </span>{" "}
                  plate{plan.layout.plates === 1 ? "" : "s"} ({count(plan.layout.samples_per_plate)}{" "}
                  samples per plate
                  {plan.layout.calibrated ? ", with an inter-run calibrator" : ""}): see the plates
                  below.
                </p>
              ) : plan.layout_error ? (
                <p className="text-[13px] text-warn">{plan.layout_error}</p>
              ) : null}
              {plan.budget ? (
                <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
                  <span>{plan.budget.text}</span>
                  {plan.budget.n_fit != null && plan.budget.n_fit !== plan.n_plan ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        onChange({
                          autoN: false,
                          nIndex: nearestStop(N_STOPS, plan.budget!.n_fit!),
                        })
                      }
                    >
                      Plan at about {count(plan.budget.n_fit)} per group
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {plan.cannot_detect.length || plan.rules.length ? (
                <div className="space-y-1.5">
                  <h3 className="text-[13px] font-semibold text-fg">What this design cannot do</h3>
                  <ul className="space-y-1 text-[13px] leading-snug text-fg">
                    {[...plan.cannot_detect, ...plan.rules].map((line) => (
                      <li key={line} className="flex gap-2">
                        <AlertTriangle
                          size={14}
                          className="mt-0.5 shrink-0 text-warn"
                          aria-hidden
                        />
                        <span>{line}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

/** The chosen genes, side by side: what they need and what the plan and this study detect. */
function Chosen({ plan, onLead }: { plan: PlanView; onLead: (gene: string) => void }) {
  const rows = plan.genes.filter((g) => g.focus);
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <Table caption="The chosen genes under the plan">
        <THead>
          <TR>
            <TH>Gene</TH>
            <TH numeric>σ</TH>
            <TH numeric>n for p &lt; α</TH>
            <TH numeric>n for a call</TH>
            <TH numeric>Plan detects</TH>
            <TH numeric>Plan calls</TH>
            <TH numeric>Study detects</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((g) => (
            <TR key={g.gene}>
              <TD>
                <button
                  type="button"
                  className="font-medium text-fg hover:underline focus-visible:underline"
                  onClick={() => onLead(g.gene)}
                >
                  {g.gene}
                </button>
              </TD>
              <TD numeric>{g.sigma.toFixed(2)}</TD>
              <TD numeric>{count(g.n_needed)}</TD>
              <TD numeric>
                {g.n_for_call != null ? count(g.n_for_call) : <Badge tone="warn">none</Badge>}
              </TD>
              <TD numeric className={g.detectable ? undefined : "text-warn"}>
                ≥ {fold(g.mde_fold)}
              </TD>
              <TD numeric>{percent(g.p_called)}</TD>
              <TD numeric>{g.current_mde_fold > 0 ? `≥ ${fold(g.current_mde_fold)}` : "—"}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

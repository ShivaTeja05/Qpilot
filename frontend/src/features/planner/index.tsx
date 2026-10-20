/**
 * Plan next (docs/app.md §7, owner: planner): plan the next experiment from this one. The study
 * already measured how much each gene varies between samples of one group; the planner uses that
 * noise to say how many samples each gene needs, what a size can detect, how often qPilot's own
 * rule would call the change, and lays the experiment out on plates (CSV to import).
 *
 * Every number is the server's (`/api/studies/{id}/planner…`, from `qpilot.qpcr.plan` and
 * `qpilot.qpcr.layout`); the page only chooses the inputs.
 */
import { CalendarRange } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation } from "wouter";
import type { Schemas } from "@/api/client";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { count } from "@/lib/format";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  PageHeader,
} from "@/ui";
import {
  scopeOf,
  usePlan,
  usePlanner,
  type PlannerBody,
  type PlannerScope,
  type PlannerView,
} from "./api";
import { Explorer, type ExplorerState } from "./Explorer";
import { GeneTable } from "./GeneTable";
import { useDebounced } from "./hooks";
import { LayoutDesigner, type PlateSettings } from "./LayoutDesigner";
import { Measured } from "./Measured";
import { FOLD_STOPS, N_STOPS, POWER_STOPS, nearestStop } from "./words";

export default function PlannerSection({ workspace }: SectionProps) {
  if (!workspace) return null;
  return <PlannerPage workspace={workspace} />;
}

function PlannerPage({ workspace }: { workspace: Schemas["WorkspaceView"] }) {
  const scope = useMemo(() => scopeOf(workspace), [workspace]);
  const measured = usePlanner(scope);
  const [, navigate] = useLocation();

  const header = (
    <PageHeader
      eyebrow="Plan next"
      title="Plan the next experiment"
      hint="From the noise this study measured: how many samples each gene needs, what a design can detect, and the plates to run it on."
    />
  );

  if (!scope.studyId) {
    return (
      <div className="mx-auto w-full max-w-[1400px]">
        {header}
        <EmptyState
          icon={<CalendarRange aria-hidden />}
          title="Nothing to plan from yet"
          action={
            <Button onClick={() => navigate(sectionPath(workspace, "design"))}>Go to Design</Button>
          }
        >
          The planner uses the noise a finished analysis measured. Confirm the design and the curves
          first; the results then open here.
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-6">
      {header}
      {measured.error ? (
        <ErrorPanel
          error={measured.error}
          title="The planner cannot read this study"
          onRetry={() => void measured.refetch()}
        />
      ) : !measured.data ? (
        <Card>
          <CardBody>
            <LoadingBlock
              label="Measuring this study's noise (a few seconds the first time)"
              lines={5}
            />
          </CardBody>
        </Card>
      ) : (
        <Planner key={measured.data.head} scope={scope} view={measured.data} />
      )}
    </div>
  );
}

function Planner({ scope, view }: { scope: PlannerScope; view: PlannerView }) {
  const d = view.defaults;
  const [state, setState] = useState<ExplorerState>(() => ({
    foldIndex: nearestStop(FOLD_STOPS, Math.max(d.fold ?? 2, 1 / (d.fold ?? 2))),
    direction: (d.fold ?? 2) >= 1 ? "up" : "down",
    powerIndex: nearestStop(POWER_STOPS, d.power ?? 0.8),
    autoN: true,
    nIndex: nearestStop(N_STOPS, 12),
    genes: d.genes ?? [],
    plates: null,
  }));
  const [settings, setSettings] = useState<PlateSettings>(() => ({
    wells_per_plate: d.wells_per_plate === 384 ? 384 : 96,
    replicates: d.replicates ?? 2,
    ntc: d.controls?.ntc ?? 1,
    nrt: d.controls?.nrt ?? 0,
    standards: d.controls?.standards ?? 0,
    calibrator: d.controls?.calibrator ?? true,
    refs: d.refs ?? view.refs,
  }));
  const [lead, setLead] = useState<string | null>(state.genes[0] ?? null);

  const body = useMemo<PlannerBody>(() => {
    const magnitude = FOLD_STOPS[state.foldIndex]!;
    return {
      fold: state.direction === "up" ? magnitude : 1 / magnitude,
      power: POWER_STOPS[state.powerIndex]!,
      alpha: view.alpha,
      n_per_group: state.autoN ? null : N_STOPS[state.nIndex]!,
      genes: state.genes,
      refs: settings.refs,
      plates: state.plates,
      wells_per_plate: settings.wells_per_plate,
      replicates: settings.replicates,
      controls: {
        ntc: settings.ntc,
        nrt: settings.nrt,
        standards: settings.standards,
        calibrator: settings.calibrator,
      },
    };
  }, [state, settings, view.alpha]);
  const settled = useDebounced(body, 250);
  const plan = usePlan(scope, state.genes.length ? settled : null);

  const toggle = (gene: string) =>
    setState((s) => {
      if (s.genes.includes(gene))
        return s.genes.length > 1 ? { ...s, genes: s.genes.filter((g) => g !== gene) } : s;
      return { ...s, genes: [...s.genes, gene] };
    });
  const refChoices = useMemo(
    () => [...new Set([...view.refs, ...view.candidates])],
    [view.refs, view.candidates],
  );

  return (
    <>
      <Measured view={view} />
      <Explorer
        view={view}
        plan={plan.data}
        planError={plan.error}
        fetching={plan.isFetching}
        state={state}
        onChange={(next) => setState((s) => ({ ...s, ...next }))}
        lead={lead && state.genes.includes(lead) ? lead : (state.genes[0] ?? null)}
        onLead={setLead}
      />
      {plan.data ? (
        <Card as="section" aria-labelledby="planner-genes">
          <CardHeader
            id="planner-genes"
            title="Every gene under this plan"
            hint={`At ${count(plan.data.n_plan)} per group, for a ${plan.data.target.toFixed(2)}× change with ${Math.round(plan.data.power * 100)} % power. Noisy genes first.`}
          />
          <CardBody>
            <GeneTable
              plan={plan.data.genes}
              measured={view.genes}
              nPlan={plan.data.n_plan}
              target={`${plan.data.target.toFixed(2)}×`}
              onToggle={toggle}
            />
          </CardBody>
        </Card>
      ) : null}
      {plan.data ? (
        <LayoutDesigner
          scope={scope}
          genes={plan.data.focus}
          nPlan={plan.data.n_plan}
          settings={settings}
          onSettings={(next) => setSettings((s) => ({ ...s, ...next }))}
          refChoices={refChoices}
        />
      ) : null}
    </>
  );
}

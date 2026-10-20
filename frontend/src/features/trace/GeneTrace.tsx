/**
 * One gene's trace (`…/trace/<GENE>`): the call, the well to look at first, the dependency view
 * (result → groups → samples → wells → plates), the selected sample with the "what if I set it
 * aside?" switch (recomputed by the engine), the well's curve and plate, the places to look, the
 * fewest samples that change the call, the control genes' shares, every sample, and what was
 * checked. Selection, the open well and the samples set aside reset when the gene changes.
 */
import { ArrowLeft, ArrowUpRight, Microscope } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import {
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  JobCard,
  Select,
  Skeleton,
} from "@/ui";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { useReducedMotion } from "@/lib/hooks";
import {
  isNotFound,
  loadingJob,
  useTraceGene,
  useTraceStudy,
  useWithout,
  type TraceScope,
  type Well,
} from "./api";
import { Dependency } from "./Dependency";
import { FactText } from "./FactText";
import {
  CallFacts,
  Checked,
  FlipSet,
  LookFirst,
  Places,
  References,
  SamplePanel,
  SamplesTable,
  WithoutResult,
} from "./GenePieces";
import { WellCurve, WellFacts, WellPlate } from "./WellPanel";
import { address } from "./words";

type Workspace = Schemas["WorkspaceView"];

/** While the study's model loads (the first trace of a study), follow its job. */
export function TraceWaiting({
  error,
  onRetry,
  what,
}: {
  error: unknown;
  onRetry: () => void;
  what: string;
}) {
  const job = loadingJob(error);
  if (job) {
    return (
      <div className="flex flex-col gap-2" role="status">
        <p className="text-[13px] text-muted">
          Trace re-reads the study&rsquo;s wells from its file the first time (about a second on the
          demo); {what} opens as soon as it is done.
        </p>
        <JobCard id={job.id} job={null} />
      </div>
    );
  }
  return (
    <ErrorPanel
      title={`${what[0]!.toUpperCase()}${what.slice(1)} could not be traced`}
      error={error}
      onRetry={onRetry}
    />
  );
}

export function GeneTracePage({
  workspace,
  scope,
  gene,
}: {
  workspace: Workspace;
  scope: TraceScope;
  gene: string;
}) {
  const [, navigate] = useLocation();
  const reduced = useReducedMotion();
  const q = useTraceGene(scope, gene);
  const overview = useTraceStudy(scope);
  const data = q.data && q.data.trace.gene === gene ? q.data : undefined;
  const trace = data?.trace;

  // what is selected, per gene (a new gene starts from its own "look first")
  const [pick, setPick] = useState<{ gene: string; unit: string } | null>(null);
  const [open, setOpen] = useState<{ gene: string; well: Well } | null>(null);
  const [aside, setAside] = useState<{ gene: string; units: string[] }>({ gene, units: [] });
  const asideUnits = aside.gene === gene ? aside.units : [];
  const unit =
    (pick?.gene === gene ? pick.unit : null) ??
    trace?.look_first.unit ??
    trace?.samples[0]?.unit ??
    null;
  const well =
    open?.gene === gene
      ? open.well
      : trace?.look_first.kind === "place"
        ? (trace.look_first.well ?? null)
        : null;
  const sample = trace?.samples.find((s) => s.unit === unit) ?? null;
  const without = useWithout(scope, gene, asideUnits);

  const selectSample = (u: string) => setPick({ gene, unit: u });
  const openWell = (w: Well) => {
    setOpen({ gene, well: w });
    if (trace?.samples.some((s) => s.unit === w.unit)) setPick({ gene, unit: w.unit });
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1279px)").matches) {
      document
        .getElementById("trace-well")
        ?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
    }
  };
  const setUnits = (units: string[]) => setAside({ gene, units });
  const toggleAside = (u: string, on: boolean) =>
    setUnits(on ? [...new Set([...asideUnits, u])] : asideUnits.filter((x) => x !== u));

  const genes = useMemo(
    () =>
      [...(overview.data?.trace.genes.map((g) => g.gene) ?? [])].sort((a, b) => a.localeCompare(b)),
    [overview.data],
  );

  const nav = (
    <nav
      aria-label="Trace"
      className="mb-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2"
    >
      <Link
        href={sectionPath(workspace, "trace")}
        className="inline-flex items-center gap-1.5 rounded-md text-[13px] text-muted hover:text-fg"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        The whole study
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={sectionPath(workspace, "gene", gene)}
          className="inline-flex items-center gap-1 text-[13px] text-accent underline-offset-4 hover:underline"
        >
          Open {gene}&rsquo;s gene page
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
        {genes.length ? (
          <Select
            size="sm"
            label="Trace another gene"
            placeholder="Trace another gene"
            value={genes.includes(gene) ? gene : undefined}
            onValueChange={(g) => navigate(sectionPath(workspace, "trace", g))}
            options={genes.map((g) => ({ value: g, label: g }))}
            className="w-44"
          />
        ) : null}
      </div>
    </nav>
  );

  if (!data || !trace) {
    if (q.error && !loadingJob(q.error)) {
      return (
        <>
          {nav}
          {isNotFound(q.error) ? (
            <ErrorPanel title={`${gene} has no call to trace`} error={q.error}>
              <p className="mt-2 text-[13px] text-muted">
                Pick a compared gene with the menu above, or open the whole study.
              </p>
            </ErrorPanel>
          ) : (
            <TraceWaiting error={q.error} onRetry={() => void q.refetch()} what={gene} />
          )}
        </>
      );
    }
    return (
      <>
        {nav}
        <div className="flex flex-col gap-4">
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-4 w-[36rem] max-w-full" />
          {q.error ? (
            <TraceWaiting error={q.error} onRetry={() => void q.refetch()} what={gene} />
          ) : null}
          <Skeleton className="h-[480px] w-full rounded-xl" />
        </div>
      </>
    );
  }

  const texts = data.texts;
  const cell = trace.cell;

  return (
    <>
      {nav}
      <div
        className={cn("transition-opacity duration-150", q.isPlaceholderData && "opacity-60")}
        aria-busy={q.isFetching}
      >
        <header className="mb-5 flex flex-col gap-3">
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
              Trace
            </div>
            <h1 className="text-[32px] font-semibold leading-tight tracking-tight text-fg">
              {gene}
            </h1>
          </div>
          <p className="max-w-4xl text-[14px] leading-relaxed text-fg">
            <FactText text={texts.summary} />
          </p>
          <CallFacts call={trace.call} labels={trace.labels} />
          <p className="text-[12px] text-muted">
            {cell.planned
              ? "Traced at the planned analysis, the call Results shows."
              : "Traced at the options you chose on the Decision Cards, the call Results shows."}{" "}
            Control genes: {cell.refs.join(", ")}.{" "}
            {trace.rule[0]!.toUpperCase() + trace.rule.slice(1)}.
          </p>
        </header>
        <div className="mb-5">
          <LookFirst trace={trace} texts={texts} onWell={openWell} onSample={selectSample} />
        </div>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
          <div className="flex min-w-0 flex-col gap-5">
            <Card as="section" aria-labelledby="trace-dependency">
              <CardHeader
                id="trace-dependency"
                title={`What ${gene} stands on`}
                hint={`${count(trace.n_used)} samples in two groups, each a value from its own ${gene} well divided by its control-gene wells.`}
              />
              <CardBody>
                <Dependency
                  trace={trace}
                  selected={unit}
                  wellKey={well?.key ?? null}
                  onSample={selectSample}
                  onWell={openWell}
                />
              </CardBody>
            </Card>
            <Places
              workspace={workspace}
              trace={trace}
              texts={texts}
              onWell={openWell}
              onSample={selectSample}
            />
            <FlipSet trace={trace} texts={texts} onAside={setUnits} onSample={selectSample} />
            <References trace={trace} onWell={openWell} />
            <SamplesTable trace={trace} selected={unit} onSample={selectSample} />
            <Checked trace={trace} />
          </div>
          <aside
            className="flex min-w-0 flex-col gap-5 xl:sticky xl:top-4 xl:self-start"
            aria-label="The selected sample and well"
          >
            <WithoutResult
              workspace={workspace}
              gene={gene}
              aside={asideUnits}
              query={without}
              onClear={() => setUnits([])}
            />
            {sample ? (
              <SamplePanel
                trace={trace}
                sample={sample}
                aside={asideUnits.includes(sample.unit)}
                onAside={(on) => toggleAside(sample.unit, on)}
                onWell={openWell}
                wellKey={well?.key ?? null}
              />
            ) : null}
            <WellCard workspace={workspace} scope={scope} well={well} onWell={openWell} />
          </aside>
        </div>
      </div>
    </>
  );
}

function WellCard({
  workspace,
  scope,
  well,
  onWell,
}: {
  workspace: Workspace;
  scope: TraceScope;
  well: Well | null;
  onWell: (well: Well) => void;
}): ReactNode {
  return (
    <Card as="section" aria-labelledby="trace-well-title" id="trace-well" className="scroll-mt-4">
      <CardHeader
        id="trace-well-title"
        level={3}
        title={well ? `${well.gene} · ${address(well)}` : "A well"}
        hint={
          well
            ? `Sample ${well.unit}`
            : "Click a well in the view, a place or a sample's list to open it here."
        }
      />
      <CardBody className="flex flex-col gap-4">
        {well ? (
          <>
            <WellFacts well={well} />
            <WellCurve workspace={workspace} scope={scope} well={well} />
            <WellPlate scope={scope} well={well} onWell={onWell} />
          </>
        ) : (
          <EmptyState compact icon={<Microscope />} title="No well open" headingLevel={3}>
            Its curve and its plate show here, with the well marked.
          </EmptyState>
        )}
      </CardBody>
    </Card>
  );
}

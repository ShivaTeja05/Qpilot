/**
 * Gene (docs/app.md §4): one gene, everything about it. qPilot's result (call, fold [CI], p, n,
 * confidence and its reasons), what holds across other analyses, one choice at a time,
 * each sample's value and well, the audit's reading, the Decision Cards that move it, the assay,
 * the reference genes and (in a Studio session) its Prism figure. Deep-linkable at `…/gene/<GENE>`; `[` and `]` move between genes.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Microscope } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "wouter";
import type { SamplePoint } from "@/charts";
import { useJob } from "@/api/jobs";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { ConclusionTag, EmptyState, ErrorPanel, LoadingBlock, Skeleton } from "@/ui";
import { cn } from "@/lib/cn";
import { fold } from "@/lib/format";
import { useHotkeys, useReducedMotion } from "@/lib/hooks";
import type { Schemas } from "@/api/client";
import {
  geneQuery,
  isNotFound,
  scopeOf,
  useAuditSamples,
  useAuditStatus,
  useAuditView,
  useGene,
  useResults,
  useRunAudit,
  type GeneRow,
} from "./api";
import { effectChoiceRows, geneCardRefs, gridDots } from "./adapters";
import {
  AuditInvite,
  AuditReading,
  OneChoice,
  WhatHolds,
  YourSamples,
  type Source,
} from "./AuditParts";
import { GeneHeader, GeneNav } from "./GeneHeader";
import { neighbours, resolveGene } from "./nav";
import { SampleDetail } from "./SampleDetail";
import { carriedUnits, samplesSource, useGeneUnits } from "./units";
import { UnitSamples } from "./UnitSamples";
import { WellCurve } from "./WellCurve";
import { AssayWells, GeneCards, PrismCard, ReferenceStability } from "./StudyParts";
import { geneSummary, groupLabels } from "./words";

const NO_CHANGES: Record<string, string> = {};

export default function GeneSection({ workspace, rest }: SectionProps) {
  if (!workspace) return null;
  return <GenePage workspace={workspace} wanted={decoded(rest[0])} />;
}

/** A path segment as text (the router may hand it over encoded or not). */
function decoded(segment: string | undefined): string | undefined {
  if (!segment) return undefined;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function Page({ children }: { children: ReactNode }) {
  // The shell's <main> pads the page; this only keeps long lines readable on wide screens.
  return <div className="mx-auto w-full max-w-[1400px]">{children}</div>;
}

function GenePage({
  workspace,
  wanted,
}: {
  workspace: Schemas["WorkspaceView"];
  wanted: string | undefined;
}) {
  const scope = useMemo(() => scopeOf(workspace), [workspace]);
  const [, navigate] = useLocation();
  const qc = useQueryClient();
  const reducedMotion = useReducedMotion();

  const results = useResults(scope);
  const order = useMemo(() => results.data?.genes.map((g) => g.gene) ?? [], [results.data]);
  const geneName = resolveGene(order, wanted) ?? wanted ?? null;
  const gene = useGene(scope, geneName);
  const near = neighbours(order, geneName);
  // The server names the neighbours too (the study's order); prefer its words when the list is not loaded.
  if (!order.length && gene.data) {
    near.prev = gene.data.prev_gene ?? null;
    near.next = gene.data.next_gene ?? null;
  }
  const go = (g: string) => navigate(sectionPath(workspace, "gene", g));

  // `[` and `]` should open at once: read the neighbours while this gene is on screen.
  useEffect(() => {
    if (!gene.data || !scope.studyId) return;
    for (const n of [near.next, near.prev])
      if (n) void qc.prefetchQuery({ ...geneQuery(scope, n), staleTime: 60_000 });
  }, [gene.data, near.next, near.prev, qc, scope]);

  useHotkeys({
    "[": () => near.prev && go(near.prev),
    "]": () => near.next && go(near.next),
  });

  // A misspelt or lower-case gene in the link: show the study's spelling.
  useEffect(() => {
    if (wanted && geneName && geneName !== wanted)
      navigate(sectionPath(workspace, "gene", geneName), { replace: true });
  }, [wanted, geneName, workspace, navigate]);

  // ---- the audit
  const status = useAuditStatus(scope);
  const statusMissing = isNotFound(status.error);
  const audited = status.data?.status === "ready";
  // The first read of an audit loads its live views (~15 s); the views wait for that job.
  const warming =
    audited && status.data && !status.data.views_ready ? (status.data.loading ?? null) : null;
  const auditOutdated = status.data?.current === false ? (status.data.decisions_since ?? 0) : 0;
  const card = useAuditView(scope, "gene", geneName, audited);
  const notCovered = audited && isNotFound(card.error);
  const covered = audited && !notCovered;
  const analyses = useAuditView(scope, "analyses", geneName, covered);
  const effects = useAuditView(scope, "effects", geneName, covered);
  const lab = useAuditView(scope, "lab", geneName, covered);
  const samples = useAuditSamples(scope, geneName, NO_CHANGES, covered);
  // "Your samples" from the engine's per-unit values whenever the audit does not draw them, and
  // for an audited design with technical replicates (only the engine's values show each unit's
  // wells; the audit's marks are added to them).
  const replicateAudit = Boolean(status.data?.manifest?.scope?.technical_replicates);
  const samplesFrom = samplesSource(covered, replicateAudit);
  const units = useGeneUnits(scope, geneName, samplesFrom === "engine" && Boolean(gene.data));
  const carries = useMemo(
    () => (covered ? carriedUnits(samples.data?.points) : undefined),
    [covered, samples.data],
  );

  const run = useRunAudit(scope);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  useEffect(() => {
    const s = job.data?.status;
    if (s === "done" || s === "failed") void qc.invalidateQueries({ queryKey: ["w", scope.key] });
  }, [job.data?.status, qc, scope.key]);
  const startAudit = () => run.mutate(false, { onSuccess: (r) => setJobId(r.job.id) });

  const geneCards = useMemo(() => (gene.data ? geneCardRefs(gene.data) : []), [gene.data]);
  const dots = useMemo(() => (gene.data ? gridDots(gene.data) : []), [gene.data]);
  const choiceRowsQ = useMemo(() => (gene.data ? effectChoiceRows(gene.data) : []), [gene.data]);
  // Which analyses the charts draw: the audit's when there is one, else qPilot's grid.
  const [sourcePick, setSource] = useState<Source | null>(null);

  // ---- the selected sample, cleared when the gene changes
  const [selected, setSelected] = useState<{ gene: string | null; sample: string } | null>(null);
  const selectedSample = selected?.gene === geneName ? selected.sample : null;
  const selectSample = (sample: string) => setSelected({ gene: geneName, sample });
  const point = selectedSample
    ? samples.data?.points.find((p) => p.sample === selectedSample)
    : undefined;

  const labels = groupLabels(results.data);
  const rule = results.data?.rule;
  const references = results.data?.references;
  const used = references?.used ?? [];

  const nav = <GeneNav workspace={workspace} gene={geneName} order={order} near={near} onGo={go} />;

  if (!scope.studyId) {
    return (
      <Page>
        <EmptyState icon={<Microscope />} title="No results yet">
          Confirm the design and the curves first; then every gene has its own page here.
        </EmptyState>
      </Page>
    );
  }

  if (!wanted) {
    return (
      <Page>
        {nav}
        <GeneChooser
          workspace={workspace}
          genes={results.data?.genes}
          error={results.error}
          onRetry={() => void results.refetch()}
        />
      </Page>
    );
  }

  if (gene.error && !gene.data) {
    const isRef = geneName != null && used.includes(geneName);
    // Only the study's own gene list can say a gene is not there (a 404 may also be a route).
    const unknown =
      Boolean(results.data) && !order.includes(geneName ?? "") && isNotFound(gene.error);
    return (
      <Page>
        {nav}
        {isNotFound(gene.error) && isRef ? (
          <>
            <h1 className="mb-1 text-[32px] font-semibold tracking-tight text-fg">{geneName}</h1>
            <p className="mb-6 text-sm text-muted">
              A reference gene: the other genes are normalised to it, so it is not compared between
              the groups itself.
            </p>
            <ReferenceStability gene={geneName} genorm={references} />
          </>
        ) : unknown ? (
          <ErrorPanel title={`No gene called “${wanted}” in this study`} error={gene.error}>
            <p className="mt-2 text-[13px] text-muted">
              Pick one with the menu above, or go back to all genes.
            </p>
          </ErrorPanel>
        ) : (
          <ErrorPanel
            title={`${wanted} could not be opened`}
            error={gene.error}
            onRetry={() => void gene.refetch()}
          />
        )}
      </Page>
    );
  }

  if (!gene.data) {
    return (
      <Page>
        {nav}
        <div role="status" aria-label={`Loading ${wanted}`}>
          <Skeleton className="h-9 w-48" />
          <Skeleton className="mt-3 h-4 w-96 max-w-full" />
          <Skeleton className="mt-5 h-24 w-full rounded-xl" />
          <LoadingBlock className="mt-6" lines={6} label={`Loading ${wanted}`} />
        </div>
      </Page>
    );
  }

  const view = gene.data;
  const g = view.row;
  const auditCard = covered ? (card.data ?? null) : null;
  const source: Source = sourcePick ?? (covered ? "audit" : "qpilot");
  const line = rule?.min_log2fc ?? 1;
  const invite = (
    <AuditInvite
      workspace={workspace}
      status={status.data ?? null}
      job={job.data ?? null}
      onRun={status.data && !statusMissing ? startAudit : null}
      running={run.isPending}
      error={run.error}
      compact
    />
  );
  const notCoveredNote = notCovered ? (
    <p className="text-[13px] text-muted">
      The audit does not cover {g.gene}: {String((card.error as Error).message)}
    </p>
  ) : null;

  return (
    <Page>
      {nav}
      <div
        className={cn("transition-opacity duration-150", gene.isPlaceholderData && "opacity-60")}
        aria-busy={gene.isPlaceholderData}
      >
        <GeneHeader
          view={view}
          labels={labels}
          audit={auditCard}
          auditPending={covered && card.isPending}
          alpha={rule?.alpha}
          minLog2fc={rule?.min_log2fc}
          ruleText={rule?.text}
          auditOutdated={auditOutdated}
          summary={geneSummary({
            gene: g,
            labels,
            audit: auditCard,
            studyId: scope.studyId,
            chainHead: results.data?.head ?? workspace.decisions_head,
          })}
        />
        <JumpList hasAudit={Boolean(auditCard)} />
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-5">
            <WhatHolds
              gene={g.gene}
              holds={g.holds}
              nCells={g.n_cells}
              dots={dots}
              line={line}
              analyses={covered ? analyses : null}
              warming={warming}
              card={auditCard}
              source={source}
              onSource={setSource}
              labels={labels}
              invite={notCoveredNote ?? (covered ? null : invite)}
            />
            <OneChoice
              gene={g.gene}
              rows={choiceRowsQ}
              line={line}
              effects={covered ? effects : null}
              warming={warming}
              source={source}
              onSource={setSource}
              labels={labels}
            />
            {samplesFrom === "engine" ? (
              <UnitSamples
                units={units}
                selected={selectedSample}
                onSelect={(unit) => (unit ? selectSample(unit) : setSelected(null))}
                carries={carries}
                note={notCoveredNote}
                curve={(w) => (
                  <WellCurve
                    workspace={workspace}
                    scope={scope}
                    plate={w.plate}
                    well={w.well}
                    gene={g.gene}
                  />
                )}
              />
            ) : (
              <YourSamples
                samples={samples}
                warming={warming}
                labels={labels}
                selected={selectedSample}
                onSelect={(p: SamplePoint) => selectSample(p.sample)}
                detail={
                  point && samples.data ? (
                    <SampleDetail
                      point={point}
                      samples={samples.data}
                      onClose={() => setSelected(null)}
                      curve={
                        <WellCurve
                          workspace={workspace}
                          scope={scope}
                          plate={point.plate}
                          well={point.well}
                          gene={g.gene}
                        />
                      }
                    />
                  ) : null
                }
              />
            )}
            {auditCard ? (
              <AuditReading
                card={auditCard}
                onSample={(s) => {
                  selectSample(s);
                  const el = document.getElementById("gene-samples");
                  el?.scrollIntoView({
                    behavior: reducedMotion ? "auto" : "smooth",
                    block: "start",
                  });
                  el?.focus({ preventScroll: true });
                }}
              />
            ) : null}
          </div>
          <aside className="flex min-w-0 flex-col gap-5" aria-label={`More about ${g.gene}`}>
            <GeneCards workspace={workspace} gene={g.gene} cards={geneCards} />
            <AssayWells efficiency={g.efficiency} lab={covered ? lab.data : null} />
            <ReferenceStability gene={g.gene} genorm={references} lab={covered ? lab.data : null} />
            {workspace.kind === "session" ? (
              <PrismCard workspace={workspace} gene={g.gene} />
            ) : null}
          </aside>
        </div>
      </div>
    </Page>
  );
}

const JUMPS: { id: string; label: string; audit?: boolean }[] = [
  { id: "gene-holds", label: "What holds" },
  { id: "gene-choices", label: "One choice at a time" },
  { id: "gene-samples", label: "Your samples" },
  { id: "gene-reading", label: "What to do", audit: true },
  { id: "gene-cards", label: "Decision Cards" },
  { id: "gene-assay", label: "Assay and wells" },
  { id: "gene-refs", label: "Reference genes" },
];

/** In-page jumps (buttons, not `#` links: the page's routes live in the hash). */
function JumpList({ hasAudit }: { hasAudit: boolean }) {
  const reduced = useReducedMotion();
  return (
    <nav aria-label="On this page" className="mb-5 flex flex-wrap gap-1.5">
      {JUMPS.filter((j) => hasAudit || !j.audit).map((j) => (
        <button
          key={j.id}
          type="button"
          onClick={() => {
            const el = document.getElementById(j.id);
            el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
            el?.focus({ preventScroll: true });
          }}
          className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          {j.label}
        </button>
      ))}
    </nav>
  );
}

/** `…/gene` without a gene: every gene, headline genes first. */
function GeneChooser({
  workspace,
  genes,
  error,
  onRetry,
}: {
  workspace: Schemas["WorkspaceView"];
  genes: GeneRow[] | undefined;
  error: unknown;
  onRetry: () => void;
}) {
  const [, navigate] = useLocation();
  if (error) return <ErrorPanel error={error} onRetry={onRetry} />;
  if (!genes) return <LoadingBlock lines={6} label="Loading the genes" />;
  if (!genes.length)
    return (
      <EmptyState icon={<Microscope />} title="No genes compared in this study">
        The study has no gene of interest compared between groups.
      </EmptyState>
    );
  const sorted = [...genes].sort(
    (a, b) => Number(Boolean(b.headline)) - Number(Boolean(a.headline)),
  );
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-fg">Choose a gene</h1>
      <p className="mt-1 mb-5 text-sm text-muted">
        Every gene has its own page: its result, what holds, its samples and its wells.
      </p>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
        {sorted.map((g) => (
          <li key={g.gene}>
            <button
              type="button"
              onClick={() => navigate(sectionPath(workspace, "gene", g.gene))}
              className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-left text-[13px] hover:border-line-strong hover:bg-surface-2"
            >
              <span className="truncate font-medium text-fg">{g.gene}</span>
              <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted tabular">
                {fold(g.fc)}
                <ConclusionTag conclusion={g.conclusion} compact />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

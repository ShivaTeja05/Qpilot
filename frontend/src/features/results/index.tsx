/**
 * Results (docs/app.md §4): the summary, the robustness map, every gene, what one choice can flip,
 * the reference genes and the Decision Cards. Every number is the API's, for the open study.
 */
import { FlaskConical, Lock } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useLocation } from "wouter";
import { type MapEncoding } from "@/charts";
import { useMediaQuery } from "@/lib/hooks";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Button, EmptyState, ErrorPanel, PageHeader, Skeleton } from "@/ui";
import { isWarming, useCards, useFlips, useResults, type ResultsView } from "./api";
import { ChoicesConfirm } from "./ChoicesConfirm";
import { DecisionCards } from "./DecisionCards";
import { GenesPanel, NO_FILTER, isFiltered, matches, type GeneFilter } from "./GenesPanel";
import { MapPanel } from "./MapPanel";
import { FlipPanel, ReferencesPanel } from "./StudyPanels";
import { Summary } from "./Summary";

/** Genes the analysis could not give a result for, and why (never a made-up number). */
function Withheld({ view }: { view: ResultsView }) {
  const list = view.withheld;
  if (!list.length) return null;
  return (
    <details className="rounded-xl border border-line bg-surface px-4 py-3 text-[13px]">
      <summary className="cursor-pointer font-medium text-fg">
        {list.length === 1 ? "1 gene has" : `${list.length} genes have`} no result, and why
      </summary>
      <ul className="mt-2 space-y-1 text-muted">
        {list.map((w) => (
          <li key={w.gene}>
            <span className="font-medium text-fg">{w.gene}</span>: {w.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading the results">
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-6">
          <Skeleton className="h-[440px] w-full rounded-xl" />
          <Skeleton className="h-[360px] w-full rounded-xl" />
        </div>
        <div className="space-y-3">
          <Skeleton className="h-48 w-full rounded-xl" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}

export default function ResultsSection({ workspace, rest }: SectionProps) {
  const [, navigate] = useLocation();
  const key = workspace?.key ?? "";
  const studyId = workspace?.results_visible ? workspace.study_id : null;
  const results = useResults(key, studyId);
  const cards = useCards(key, studyId);
  const flips = useFlips(key, studyId);
  const [by, setBy] = useState<MapEncoding>("conclusion");
  const [filter, setFilter] = useState<GeneFilter>(NO_FILTER);

  const view = results.data;
  const openGene = useCallback(
    (gene: string) => navigate(sectionPath(workspace, "gene", gene)),
    [navigate, workspace],
  );
  const dimLabel = useCallback(
    (dim: string) =>
      flips.data?.rows.find((r) => r.dimension === dim)?.title ?? dim.replace(/_/g, " "),
    [flips.data],
  );
  const highlight = useMemo(
    () =>
      view && isFiltered(filter)
        ? new Set(view.genes.filter((g) => matches(g, filter)).map((g) => g.gene))
        : null,
    [view, filter],
  );

  const wide = useMediaQuery("(min-width: 1280px)");

  if (!workspace) return null;
  if (!workspace.results_visible) {
    const step = workspace.next_step;
    return (
      <div className="mx-auto max-w-3xl p-6 lg:p-10">
        <EmptyState
          icon={<Lock className="size-5" aria-hidden />}
          title="Results stay hidden until the design and the curves are confirmed"
          action={
            <Button
              onClick={() =>
                navigate(sectionPath(workspace, (step.section as "design") ?? "design"))
              }
            >
              {step.action ?? step.title}
            </Button>
          }
        >
          Nothing that shows a difference between groups is shown before then, so the choices are
          made blind. Next: {step.title}
          {step.detail ? `. ${step.detail}` : ""}
        </EmptyState>
      </div>
    );
  }
  if (!studyId) {
    return (
      <div className="mx-auto max-w-3xl p-6 lg:p-10">
        <EmptyState icon={<FlaskConical className="size-5" aria-hidden />} title="No analysis yet">
          This workspace has no analysed study. Confirm the design and the curves to analyse it.
        </EmptyState>
      </div>
    );
  }

  const map = view && (
    <MapPanel
      view={view}
      by={by}
      onBy={setBy}
      highlight={highlight}
      selected={null}
      onOpen={openGene}
    />
  );
  const rest_ = view && (
    <>
      <GenesPanel
        genes={view.genes}
        filter={filter}
        onFilter={setFilter}
        dimLabel={dimLabel}
        selected={null}
        onOpen={openGene}
      />
      {flips.error ? (
        <ErrorPanel error={flips.error} title="The flip matrix could not be read" compact />
      ) : (
        <FlipPanel flips={flips.data} onOpen={openGene} />
      )}
      <ReferencesPanel view={view} />
    </>
  );
  const decisions = cards.error ? (
    <ErrorPanel
      error={cards.error}
      title="The Decision Cards could not be read"
      onRetry={() => void cards.refetch()}
      compact
    />
  ) : !cards.data ? (
    <div className="space-y-3">
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="h-40 w-full rounded-xl" />
    </div>
  ) : (
    <div className="space-y-3">
      <DecisionCards
        view={cards.data}
        workspaceKey={key}
        studyId={studyId}
        focusCard={rest[0] === "card" ? (rest[1] ?? null) : null}
        nextAction={workspace.next_step.section === "results" ? workspace.next_step.action : null}
      />
      <ChoicesConfirm workspace={workspace} autoFocus={rest[0] === "confirm"} />
    </div>
  );

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Results"
        hint="Every gene's call, how well it holds across the analyses qPilot checks, and the choices still to decide."
      />
      {results.error ? (
        <ErrorPanel error={results.error} onRetry={() => void results.refetch()} />
      ) : !view ? (
        <>
          {isWarming(results) && (
            <p className="mb-4 text-[13px] text-muted" role="status">
              qPilot is reading this study for the first time; the results appear here when it is
              done.
            </p>
          )}
          <ResultsSkeleton />
        </>
      ) : (
        <div className="space-y-6">
          <Summary view={view} auditHref={sectionPath(workspace, "audit")} />
          <Withheld view={view} />
          {wide ? (
            <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-6">
              <div className="min-w-0 space-y-6">
                {map}
                {rest_}
              </div>
              <aside className="sticky top-4 max-h-[calc(100dvh-2rem)] min-w-0 self-start overflow-y-auto pr-1">
                {decisions}
              </aside>
            </div>
          ) : (
            <div className="space-y-6">
              {map}
              {decisions}
              {rest_}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

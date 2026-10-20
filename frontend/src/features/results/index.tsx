/**
 * Results (docs/app.md §4): the summary, the robustness map, every gene, what one choice can flip,
 * the reference genes and the Decision Cards. Every number is the API's, for the open study.
 */
import { FlaskConical, Lock } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useLocation } from "wouter";
import { type MapEncoding } from "@/charts";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Button, EmptyState, ErrorPanel, PageHeader, Skeleton } from "@/ui";
import { useCards, useResults } from "./api";
import { DecisionCards } from "./DecisionCards";
import { GenesPanel, NO_FILTER, isFiltered, matches, type GeneFilter } from "./GenesPanel";
import { MapPanel } from "./MapPanel";
import { FlipPanel, ReferencesPanel } from "./StudyPanels";
import { Summary } from "./Summary";

/** Which Decision Card kind decides which robustness dimension. */
const KIND_DIM: Record<string, string> = {
  reference_set: "refs",
  group_cutoff: "cut",
  amp_call: "amp_call",
  undetermined: "undetermined",
};

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

export default function ResultsSection({ workspace }: SectionProps) {
  const [, navigate] = useLocation();
  const key = workspace?.key ?? "";
  const studyId = workspace?.results_visible ? workspace.study_id : null;
  const results = useResults(key, studyId);
  const cards = useCards(key, studyId);
  const [by, setBy] = useState<MapEncoding>("conclusion");
  const [filter, setFilter] = useState<GeneFilter>(NO_FILTER);

  const view = results.data;
  const openGene = useCallback((gene: string) => navigate(sectionPath(workspace, "gene", gene)), [navigate, workspace]);
  const dimLabel = useCallback(
    (dim: string) => {
      const card = cards.data?.cards.find((c) => KIND_DIM[c.kind] === dim);
      return card?.title ?? dim.replace(/_/g, " ");
    },
    [cards.data],
  );
  const dims = useMemo(() => {
    const fromCards = (cards.data?.cards ?? []).map((c) => KIND_DIM[c.kind]).filter((d): d is string => Boolean(d));
    const fromGenes = (view?.genes ?? []).flatMap((g) => g.flips_by);
    return [...new Set([...fromCards, ...fromGenes])];
  }, [cards.data, view]);
  const highlight = useMemo(
    () => (view && isFiltered(filter) ? new Set(view.genes.filter((g) => matches(g, filter)).map((g) => g.gene)) : null),
    [view, filter],
  );

  if (!workspace) return null;
  if (!workspace.results_visible) {
    const step = workspace.next_step;
    return (
      <div className="mx-auto max-w-3xl p-6 lg:p-10">
        <EmptyState
          icon={<Lock className="size-5" aria-hidden />}
          title="Results stay hidden until the design and the curves are confirmed"
          action={
            <Button onClick={() => navigate(sectionPath(workspace, (step.section as "design") ?? "design"))}>{step.action ?? step.title}</Button>
          }
        >
          Nothing that shows a difference between groups is shown before then, so the choices are made blind. Next: {step.title}
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

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Results"
        hint="Every gene's call, how robust it is to reasonable analysis choices, and the choices still to decide."
      />
      {results.error ? (
        <ErrorPanel error={results.error} onRetry={() => void results.refetch()} />
      ) : !view ? (
        <ResultsSkeleton />
      ) : (
        <div className="space-y-6">
          <Summary view={view} auditHref={sectionPath(workspace, "audit")} />
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="min-w-0 space-y-6">
              <MapPanel view={view} by={by} onBy={setBy} highlight={highlight} selected={null} onOpen={openGene} />
              <GenesPanel genes={view.genes} filter={filter} onFilter={setFilter} dimLabel={dimLabel} selected={null} onOpen={openGene} />
              {dims.length > 0 && <FlipPanel genes={view.genes} dims={dims} dimLabel={dimLabel} onOpen={openGene} />}
              <ReferencesPanel view={view} />
            </div>
            <aside className="min-w-0 xl:sticky xl:top-4 xl:max-h-[calc(100dvh-2rem)] xl:self-start xl:overflow-y-auto xl:pr-1 max-xl:order-first">
              {cards.error ? (
                <ErrorPanel error={cards.error} title="The Decision Cards could not be read" onRetry={() => void cards.refetch()} compact />
              ) : !cards.data ? (
                <div className="space-y-3">
                  <Skeleton className="h-40 w-full rounded-xl" />
                  <Skeleton className="h-40 w-full rounded-xl" />
                </div>
              ) : (
                <DecisionCards view={cards.data} workspaceKey={key} studyId={studyId} headline={view.headline} />
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}

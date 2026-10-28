/**
 * Trace (docs/app.md §7, owner: trace): follow any number down to the samples, wells and plates
 * that drive it. `…/trace` is the study's overview (which calls hang on few samples, which
 * samples sit behind the most calls); `…/trace/<GENE>` follows one gene's call down to its
 * wells, with the "what if I set this sample aside?" recomputed by the engine.
 */
import { Route } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import type { SectionProps } from "@/shell/sections";
import { EmptyState, JobCard } from "@/ui";
import { scopeOf } from "./api";
import { GeneTracePage } from "./GeneTrace";
import { OverviewPage } from "./Overview";

function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1400px]">{children}</div>;
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

export default function TraceSection({ workspace, rest }: SectionProps) {
  const scope = useMemo(() => (workspace ? scopeOf(workspace) : null), [workspace]);
  if (!workspace || !scope) return null;
  const gene = decoded(rest[0]);
  if (!scope.studyId && workspace.results_visible) {
    // A person's decision (in Trace, Controls or Curves) changed the design: the study is
    // analysed again before it can be traced.
    const job = workspace.active_jobs.find((j) => j.kind === "analyse");
    return (
      <Page>
        <div className="flex flex-col gap-2" role="status">
          <h1 className="text-lg font-semibold tracking-tight text-fg">Trace</h1>
          <p className="text-[13px] text-muted">
            The study is being analysed again with the decision you made; it is traced at the new
            analysis as soon as that is done.
          </p>
          {job ? <JobCard id={job.id} job={null} /> : null}
        </div>
      </Page>
    );
  }
  if (!scope.studyId) {
    return (
      <Page>
        <EmptyState icon={<Route />} title="Nothing to trace yet" headingLevel={1}>
          Confirm the design and the curves first; then every result can be followed down to its
          samples, wells and plates here.
        </EmptyState>
      </Page>
    );
  }
  return (
    <Page>
      {gene ? (
        <GeneTracePage key={gene} workspace={workspace} scope={scope} gene={gene} />
      ) : (
        <OverviewPage workspace={workspace} scope={scope} />
      )}
    </Page>
  );
}

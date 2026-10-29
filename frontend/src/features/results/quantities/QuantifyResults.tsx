/**
 * Results of a study that quantifies samples (its design's purpose: no groups compared). The
 * main result is every sample's quantity from the standard curve (the Quantities card: the
 * curve, LOD, LOQ, each sample's quantity with its 95 % prediction interval, what is reported
 * for it, its wells); beside it the choices that can change what is reported (the quantity
 * cards: which wells count as detected, the LOQ line), decided by a person only when an option
 * changes a reported result, then confirmed. Every number is the API's.
 */
import { FlaskRound } from "lucide-react";
import type { Schemas } from "@/api/client";
import { count } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { ErrorPanel, PageHeader, Skeleton } from "@/ui";
import type { useCards } from "../api";
import { ChoicesConfirm } from "../ChoicesConfirm";
import { DecisionCards } from "../DecisionCards";
import { ImportTrustCard } from "../ImportTrust";
import { useQuantities, type QuantitiesView } from "./api";
import { QuantitiesPanel } from "./QuantitiesPanel";

/** Sample results by class over every assay, in the API's order of classes. */
export function classCounts(view: QuantitiesView): { id: string; words: string; n: number }[] {
  const total: Record<string, number> = {};
  for (const a of view.assays)
    for (const [k, n] of Object.entries(a.by_class ?? {})) total[k] = (total[k] ?? 0) + n;
  return (view.classes ?? [])
    .filter((c) => total[c.id])
    .map((c) => ({ id: c.id, words: c.words, n: total[c.id]! }))
    .reverse(); // most reportable first
}

function QuantifySummary({ view }: { view: QuantitiesView }) {
  const counts = classCounts(view);
  const total = counts.reduce((s, c) => s + c.n, 0);
  const assays = view.assays.map((a) => a.target);
  return (
    <section
      aria-labelledby="quantify-summary"
      className="rounded-xl border border-line bg-surface px-4 py-3"
    >
      <h2 id="quantify-summary" className="flex items-center gap-2 text-sm font-semibold text-fg">
        <FlaskRound className="size-4 text-muted" aria-hidden /> A quantification: no groups are
        compared
      </h2>
      <p className="mt-1 text-[13px] text-muted">
        {count(total)} sample result{total === 1 ? "" : "s"} ({assays.length} assay
        {assays.length === 1 ? "" : "s"}: {assays.join(", ")}), each read from its plate&apos;s
        standard curve.
      </p>
      {counts.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13px]" aria-label="By class">
          {counts.map((c) => (
            <li key={c.id} data-class={c.id}>
              <span className="tabular font-semibold text-fg">{count(c.n)}</span>{" "}
              <span className="text-muted">{c.words}</span>
            </li>
          ))}
        </ul>
      )}
      {view.analysis.length > 0 && (
        <p className="mt-2 text-[12.5px] text-muted">{view.analysis.join(" ")}</p>
      )}
    </section>
  );
}

export function QuantifyResults({
  workspace,
  studyId,
  cards,
  rest,
}: {
  workspace: Schemas["WorkspaceView"];
  studyId: string;
  cards: ReturnType<typeof useCards>;
  rest: string[];
}) {
  const key = workspace.key;
  const quantities = useQuantities(key, studyId);
  const wide = useMediaQuery("(min-width: 1280px)");
  const sid = workspace.kind === "session" ? workspace.key : null;
  const main = (
    <div className="min-w-0 space-y-6">
      {quantities.error ? (
        <ErrorPanel error={quantities.error} onRetry={() => void quantities.refetch()} />
      ) : quantities.data ? (
        <QuantifySummary view={quantities.data} />
      ) : (
        <Skeleton className="h-24 w-full rounded-xl" />
      )}
      <QuantitiesPanel workspaceKey={key} studyId={studyId} quantify sid={sid} />
    </div>
  );
  const decisions = cards.error ? (
    <ErrorPanel
      error={cards.error}
      title="The Decision Cards could not be read"
      onRetry={() => void cards.refetch()}
      compact
    />
  ) : !cards.data ? (
    <Skeleton className="h-40 w-full rounded-xl" />
  ) : (
    <div className="space-y-3">
      <ImportTrustCard
        workspaceKey={key}
        studyId={studyId}
        isSession={workspace.kind === "session"}
      />
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
        hint="Every sample's quantity from the standard curve, and the choices that could change what is reported for a sample."
      />
      {wide ? (
        <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-6">
          {main}
          <aside className="sticky top-4 max-h-[calc(100dvh-2rem)] min-w-0 self-start overflow-y-auto pr-1">
            {decisions}
          </aside>
        </div>
      ) : (
        <div className="space-y-6">
          {decisions}
          {main}
        </div>
      )}
    </div>
  );
}

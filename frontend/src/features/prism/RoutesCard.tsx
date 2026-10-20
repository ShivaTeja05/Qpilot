/**
 * Why the bridge matters: the usual routes from the instrument to Prism, recomputed by the engine
 * on this study's own plates, groups and reference genes, and how many conclusions each one
 * would draw differently (`qpilot/qpcr/routes.py`; facts `f_n_differ_route_*`).
 */
import { AlertTriangle, ChevronDown } from "lucide-react";
import { useState } from "react";
import { sectionPath } from "@/shell/sections";
import { Card, CardBody, CardHeader, ConclusionTag, ErrorPanel, LoadingBlock } from "@/ui";
import { cn } from "@/lib/cn";
import { count, ofTotal } from "@/lib/format";
import { asConclusion, CONCLUSION } from "@/lib/vocab";
import { usePrismRoutes, type PrismRoute, type PrismRoutes, type Workspace } from "./api";
import { ROUTE_ORDER, ROUTE_WORDS } from "./words";

/** The route a lab most often takes (2^-ΔΔCq, then a t test in Prism): the headline. */
const HEADLINE = "linear_welch";
const SHOWN = 10;

export function RoutesCard({ workspace }: { workspace: Workspace }) {
  const routes = usePrismRoutes(workspace.key);
  return (
    <Card as="section" aria-labelledby="prism-routes-title">
      <CardHeader
        id="prism-routes-title"
        title="What the usual route into Prism would change"
        hint="The same plates, groups and reference genes, taken through the steps most labs use between the instrument and Prism."
      />
      <CardBody>
        {routes.isPending ? (
          <LoadingBlock label="Recomputing the usual routes" lines={4} />
        ) : routes.error ? (
          <ErrorPanel
            error={routes.error}
            title="The route comparison could not be read"
            onRetry={() => void routes.refetch()}
            compact
          />
        ) : (
          <RoutesBody data={routes.data} workspace={workspace} />
        )}
      </CardBody>
    </Card>
  );
}

export function RoutesBody({ data, workspace }: { data: PrismRoutes; workspace: Workspace }) {
  const rows = [...data.routes].sort((a, b) => rank(a.route) - rank(b.route));
  if (!rows.length) {
    return (
      <p className="text-[13px] text-muted">
        This analysis has no route comparison: it needs two groups and at least one reference gene
        with a Cq in every sample. The bundle is still the engine's own analysis.
      </p>
    );
  }
  const headline =
    rows.find((r) => r.route === HEADLINE) ??
    rows.reduce((a, b) => (b.n_differ > a.n_differ ? b : a));
  const alarming = headline.n_differ > 0;
  return (
    <div className="flex flex-col gap-4">
      <div
        className={cn(
          "flex items-start gap-3 rounded-lg border p-3",
          alarming ? "border-danger/30 bg-danger-soft" : "border-line bg-surface-2",
        )}
      >
        {alarming ? (
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        ) : null}
        <p className="text-[15px] leading-snug text-fg">
          Taken the usual way — 2^-ΔΔCq in a spreadsheet, then a t test in Prism —{" "}
          <strong className={cn("font-semibold tabular", alarming && "text-danger")}>
            {ofTotal(headline.n_differ, headline.n_genes)}
          </strong>{" "}
          conclusions on this study come out differently from the engine's.
        </p>
      </div>

      <ol
        className="flex flex-col divide-y divide-line rounded-lg border border-line"
        aria-label="Routes into Prism"
      >
        {rows.map((row) => (
          <RouteItem key={row.route} row={row} workspace={workspace} engine={data.engine ?? null} />
        ))}
      </ol>

      <p className="text-[12px] leading-relaxed text-muted">
        Next to each gene is the engine's call; the route's call differs from it. Computed by
        qPilot's engine on this study, with the engine's call rule
        {data.rule ? ` (${data.rule})` : " (up or down only if p < 0.05 and at least two-fold)"};
        never used for a conclusion. What Send to Prism writes is the engine's own analysis — log2
        values, one per biological unit, and Welch's t test — so Prism starts from the engine's
        conclusions.
      </p>
    </div>
  );
}

function rank(id: string): number {
  const i = ROUTE_ORDER.indexOf(id);
  return i < 0 ? ROUTE_ORDER.length : i;
}

function RouteItem({
  row,
  workspace,
  engine,
}: {
  row: PrismRoute;
  workspace: Workspace;
  engine: Record<string, string> | null;
}) {
  const [all, setAll] = useState(false);
  const nGenes = row.n_genes;
  const words = ROUTE_WORDS[row.route];
  const share = nGenes > 0 ? row.n_differ / nGenes : 0;
  const genes = all ? row.genes : row.genes.slice(0, SHOWN);
  const listId = `prism-route-genes-${row.route}`;
  return (
    <li className="grid gap-3 p-3 md:grid-cols-[minmax(0,1fr)_9.5rem]">
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-fg">{words?.title ?? row.label}</p>
        {words ? <p className="mt-0.5 text-[12px] text-muted">{words.why}</p> : null}
        {row.genes.length ? (
          <div className="mt-2">
            <ul
              id={listId}
              className="flex flex-wrap gap-1.5"
              aria-label={`Genes this route concludes differently (${count(row.genes.length)})`}
            >
              {genes.map((g) => (
                <li key={g}>
                  <GeneChip gene={g} workspace={workspace} engine={engine?.[g]} />
                </li>
              ))}
            </ul>
            {row.genes.length > SHOWN ? (
              <button
                type="button"
                aria-expanded={all}
                aria-controls={listId}
                onClick={() => setAll((v) => !v)}
                className="mt-1.5 inline-flex items-center gap-1 text-[12px] text-muted underline-offset-2 hover:text-fg hover:underline"
              >
                <ChevronDown
                  className={cn("size-3.5 transition-transform", all && "rotate-180")}
                  aria-hidden
                />
                {all ? "Show fewer" : `Show all ${count(row.genes.length)}`}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5 md:items-end">
        <p className="text-[13px] text-fg">
          <span
            className={cn(
              "text-lg font-semibold tabular",
              row.n_differ > 0 ? "text-danger" : "text-ok",
            )}
          >
            {count(row.n_differ)}
          </span>
          <span className="text-muted"> of {count(nGenes)} differ</span>
        </p>
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle md:w-36"
          role="img"
          aria-label={`${ofTotal(row.n_differ, nGenes)} conclusions differ`}
        >
          <div
            className="h-full rounded-full bg-danger/70"
            style={{ width: `${Math.round(share * 100)}%` }}
          />
        </div>
      </div>
    </li>
  );
}

/** A gene this route concludes differently: the engine's call, and a link to the gene. */
function GeneChip({
  gene,
  workspace,
  engine,
}: {
  gene: string;
  workspace: Workspace;
  engine?: string;
}) {
  return (
    <a
      href={`#${sectionPath(workspace, "gene", gene)}`}
      className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-fg hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      title={
        !engine
          ? `Open ${gene}`
          : asConclusion(engine) === "none"
            ? `The engine makes no call on ${gene}; this route calls it up or down. Open ${gene}.`
            : `The engine calls ${gene} ${CONCLUSION[asConclusion(engine)].word}; this route does not. Open ${gene}.`
      }
    >
      {gene}
      {engine ? (
        <ConclusionTag conclusion={engine} compact className="font-sans text-[11px]" />
      ) : null}
    </a>
  );
}

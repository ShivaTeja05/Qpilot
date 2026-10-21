/**
 * The Study tab: the verdicts at a glance, every gene on the robustness map and in a list, which
 * choices change calls and how much of the spread each one makes, reference-gene stability, what
 * to fix before looking at results, and the issue queue. Every gene opens the Gene section.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import {
  GenormBars,
  HBars,
  RobustnessMap,
  SpreadBars,
  VERDICTS,
  VERDICT_ORDER,
  VerdictStrip,
  auditMapPoints,
  callKey,
  choicesAloneBars,
  choicesSpreadBars,
  isVerdict,
  type BarRow,
  type LegendItem,
} from "@/charts";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  EmptyState,
  ErrorPanel,
  Input,
  LoadingBlock,
  Skeleton,
  VerdictTag,
} from "@/ui";
import { type AuditTarget, shownError, useAuditIssues, useAuditStudy } from "./api";
import { IssueQueue } from "./IssueQueue";
import type { AuditOverview, AuditStudyView } from "./types";

export function StudyTab({
  target,
  overview,
  geneHref,
  onOpenLab,
}: {
  target: AuditTarget;
  overview: AuditOverview | undefined;
  /** Where a gene opens (the Gene section); null when the audit is not about this study. */
  geneHref: ((gene: string) => string) | null;
  onOpenLab: () => void;
}) {
  const study = useAuditStudy(target);
  const issues = useAuditIssues(target);
  const [, navigate] = useLocation();
  const [verdict, setVerdict] = useState<string | null>(null);
  const openGene = geneHref ? (gene: string) => navigate(geneHref(gene)) : undefined;

  const highlight = useMemo(
    () =>
      verdict && overview
        ? new Set(overview.genes.filter((g) => g.verdict === verdict).map((g) => g.gene))
        : null,
    [verdict, overview],
  );

  return (
    <div className="space-y-5">
      <section aria-labelledby="audit-verdicts">
        <h2 id="audit-verdicts" className="sr-only">
          Verdicts
        </h2>
        {overview ? (
          <VerdictStrip
            counts={overview.verdicts.map((v) => ({
              verdict: v.key,
              count: v.count,
              rule: v.rule,
              label: v.label,
            }))}
            selected={verdict}
            onSelect={setVerdict}
          />
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card as="section" aria-labelledby="audit-map">
          <CardHeader
            id="audit-map"
            title="Every gene"
            hint={`Fold change against the share of the audit's reasonable set${overview ? ` (${count(overview.study.reasonable)} analyses)` : ""} with the same call.${openGene ? " Click a gene to open it." : ""}`}
          />
          <CardBody>
            {study.data && overview ? (
              <StudyMap
                study={study.data}
                overview={overview}
                highlight={highlight}
                onSelect={openGene}
              />
            ) : shownError(study.error) ? (
              <ErrorPanel compact error={study.error} onRetry={() => void study.refetch()} />
            ) : (
              <Skeleton className="h-[360px] w-full rounded-lg" />
            )}
          </CardBody>
        </Card>
        <GeneList
          overview={overview}
          verdict={verdict}
          onClear={() => setVerdict(null)}
          geneHref={geneHref}
        />
      </div>

      {shownError(study.error) ? null : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card as="section" aria-labelledby="audit-alone">
            <CardHeader
              id="audit-alone"
              title="Calls changed by one choice alone"
              hint="Every option of one decision, every other choice as planned."
            />
            <CardBody>
              {study.data ? (
                <HBars
                  rows={choicesAloneBars(study.data)}
                  valueHeader="Calls changed"
                  summary={aloneSummary(study.data)}
                />
              ) : (
                <LoadingBlock lines={5} />
              )}
            </CardBody>
          </Card>
          <Card as="section" aria-labelledby="audit-spread">
            <CardHeader
              id="audit-spread"
              title="Share of the spread in fold change"
              hint={`Across the audit's reasonable set${overview ? ` (${count(overview.study.reasonable)} analyses)` : ""}, how much of the fold changes' spread each choice makes.`}
            />
            <CardBody>
              {study.data ? (
                <SpreadBars
                  rows={spreadRows(study.data)}
                  valueHeader="Share of the spread"
                  summary={spreadSummary(study.data)}
                />
              ) : (
                <LoadingBlock lines={5} />
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {study.data ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <References study={study.data} />
          <FixFirst study={study.data} />
        </div>
      ) : null}

      <IssueQueue
        issues={issues.data ?? overview?.issues}
        total={overview?.n_issues}
        loading={issues.isPending}
        error={
          shownError(issues.error) &&
          !(issues.error instanceof ApiError && issues.error.status === 404)
            ? issues.error
            : undefined
        }
        onRetry={() => void issues.refetch()}
        geneHref={geneHref}
        onOpenLab={onOpenLab}
      />
    </div>
  );
}

function StudyMap({
  study,
  overview,
  highlight,
  onSelect,
}: {
  study: AuditStudyView;
  overview: AuditOverview;
  highlight: ReadonlySet<string> | null;
  onSelect?: (gene: string) => void;
}) {
  const label = useMemo(() => new Map(overview.verdicts.map((v) => [v.key, v.label])), [overview]);
  const points = useMemo(() => auditMapPoints(study, (v) => label.get(v) ?? v), [study, label]);
  const legend: LegendItem[] = VERDICT_ORDER.map((v) => ({
    mark: VERDICTS[v],
    label: label.get(v) ?? VERDICTS[v].label,
    count: overview.verdicts.find((x) => x.key === v)?.count,
  })).filter((l) => (l.count ?? 0) > 0);
  const summary = `Map of ${plural(points.length, "gene")}: fold change (${overview.study.group} against ${overview.study.rest ?? "the rest"}) against the share of ${count(
    overview.study.reasonable,
  )} analyses of the audit's reasonable set with the same call; ${overview.verdicts
    .filter((v) => v.count)
    .map((v) => `${count(v.count)} ${v.label.toLowerCase()}`)
    .join(", ")}.`;
  return (
    <RobustnessMap
      points={points}
      line={study.line_log2}
      lineLabel={`${study.line} line`}
      lower={`lower in ${overview.study.group}`}
      higher={`higher in ${overview.study.group}`}
      legend={legend}
      summary={summary}
      highlight={highlight}
      onSelect={onSelect}
    />
  );
}

/** The genes, by verdict (most urgent first), filtered by the verdict strip and a search. */
function GeneList({
  overview,
  verdict,
  onClear,
  geneHref,
}: {
  overview: AuditOverview | undefined;
  verdict: string | null;
  onClear: () => void;
  geneHref: ((gene: string) => string) | null;
}) {
  const [query, setQuery] = useState("");
  const genes = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (overview?.genes ?? []).filter(
      (g) => (!verdict || g.verdict === verdict) && (!q || g.gene.toLowerCase().includes(q)),
    );
  }, [overview, verdict, query]);
  const selectedLabel = verdict ? overview?.verdicts.find((v) => v.key === verdict)?.label : null;
  return (
    <Card
      as="section"
      aria-labelledby="audit-genes"
      className="flex max-h-[480px] min-h-0 flex-col xl:max-h-[560px]"
    >
      <CardHeader
        id="audit-genes"
        title={selectedLabel ? `${selectedLabel}` : "Genes by verdict"}
        hint={
          overview
            ? selectedLabel
              ? plural(genes.length, "gene")
              : `${plural(overview.genes.length, "gene")}, most urgent first`
            : undefined
        }
        actions={
          verdict ? (
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-muted underline-offset-2 hover:text-fg hover:underline"
            >
              Show all
            </button>
          ) : null
        }
      />
      <div className="px-4 pb-2">
        <Input
          type="search"
          placeholder="Find a gene"
          aria-label="Find a gene"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {!overview ? (
          <LoadingBlock className="p-2" lines={6} />
        ) : !genes.length ? (
          <EmptyState compact title="No gene matches" className="m-2" />
        ) : (
          <ul aria-label="Genes">
            {genes.map((g) => (
              <li key={g.gene}>
                <GeneRow href={geneHref?.(g.gene)}>
                  <VerdictTag verdict={g.verdict} compact />
                  <span className="min-w-0">
                    <span
                      className={cn(
                        "block truncate text-sm text-fg",
                        g.headline && "font-semibold",
                      )}
                    >
                      {g.gene}
                      {g.headline ? (
                        <Badge className="ml-1.5 align-[1px]" tone="accent">
                          headline
                        </Badge>
                      ) : null}
                    </span>
                    {!isVerdict(g.verdict) ? (
                      <span className="block text-xs text-muted">{g.label}</span>
                    ) : null}
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted tabular">
                    {g.fold}
                    <ConclusionTag conclusion={callKey(g)} compact />
                  </span>
                </GeneRow>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** A gene's row: a link to the Gene section, or plain when the gene is not this study's. */
function GeneRow({ href, children }: { href: string | undefined; children: ReactNode }) {
  const cls = "grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-1.5";
  return href ? (
    <Link href={href} className={cn(cls, "hover:bg-bg-subtle")}>
      {children}
    </Link>
  ) : (
    <div className={cls}>{children}</div>
  );
}

function References({ study }: { study: AuditStudyView }) {
  const m = Object.fromEntries(study.references.map((r) => [r.gene, r.m_value ?? Number(r.m)]));
  const differs = new Set(study.references.filter((r) => r.differs).map((r) => r.gene));
  const cutoff = Number(study.stable_below);
  const note = study.reference_note
    ? study.reference_note[0]!.toUpperCase() + study.reference_note.slice(1)
    : "";
  return (
    <Card as="section" aria-labelledby="audit-refs">
      <CardHeader
        id="audit-refs"
        title="Reference gene stability"
        hint={`geNorm M of each candidate: lower is steadier, steady below ${study.stable_below}.`}
      />
      <CardBody className="space-y-3">
        {note ? (
          <p className="rounded-lg bg-warn-soft/60 px-3 py-2 text-[13px] text-fg">{note}.</p>
        ) : null}
        <GenormBars
          m={m}
          order={study.references.map((r) => r.gene)}
          cutoffM={cutoff}
          differs={differs}
          only="m"
        />
      </CardBody>
    </Card>
  );
}

function FixFirst({ study }: { study: AuditStudyView }) {
  const inf = study.influence;
  return (
    <Card as="section" aria-labelledby="audit-fix">
      <CardHeader
        id="audit-fix"
        title="Fix these before you look at results"
        hint="The choices that decide the most calls."
      />
      <CardBody className="space-y-3 text-sm">
        {study.lock_headline.length ? (
          <p className="text-fg">
            To protect the headline calls, fix <Names names={study.lock_headline} /> before you see
            results, and record why (a Decision Card).
          </p>
        ) : (
          <p className="text-muted">No single choice changes a headline call.</p>
        )}
        {study.lock_called.length ? (
          <p className="text-[13px] text-muted">
            In the audit's reasonable set, fixing <Names names={study.lock_called} /> protects every
            called gene.
          </p>
        ) : null}
        <ul className="space-y-1.5 border-t border-line pt-3 text-[13px] text-muted">
          {inf.one_sample_genes != null ? (
            <li>
              <span className="font-medium text-fg tabular">
                {plural(inf.one_sample_genes, "gene")}
              </span>{" "}
              change call when one sample is removed.
            </li>
          ) : null}
          {inf.ref_removals_flip != null ? (
            <li>
              <span className="font-medium text-fg tabular">{count(inf.ref_removals_flip)}</span> of{" "}
              <span className="tabular">{inf.ref_removals.replace(/,/g, " ")}</span> single
              reference-well removals change a call.
            </li>
          ) : null}
        </ul>
      </CardBody>
    </Card>
  );
}

function Names({ names }: { names: string[] }) {
  return (
    <>
      {names.map((n, i) => (
        <span key={n}>
          {i > 0 ? (i === names.length - 1 ? " and " : ", ") : null}
          <span className="font-semibold">{n}</span>
        </span>
      ))}
    </>
  );
}

/** The spread bars, with a note on the choices fixed in the audit's reasonable set (they change the question). */
function spreadRows(s: AuditStudyView): BarRow[] {
  const question = new Set(s.choices.filter((c) => c.question).map((c) => c.id));
  return choicesSpreadBars(s).map((r) =>
    question.has(r.key)
      ? { ...r, note: "fixed in the audit's reasonable set: it changes the question" }
      : r,
  );
}

function aloneSummary(s: AuditStudyView): string {
  const top = [...s.choices].sort((a, b) => b.alone - a.alone);
  const changing = top.filter((c) => c.alone > 0);
  if (!changing.length) return "No single choice changes a call on its own.";
  return `Calls changed by one choice alone: ${changing.map((c) => `${c.name.toLowerCase()} ${count(c.alone)}`).join(", ")}.`;
}

function spreadSummary(s: AuditStudyView): string {
  const top = [...s.choices].sort((a, b) => b.spread - a.spread).filter((c) => c.spread > 0);
  if (!top.length) return "No choice moves the fold changes across the audit's reasonable set.";
  return `Share of the spread in fold change: ${top.map((c) => `${c.name.toLowerCase()} ${c.spread} %`).join(", ")}.`;
}

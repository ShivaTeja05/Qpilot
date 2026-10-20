/**
 * The parts of the Gene section that the robustness audit fills: what holds across every
 * reasonable analysis, one choice at a time, each sample's value, and the audit's reading of the
 * gene (what changes it, what it leans on, what to do). Without an audit: an invitation to run it.
 */
import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import {
  AnalysesStrip,
  Beeswarm,
  ChoiceDotPlot,
  analysesDots,
  choiceRows,
  sampleGroups,
  samplePoints,
  type AnalysisDot,
  type ChoiceRow,
  type SamplePoint,
} from "@/charts";
import type { JobView, Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { Button, EmptyState, ErrorPanel, JobCard, LoadingBlock, SegmentedControl } from "@/ui";
import { cn } from "@/lib/cn";
import { count, ofTotal, percent } from "@/lib/format";
import type { AuditAnalyses, AuditEffects, AuditGeneCard, AuditSamples, AuditStatus } from "./api";
import { Panel, Sentences, Stat } from "./Panel";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

/** Axis end words: "lower in MYCN-high" / "higher in MYCN-high". */
export function sideWords(hi: string) {
  return { lower: `lower in ${hi}`, higher: `higher in ${hi}` };
}

/** A query's three states in one place: loading (or the audit's views warming up), error, data. */
function Loaded<T>({
  query,
  label,
  warming,
  children,
}: {
  query: Query<T>;
  label: string;
  /** The job loading the audit's live views (the first time, ~15 s): shown while waiting. */
  warming?: JobView | null;
  children: (data: T) => ReactNode;
}) {
  if (query.data) return <>{children(query.data)}</>;
  if (query.error) return <ErrorPanel compact error={query.error} onRetry={() => void query.refetch()} />;
  if (warming) return <JobCard id={warming.id} />;
  return <LoadingBlock label={label} lines={4} />;
}

// ---- the source switch ------------------------------------------------------------------------

export type Source = "qpilot" | "audit";

/** qPilot's own grid or the audit's reasonable analyses (shown when both exist). */
export function SourceSwitch({ value, onChange }: { value: Source; onChange: (v: Source) => void }) {
  return (
    <SegmentedControl
      size="sm"
      label="Which analyses"
      value={value}
      onValueChange={onChange}
      options={[
        { value: "audit", label: "The audit", title: "Every reasonable combination of the audit's eight decisions" },
        { value: "qpilot", label: "qPilot's grid", title: "Every combination of the Decision Cards' options" },
      ]}
    />
  );
}

type Query<T> = { data?: T; error: unknown; isPending: boolean; refetch: () => unknown };

// ---- What holds -------------------------------------------------------------------------------

export function WhatHolds({
  gene,
  holds,
  nCells,
  dots,
  line,
  analyses,
  card,
  source,
  onSource,
  labels,
  invite,
  warming,
}: {
  gene: string;
  /** qPilot's robustness share: its analyses with the planned call (0–1). */
  holds: number | null | undefined;
  nCells?: number | null;
  /** qPilot's grid, one dot per analysis. */
  dots: AnalysisDot[];
  /** The call rule's size line (log2). */
  line: number;
  /** The audit's analyses (null: not audited, or the audit does not cover this gene). */
  analyses: Query<AuditAnalyses> | null;
  card: AuditGeneCard | null;
  source: Source;
  onSource: (v: Source) => void;
  labels: { hi: string; lo: string };
  /** What to say about the audit when it is not there. */
  invite?: ReactNode;
  warming?: JobView | null;
}) {
  const a = analyses?.data;
  const showAudit = Boolean(analyses) && source === "audit";
  const sameQ = dots.filter((d) => d.same).length;
  return (
    <Panel
      id="gene-holds"
      title="What holds"
      hint="How often the same call comes out when the analysis is done another reasonable way."
      actions={analyses && dots.length ? <SourceSwitch value={source} onChange={onSource} /> : undefined}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-sunken/40 p-3">
          <Stat
            label="Same call, qPilot's grid"
            value={percent(holds)}
            sub={nCells ? `of ${count(nCells)} analyses over the Decision Cards' options` : "of qPilot's analyses over the Decision Cards' options"}
          />
          <HoldsBar share={holds ?? null} />
        </div>
        <div className="rounded-lg border border-line bg-sunken/40 p-3">
          {a ? (
            <>
              <Stat
                label="Same call, the audit"
                value={ofTotal(a.n_same, a.n)}
                sub="reasonable analyses over the audit's eight decisions"
              />
              <HoldsBar share={a.n ? a.n_same / a.n : null} />
            </>
          ) : (
            <Stat
              label="Same call, the audit"
              value={analyses ? "…" : "—"}
              sub={analyses ? "Reading the audit…" : "Not audited: the audit tries every reasonable combination of eight decisions."}
            />
          )}
        </div>
      </div>
      <div className="mt-4">
        {showAudit && analyses ? (
          <Loaded query={analyses} label="Reading every reasonable analysis" warming={warming}>
            {(data) => (
              <AnalysesStrip
                rows={analysesDots(data)}
                line={data.line_log2}
                lineLabel={`${data.line} line`}
                {...sideWords(labels.hi)}
                summary={`Every reasonable analysis of ${data.gene} in the audit, on the fold axis: ${ofTotal(data.n_same, data.n)} give the planned call (${data.base_call}); the planned analysis is ringed.`}
                caption={card?.holds.lines.length ? <Sentences items={card.holds.lines} /> : undefined}
              />
            )}
          </Loaded>
        ) : dots.length ? (
          <AnalysesStrip
            rows={dots}
            line={line}
            {...sideWords(labels.hi)}
            summary={`Every analysis of ${gene} in qPilot's grid, on the fold axis: ${ofTotal(sameQ, dots.length)} give the planned call; the planned analysis is ringed.`}
          />
        ) : (
          <p className="text-[13px] text-muted">qPilot's grid for this study is not available.</p>
        )}
      </div>
      {invite ? <div className="mt-4">{invite}</div> : null}
    </Panel>
  );
}

/** A thin bar for a share of analyses (decoration: the number beside it says it). */
function HoldsBar({ share }: { share: number | null }) {
  if (share == null || !Number.isFinite(share)) return null;
  return (
    <div aria-hidden className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-bg-subtle">
      <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(Math.min(1, Math.max(0, share)) * 100)}%` }} />
    </div>
  );
}

// ---- One choice at a time ---------------------------------------------------------------------

export function OneChoice({
  gene,
  rows,
  line,
  effects,
  source,
  onSource,
  labels,
  warming,
}: {
  gene: string;
  /** qPilot's decisions, one option at a time. */
  rows: ChoiceRow[];
  line: number;
  effects: Query<AuditEffects> | null;
  source: Source;
  onSource: (v: Source) => void;
  labels: { hi: string; lo: string };
  warming?: JobView | null;
}) {
  const showAudit = Boolean(effects) && source === "audit";
  const changingQ = rows.filter((r) => r.options.some((o) => o.changesCall));
  return (
    <Panel
      id="gene-choices"
      title="One choice at a time"
      hint="Each option of each decision, with every other choice as planned. A ringed dot changes the call on its own."
      actions={effects && rows.length ? <SourceSwitch value={source} onChange={onSource} /> : undefined}
    >
      {showAudit && effects ? (
        <Loaded query={effects} label="Reading one choice at a time" warming={warming}>
          {(data) => {
            const changing = data.decisions.filter((d) => d.n_change > 0);
            return (
              <ChoiceDotPlot
                decisions={choiceRows(data)}
                line={data.line_log2}
                lineLabel={`${data.line} line`}
                {...sideWords(labels.hi)}
                summary={
                  changing.length
                    ? `${data.gene} at ${data.planned} as planned. ${count(changing.length)} of ${count(data.decisions.length)} of the audit's decisions have an option that changes the call on its own: ${changing.map((d) => d.name).join(", ")}.`
                    : `${data.gene} at ${data.planned} as planned. No single option of the audit's ${count(data.decisions.length)} decisions changes the call on its own.`
                }
              />
            );
          }}
        </Loaded>
      ) : rows.length ? (
        <ChoiceDotPlot
          decisions={rows}
          line={line}
          {...sideWords(labels.hi)}
          summary={
            changingQ.length
              ? `${gene}, one Decision Card choice at a time: ${count(changingQ.length)} of ${count(rows.length)} decisions have an option that changes the call on its own: ${changingQ.map((r) => r.name).join(", ")}.`
              : `${gene}, one Decision Card choice at a time: no single option of the ${count(rows.length)} decisions changes the call on its own.`
          }
        />
      ) : (
        <p className="text-[13px] text-muted">No decision is varied for this gene.</p>
      )}
    </Panel>
  );
}

// ---- Your samples -----------------------------------------------------------------------------

export function YourSamples({
  samples,
  labels,
  selected,
  onSelect,
  detail,
  invite,
  warming,
}: {
  samples: Query<AuditSamples> | null;
  labels: { hi: string; lo: string };
  selected: string | null;
  onSelect: (p: SamplePoint) => void;
  /** The selected sample's well and curve. */
  detail?: ReactNode;
  invite?: ReactNode;
  warming?: JobView | null;
}) {
  return (
    <Panel
      id="gene-samples"
      title="Your samples"
      hint="Each sample's normalised value, relative to the mean of the rest. Click a sample to open its well."
    >
      {samples ? (
        <Loaded query={samples} label="Reading each sample's value" warming={warming}>
          {(data) => {
            const carries = data.points.filter((p) => p.carries).length;
            const late = data.points.filter((p) => p.late).length;
            const flagged = data.points.filter((p) => p.flagged).length;
            const groups = Object.values(data.groups);
            return (
              <>
                <Beeswarm
                  groups={sampleGroups(data)}
                  points={samplePoints(data)}
                  foldText={data.fold}
                  lateCut={data.late_cut}
                  {...sideWords(labels.hi)}
                  selected={selected}
                  onSelectSample={onSelect}
                  summary={`${data.gene} in ${groups.map((g) => `${count(g.n)} ${g.label}`).join(" and ")} samples: ${data.fold}.${carries ? ` ${count(carries)} samples each change the call when left out.` : ""}${late ? ` ${count(late)} wells have a late Cq.` : ""}${flagged ? ` ${count(flagged)} wells are flagged.` : ""}`}
                />
                {groups.some((g) => g.missing) ? (
                  <p className="mt-2 text-xs text-muted">
                    Not shown (no usable value):{" "}
                    {groups
                      .filter((g) => g.missing)
                      .map((g) => `${count(g.missing)} in ${g.label}`)
                      .join(", ")}
                    .
                  </p>
                ) : null}
                {detail}
              </>
            );
          }}
        </Loaded>
      ) : (
        invite
      )}
    </Panel>
  );
}

// ---- The audit's reading ----------------------------------------------------------------------

function Block({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <h3 className="mb-2 text-[13px] font-semibold text-fg">{title}</h3>
      {children}
    </div>
  );
}

export function AuditReading({
  card,
  onSample,
}: {
  card: AuditGeneCard;
  /** Open a sample the call leans on (its well). */
  onSample?: (sample: string) => void;
}) {
  return (
    <Panel
      id="gene-reading"
      title="What changes it, what it leans on, what to do"
      hint="The audit's reading of this gene."
    >
      <div className="grid gap-6 lg:grid-cols-3">
        <Block title="What changes it">
          {card.changes.length ? (
            <ul className="space-y-1.5 text-[13px]">
              {card.changes.map((c, i) => (
                <li key={`${i}:${c.choice}`} className="rounded-lg border border-line px-2.5 py-2">
                  <span className="font-medium text-fg">{c.choice}</span>
                  <span className={cn("block", c.same_call ? "text-muted" : "text-warn")}>
                    {c.fold}, {c.call}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted">{card.no_changes ?? "No reasonable choice changes it."}</p>
          )}
          {card.shortcut ? <p className="mt-2 text-xs text-muted">{card.shortcut}</p> : null}
        </Block>
        <Block title="What it leans on">
          <Sentences items={card.leans} />
          {card.singles.length ? (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Samples that change the call on their own">
              {card.singles.map((s) => (
                <li key={`${s.sample}:${s.well}`}>
                  <button
                    type="button"
                    onClick={() => onSample?.(s.sample)}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg hover:border-line-strong"
                    title={`Leaving it out: ${s.call}`}
                  >
                    <span className="font-medium">{s.sample}</span>
                    <span className="text-muted">
                      {" "}
                      · plate {s.plate} · {s.well}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </Block>
        <Block title="What to do">
          <Sentences items={card.todo} />
        </Block>
      </div>
    </Panel>
  );
}

// ---- Without an audit -------------------------------------------------------------------------

/** The audit is not there (yet): say what it adds, and start it or say why it cannot run. */
export function AuditInvite({
  workspace,
  status,
  job,
  onRun,
  running,
  error,
  compact,
}: {
  workspace: Workspace;
  status: AuditStatus | null;
  /** A job started from here (or the server's running one). */
  job: JobView | null;
  onRun: (() => void) | null;
  running?: boolean;
  error?: unknown;
  compact?: boolean;
}) {
  const auditPath = sectionPath(workspace, "audit");
  if (job || status?.status === "running") {
    return <JobCard id={job?.id ?? status?.job?.id ?? null} />;
  }
  if (status?.status === "failed") {
    return (
      <ErrorPanel title="The audit stopped before finishing" error={new Error(status.reason ?? status.job?.error?.message ?? "It stopped before finishing.")}>
        {onRun ? (
          <Button size="sm" className="mt-3" loading={running} onClick={onRun}>
            Run the audit again
          </Button>
        ) : null}
      </ErrorPanel>
    );
  }
  if (status && ["refused", "not_applicable", "unavailable"].includes(status.status)) {
    return (
      <EmptyState compact icon={<ShieldCheck />} title="The audit cannot run on this study">
        {status.reason ?? "The robustness audit does not apply here."}
      </EmptyState>
    );
  }
  return (
    <EmptyState
      compact={compact}
      icon={<ShieldCheck />}
      title="Audit this result"
      action={
        <>
          {onRun ? (
            <Button variant="primary" loading={running} onClick={onRun}>
              Run the audit
            </Button>
          ) : null}
          <Button variant="ghost" asChild>
            <Link href={auditPath}>What the audit does</Link>
          </Button>
        </>
      }
    >
      The robustness audit re-runs your confirmed study under every combination of eight analysis decisions
      (about 50 s on the demo) and gives each gene a verdict. Here it adds every reasonable analysis, one choice
      at a time, each sample's value and what to do.
      {error ? <ErrorPanel compact className="mt-3 text-left" error={error} /> : null}
    </EmptyState>
  );
}

/**
 * Controls (Run Gate, docs/app.md §4): every plate's controls checked against the rule pack, and
 * whether leaving out the wells a rule points at would change any conclusion. The headline, the
 * plate strip (gated / ungated, worst verdict), the rule checks (verdict chip, reason, wells,
 * consequence), what leaving wells out changes, and the `gate.rule` Decision Cards. Rules label;
 * in a Studio session a person decides the cards here (the wells become curve exclusions and the
 * study is analysed again); a study analysed outside Studio is read-only.
 */
import { ListChecks } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "wouter";
import type { Schemas } from "@/api/client";
import { FactText } from "@/features/results/FactText";
import { count, plural } from "@/lib/format";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  Hash,
  JobCard,
  PageHeader,
  Skeleton,
} from "@/ui";
import { scopeOf, useGate, loadingJob, type GateScope, type GateView } from "./api";
import { GateCards } from "./Cards";
import { ClassChip, PlateStrip, VerdictCounts } from "./Pieces";
import { RuleList } from "./Rules";
import { DEFAULT_FILTER, leadOption, whereText, type RuleFilter } from "./words";

type Workspace = Schemas["WorkspaceView"];

function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1400px]">{children}</div>;
}

function Header({ view }: { view?: GateView }) {
  return (
    <PageHeader
      eyebrow="Controls"
      title="What the controls on each plate say"
      hint="Every plate's controls checked against a rule pack, and whether leaving out the wells a rule points at would change any conclusion. Rules label; only a person decides what a finding means for the analysis."
      actions={
        view ? (
          <span className="text-[12px] text-muted">
            Pack {view.pack.name} {view.pack.version} ·{" "}
            <Hash value={view.pack.hash} prefix="hash" />
          </span>
        ) : null
      }
    />
  );
}

export function Waiting({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const job = loadingJob(error);
  if (job) {
    return (
      <div className="flex flex-col gap-2" role="status">
        <p className="text-[13px] text-muted">
          The first time, every plate&rsquo;s controls are checked and the analysis is re-run
          without the wells they point at (about six seconds on the demo); the page opens as soon as
          it is done.
        </p>
        <JobCard id={job.id} job={null} />
      </div>
    );
  }
  return <ErrorPanel title="The controls could not be checked" error={error} onRetry={onRetry} />;
}

/** What leaving wells out changes, one line per tested finding (opens its rule check). */
function Consequences({ view, onOpen }: { view: GateView; onOpen: (id: string) => void }) {
  const byId = new Map(view.evaluations.map((e) => [e.id, e]));
  if (view.consequences.length === 0) return null;
  return (
    <Card as="section" aria-labelledby="gate-conseq-title">
      <CardHeader
        id="gate-conseq-title"
        title="What leaving the wells out would change"
        hint={`For each of the ${plural(view.consequences.length, "rule check")} that warns or fails and points at wells, the whole analysis was re-run without them, measured at ${view.analysis === "planned" ? "the planned analysis" : "the options you chose on the Decision Cards"}.`}
      />
      <ul className="border-t border-line">
        {view.consequences.map((c) => {
          const e = byId.get(c.id);
          const lead = leadOption(c);
          return (
            <li
              key={c.id}
              className="flex flex-col gap-1 border-b border-line px-4 py-2.5 last:border-b-0 sm:flex-row sm:items-start sm:gap-3"
            >
              <span className="w-[10rem] shrink-0 pt-0.5">
                <ClassChip value={c.consequence} />
              </span>
              <span className="min-w-0 flex-1 text-[13px]">
                <span className="block font-medium text-fg">
                  <span className="font-mono text-[12px] text-muted">{c.rule_id}</span> {c.title}
                  <span className="font-normal text-muted"> · {e ? whereText(e) : ""}</span>
                </span>
                {lead && (
                  <span className="block text-fg">
                    <FactText text={lead.text} />
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => onOpen(c.id)}
                className="shrink-0 self-start text-[13px] font-medium text-accent hover:underline"
              >
                Show the check
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function PackRules({ view }: { view: GateView }) {
  return (
    <Card as="section" aria-labelledby="gate-pack-title">
      <CardHeader
        id="gate-pack-title"
        title="The rules and where their thresholds come from"
        hint={view.pack.label}
      />
      <CardBody>
        <ul className="flex flex-col gap-2">
          {view.pack.rules.map((r) => (
            <li key={r.rule_id}>
              <details className="rounded-lg border border-line px-3 py-2 text-[13px]">
                <summary className="cursor-pointer select-none font-medium text-fg">
                  <span className="font-mono text-[12px] text-muted">{r.rule_id}</span> {r.title}
                  {r.informational && (
                    <span className="font-normal text-muted"> · logged only</span>
                  )}
                </summary>
                <p className="mt-1.5 leading-relaxed text-fg">{r.statement}</p>
                <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-[12px] text-muted">
                  {r.sources.map((s) => (
                    <li key={s.key}>
                      {s.citation}
                      {s.url ? (
                        <span className="ml-1 break-all font-mono text-[11px]">{s.url}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

export function GatePage({
  view,
  workspace,
  scope,
}: {
  view: GateView;
  workspace: Workspace;
  scope?: GateScope;
}) {
  const [filter, setFilter] = useState<RuleFilter>(DEFAULT_FILTER);
  const [focus, setFocus] = useState<string | null>(null);
  const open = (id: string) => {
    setFilter({ ...DEFAULT_FILTER, verdict: "all" });
    setFocus(id);
  };
  return (
    <>
      <Header view={view} />
      <Card as="section" aria-labelledby="gate-summary-title" className="mb-5">
        <CardHeader id="gate-summary-title" title="In one line" />
        <CardBody className="flex flex-col gap-3">
          <p className="max-w-4xl text-[15px] leading-relaxed text-fg">
            <FactText text={view.headline} />
          </p>
          <VerdictCounts counts={view.counts} />
          <p className="text-[13px] text-muted">
            {view.how_to_apply}{" "}
            {view.exclude_in === "curves" ? (
              <Link
                href={sectionPath(workspace, "curves")}
                className="font-medium text-accent hover:underline"
              >
                See the exclusions in Curves
              </Link>
            ) : (
              <Link
                href={sectionPath(workspace, "trace")}
                className="font-medium text-accent hover:underline"
              >
                Go to Trace
              </Link>
            )}
          </p>
        </CardBody>
      </Card>
      <Card as="section" aria-labelledby="gate-plates-title" className="mb-5">
        <CardHeader
          id="gate-plates-title"
          title="Plates"
          hint={`${count(view.n_gated)} gated, ${count(view.n_ungated)} ungated (no wells typed as controls). Each shows its worst verdict; pick one to see only its checks.`}
        />
        <CardBody>
          <PlateStrip
            plates={view.plates}
            selected={filter.plate}
            onSelect={(plate) => setFilter({ ...filter, plate })}
          />
        </CardBody>
      </Card>
      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] [&>*]:min-w-0">
        <div className="flex min-w-0 flex-col gap-5">
          <RuleList view={view} filter={filter} onFilter={setFilter} focusId={focus} />
          <Consequences view={view} onOpen={open} />
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <GateCards view={view} workspace={workspace} scope={scope} />
          <PackRules view={view} />
        </div>
      </div>
    </>
  );
}

export default function GateSection({ workspace }: SectionProps) {
  const scope = useMemo(() => (workspace ? scopeOf(workspace) : null), [workspace]);
  const q = useGate(scope ?? { key: "", studyId: null, kind: "study" });
  if (!workspace || !scope) return null;
  if (!scope.studyId && workspace.results_visible) {
    // A person's decision changed the design: the study is analysed again before it is gated.
    const job = workspace.active_jobs.find((j) => j.kind === "analyse");
    return (
      <Page>
        <Header />
        <div className="flex flex-col gap-2" role="status">
          <p className="text-[13px] text-muted">
            The study is being analysed again with the decision you made; its controls are checked
            at the new analysis as soon as it is done.
          </p>
          {job && <JobCard id={job.id} job={null} />}
        </div>
      </Page>
    );
  }
  if (!scope.studyId) {
    return (
      <Page>
        <EmptyState icon={<ListChecks />} title="No controls to check yet" headingLevel={1}>
          Confirm the design and the curves first; then every plate&rsquo;s controls are checked
          here, with what leaving their wells out would change.
        </EmptyState>
      </Page>
    );
  }
  // While the gate.run job works, the query retries: its 409 `loading` is the failure reason.
  const waiting = q.error ?? (loadingJob(q.failureReason) ? q.failureReason : null);
  if (!q.data) {
    return (
      <Page>
        <Header />
        {waiting ? (
          <Waiting error={waiting} onRetry={() => void q.refetch()} />
        ) : (
          <div className="flex flex-col gap-4" role="status" aria-label="Checking the controls">
            <Skeleton className="h-4 w-[32rem] max-w-full" />
            <Skeleton className="h-64 w-full rounded-xl" />
          </div>
        )}
      </Page>
    );
  }
  return (
    <Page>
      <GatePage view={q.data} workspace={workspace} scope={scope} />
    </Page>
  );
}

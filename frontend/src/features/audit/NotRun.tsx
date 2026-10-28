/**
 * The audit has not run on this study (or is running now): what it is, in plain words, what it
 * checks before it runs, its scale, and **Run the audit** with the job's progress.
 */
import { Loader2, Play } from "lucide-react";
import { useEffect } from "react";
import type { SectionProps } from "@/shell/sections";
import { useJob } from "@/api/jobs";
import { count, duration } from "@/lib/format";
import type { Verdict } from "@/lib/vocab";
import { Button, Card, CardBody, CardHeader, ErrorPanel, JobCard, VerdictTag } from "@/ui";
import { useInvalidateAudit, useRunAudit, useSeedJob, type AuditTarget } from "./api";
import type { AuditStatus } from "./types";
import { ReplicatesNote } from "./ReplicatesNote";
import { decisionWords } from "./words";

/** What each verdict means, without the audit's thresholds (they come with the audit). */
const VERDICT_MEANING: Record<Verdict, string> = {
  solid:
    "The same call in nearly all of the audit's reasonable set, and no handful of samples changes it.",
  "holds with caveats":
    "The same call nearly everywhere, but it rests on a few samples or the difference is not always clear.",
  "depends on your choices":
    "Most of the audit's reasonable set agrees; the rest turn on named choices you should fix and report.",
  fragile:
    "Changes with reasonable choices, with one or two samples, or sits close to the line a call needs.",
  "check data first": "A problem found in the data changes this call when it is fixed.",
  "no call":
    "Not called a change; the audit says whether some analyses in its reasonable set would call it.",
};

export function NotRun({
  workspace,
  target,
  status,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
  status: AuditStatus;
}) {
  const run = useRunAudit(target);
  useSeedJob(status.job);
  const jobId = run.data?.job.id ?? status.job?.id ?? null;
  const job = useJob(jobId);
  const invalidate = useInvalidateAudit(target);
  // A finished audit opens the verdicts; a refused one turns into its reason (the status says).
  const settled = job.data?.status === "done" || job.data?.status === "failed";
  useEffect(() => {
    if (settled) void invalidate();
  }, [settled, invalidate]);
  const running = job.data
    ? job.data.status === "queued" || job.data.status === "running"
    : Boolean(jobId);

  // The server checks that the audit applies (its first step, alone) and says what it would
  // cover for this study; the status is re-read when that check is done.
  useSeedJob(status.checking);
  const checking = useJob(status.checking?.id);
  const checked = checking.data?.status === "done" || checking.data?.status === "failed";
  useEffect(() => {
    if (checked) void invalidate();
  }, [checked, invalidate]);
  const scope = status.check?.scope;
  const decisions = decisionWords(Boolean(scope?.technical_replicates?.varied));
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Card as="section" aria-labelledby="audit-what">
        <CardHeader id="audit-what" title="What the audit does" />
        <CardBody className="@container space-y-4 text-sm leading-relaxed text-fg">
          <p>
            It re-runs your confirmed study under every combination of {decisions.count} analysis
            decisions ({decisions.words}) and gives each gene a verdict: does its call hold
            whichever analysis in its reasonable set you had picked?
          </p>
          <ul className="grid gap-2 @lg:grid-cols-2 @3xl:grid-cols-3">
            {(Object.keys(VERDICT_MEANING) as Verdict[]).map((v) => (
              <li key={v} className="rounded-lg border border-line p-2.5">
                <VerdictTag verdict={v} />
                <p className="mt-1 text-[13px] text-muted">{VERDICT_MEANING[v]}</p>
              </li>
            ))}
          </ul>
          <div className="space-y-1.5 text-[13px] text-muted">
            <p>
              <span className="font-medium text-fg">It checks before it runs.</span> With every
              choice as planned it must reproduce qPilot's own numbers for every gene; if one
              differs, it refuses rather than describe other numbers.
            </p>
            <p>
              <span className="font-medium text-fg">It changes nothing.</span> It writes its own
              folder beside the Analysis Record, with a checksum for every file and the decision
              chain it describes. Your results and Decision Cards stay as they are.
            </p>
          </div>
        </CardBody>
      </Card>

      <Card
        as="section"
        aria-labelledby="audit-run"
        className="order-first self-start xl:order-none"
      >
        <CardHeader id="audit-run" title={running ? "The audit is running" : "Run the audit"} />
        <CardBody className="space-y-4">
          {status.checking && !scope ? (
            <p className="flex items-center gap-2 text-[13px] text-muted" role="status">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              Checking that the audit applies to this study…
            </p>
          ) : null}
          {scope?.analyses_in_full_grid ? (
            <dl className="grid grid-cols-2 gap-3">
              <Stat label="analyses" value={count(scope.analyses_in_full_grid)} />
              <Stat label="genes compared" value={count(scope.n_genes_compared)} />
              <Stat label="samples" value={count(scope.n_samples)} />
              <Stat label="sets of reference genes" value={count(scope.reference_sets)} />
            </dl>
          ) : (
            // The scale of this study is known once the audit has prepared it; until then, the
            // demo's (docs/app.md §4), with the server's measured time.
            <p className="text-[13px] text-muted">
              Every combination of the decisions' options is one analysis: on the demo study that is
              90 396 analyses
              {status.typical_s ? `, about ${duration(status.typical_s)} on a laptop` : ""}.
            </p>
          )}
          <ReplicatesNote replicates={scope?.technical_replicates} className="p-3" />
          {scope?.groups?.length === 2 ? (
            <p className="text-[13px] text-muted">
              Comparing <span className="font-medium text-fg">{scope.groups[0]}</span> with{" "}
              <span className="font-medium text-fg">{scope.groups[1]}</span>
              {workspace.is_demo ? " (the demo's design)" : ""}.
            </p>
          ) : null}
          {jobId ? (
            <JobCard id={jobId}>
              {() => <p className="text-[13px] text-muted">Opening the verdicts…</p>}
            </JobCard>
          ) : (
            <Button
              variant="primary"
              icon={<Play />}
              loading={run.isPending}
              onClick={() => run.mutate(false)}
              className="w-full"
            >
              Run the audit
            </Button>
          )}
          {status.status === "failed" && status.reason && !jobId ? (
            <p className="rounded-lg border border-danger/30 bg-danger-soft/50 px-3 py-2 text-[13px] text-fg">
              The last audit stopped: {status.reason}
            </p>
          ) : null}
          {run.isError ? (
            <ErrorPanel compact error={run.error} title="The audit did not start" />
          ) : null}
          {job.data?.status === "failed" && !run.isPending ? (
            <Button
              variant="secondary"
              icon={<Play />}
              onClick={() => run.mutate(false)}
              className="w-full"
            >
              Try again
            </Button>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-sunken px-3 py-2">
      <dd className="font-mono text-lg font-semibold text-fg tabular">{value}</dd>
      <dt className="text-xs text-muted">{label}</dt>
    </div>
  );
}

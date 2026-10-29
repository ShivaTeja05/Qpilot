/**
 * Check the curves: a job (about 15 s on the demo) that proposes the amplification rule and, per
 * target where it could change a conclusion, each well where the Curve Judge disagrees with
 * LinRegPCR. The job survives navigation (the workspace lists it while it runs).
 */
import { ScanLine } from "lucide-react";
import { useRef, useState } from "react";
import { api, unwrap, type JobView, type Schemas } from "@/api/client";
import { plural } from "@/lib/format";
import { useFocusTarget } from "@/shell/actions";
import { useWrite } from "@/shell/writes";
import type { SectionProps } from "@/shell/sections";
import { Button, Card, CardBody, JobCard } from "@/ui";

type Workspace = NonNullable<SectionProps["workspace"]>;

type Report = Schemas["ProposeReport"];

export interface CheckCurvesState {
  start: () => void;
  /** Starting, or a check of this session is running. */
  busy: boolean;
  /** The job to show (the one started here, else the one the workspace says is running). */
  jobId: string | null;
  dismiss: () => void;
}

/** The check's state, shared by the panel, the button in the stage bar and the job card. */
export function useCheckCurves(workspace: Workspace): CheckCurvesState {
  const sid = workspace.key;
  const running = workspace.active_jobs.find(
    (j: JobView) =>
      j.kind === "propose.curves" && (j.status === "queued" || j.status === "running"),
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const check = useWrite({
    workspaceKey: sid,
    mutationFn: () =>
      unwrap(api.POST("/api/sessions/{sid}/propose/curves", { params: { path: { sid } } })),
    onSuccess: (r) => setJobId(r.job.id),
  });
  return {
    start: () => check.mutate(),
    busy: check.isPending || Boolean(running),
    jobId: jobId ?? running?.id ?? null,
    dismiss: () => setJobId(null),
  };
}

/** The button; also the next step's focus target ("Check the curves"). */
export function CheckCurvesButton({
  state,
  again,
  primary,
}: {
  state: CheckCurvesState;
  again?: boolean;
  primary?: boolean;
}) {
  const button = useRef<HTMLButtonElement>(null);
  useFocusTarget("Check the curves", button);
  return (
    <Button
      ref={button}
      variant={primary ? "primary" : "secondary"}
      icon={<ScanLine />}
      loading={state.busy}
      disabled={state.busy}
      onClick={state.start}
      data-action="Check the curves"
    >
      {again ? "Check the curves again" : "Check the curves"}
    </Button>
  );
}

/** The job's progress, then what it found. */
export function CheckCurvesJob({
  state,
  className,
}: {
  state: CheckCurvesState;
  className?: string;
}) {
  if (!state.jobId) return null;
  return (
    <JobCard id={state.jobId} onDismiss={state.dismiss} className={className}>
      {(result) => (result ? <ReportText report={result as Report} /> : null)}
    </JobCard>
  );
}

/** Before any proposal: what the check does, and the button. */
export function CheckCurvesPanel({
  state,
  cqOnly = false,
}: {
  state: CheckCurvesState;
  /** A file of Cq values only: nothing to fit or judge (docs/cq-tables.md). */
  cqOnly?: boolean;
}) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-3 pt-4">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="max-w-2xl text-[13px] text-muted">
            <p className="text-sm font-medium text-fg">Check the curves</p>
            {cqOnly ? (
              <p className="mt-1">
                This file has Cq values only, so there is no curve for LinRegPCR to fit or for the
                Curve Judge to read. The check proposes the amplification rule (a well counts when
                the file gives it a Cq; the Cq cut-offs stay choices whose consequences are shown
                later), and the Cq table below is what you confirm: each sample’s Cq per well, the
                wells without a Cq and the replicates whose spread is wider than expected.
              </p>
            ) : (
              <p className="mt-1">
                qPilot fits every curve with LinRegPCR and asks the Curve Judge, a local curve
                classifier that reads only the curve’s shape, for its own call on each study well.
                Where the two disagree in a way that could change a conclusion, each well is listed
                here for you to decide; the others change nothing and are not listed. The
                amplification rule is proposed too.
              </p>
            )}
          </div>
          <CheckCurvesButton state={state} primary />
        </div>
        <CheckCurvesJob state={state} />
      </CardBody>
    </Card>
  );
}

/**
 * What the check found, said once: the server's message already holds the notes and the Curve
 * Judge's sentence (counts included), so only a report without one is pieced together here.
 */
function ReportText({ report }: { report: Report }) {
  if (report.message) return <p className="text-[13px] text-fg">{report.message}</p>;
  return (
    <div className="flex flex-col gap-1 text-[13px]">
      {report.disagreements != null ? (
        <p className="text-muted">
          The Curve Judge disagrees with LinRegPCR on {plural(report.disagreements, "study well")}
          {report.targets_that_matter != null
            ? `; on ${plural(report.targets_that_matter, "target")} resolving them could change a conclusion`
            : ""}
          .
        </p>
      ) : null}
      {report.notes?.length ? (
        <ul className="list-disc pl-5 text-muted">
          {report.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Check the curves: a job (about 15 s on the demo) that proposes the amplification rule and, per
 * target where it could change a conclusion, each well where the Curve Judge disagrees with
 * LinRegPCR. The job survives navigation (the workspace lists it while it runs).
 */
import { ScanLine } from "lucide-react";
import { useRef, useState } from "react";
import { api, unwrap } from "@/api/client";
import { count } from "@/lib/format";
import { useFocusTarget } from "@/shell/actions";
import { useWrite } from "@/shell/writes";
import type { SectionProps } from "@/shell/sections";
import { Button, Card, CardBody, JobCard } from "@/ui";

interface Report {
  message?: string;
  notes?: string[];
  disagreements?: number | null;
  targets_that_matter?: number | null;
  proposed?: string[];
}

export function CheckCurves({ workspace }: { workspace: NonNullable<SectionProps["workspace"]> }) {
  const sid = workspace.key;
  const stage = workspace.stages.find((s) => s.stage === "curves");
  const running = workspace.active_jobs.find(
    (j) => j.kind === "propose.curves" && (j.status === "queued" || j.status === "running"),
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const id = jobId ?? running?.id ?? null;
  const button = useRef<HTMLButtonElement>(null);
  useFocusTarget("Check the curves", button);

  const check = useWrite({
    workspaceKey: sid,
    mutationFn: () =>
      unwrap(api.POST("/api/sessions/{sid}/propose/curves", { params: { path: { sid } } })),
    onSuccess: (r) => setJobId(r.job.id),
  });

  if (stage?.confirmed && !id) return null;
  const busy = check.isPending || Boolean(running);

  return (
    <Card>
      <CardBody className="flex flex-col gap-3 pt-4">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="max-w-2xl text-[13px] text-muted">
            <p className="text-sm font-medium text-fg">Check the curves</p>
            <p className="mt-1">
              qPilot fits every curve with LinRegPCR and asks the Curve Judge, a local curve
              classifier that reads only the curve’s shape, for its own call on each study well.
              Where the two disagree in a way that could change a conclusion, each well is listed
              below for you to decide; the others change nothing and are not listed. Usually about
              15 s.
            </p>
          </div>
          {!stage?.confirmed ? (
            <Button
              ref={button}
              variant={stage && stage.pending > 0 ? "secondary" : "primary"}
              icon={<ScanLine />}
              loading={busy}
              disabled={busy}
              onClick={() => check.mutate()}
              data-action="Check the curves"
            >
              {stage && stage.pending > 0 ? "Check the curves again" : "Check the curves"}
            </Button>
          ) : null}
        </div>
        {id ? (
          <JobCard id={id} onDismiss={() => setJobId(null)}>
            {(result) => <ReportText report={(result ?? {}) as Report} />}
          </JobCard>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ReportText({ report }: { report: Report }) {
  return (
    <div className="flex flex-col gap-1 text-[13px]">
      {report.message ? <p className="text-fg">{report.message}</p> : null}
      {report.disagreements != null ? (
        <p className="text-muted">
          The Curve Judge disagrees with LinRegPCR on {count(report.disagreements)} study well
          {report.disagreements === 1 ? "" : "s"}
          {report.targets_that_matter != null
            ? `; on ${count(report.targets_that_matter)} target${report.targets_that_matter === 1 ? "" : "s"} resolving them could change a conclusion`
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

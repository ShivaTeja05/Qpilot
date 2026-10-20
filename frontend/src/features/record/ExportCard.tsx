/** Export the Analysis Record: a job, then the record's id, chain head, files and a download. */
import { AlertTriangle, Download, PackageCheck } from "lucide-react";
import { count } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, ErrorPanel, Hash, JobCard, KeyValues, Tooltip } from "@/ui";
import { downloadUrl, useExportRecord } from "./api";
import type { RecordExport } from "./types";

/** The export job's result, if it has the shape of one. */
export function asRecordExport(result: unknown): RecordExport | null {
  const r = result as Partial<RecordExport> | null | undefined;
  return r && typeof r.record_id === "string" && typeof r.download === "string" ? (r as RecordExport) : null;
}

export function ExportCard({
  studyId,
  head,
  jobId,
  onJob,
  disabledReason,
}: {
  studyId: string | null | undefined;
  /** The chain head the timeline shows (sent as `expected_head`). */
  head: string | null | undefined;
  jobId: string | null;
  onJob: (id: string | null) => void;
  /** Why exporting is not possible yet (no analysis), in words. */
  disabledReason?: string | null;
}) {
  const start = useExportRecord(studyId);
  const button = (
    <Button
      variant="primary"
      icon={<PackageCheck />}
      loading={start.isPending}
      disabled={Boolean(disabledReason) || !studyId}
      onClick={() =>
        start.mutate(head, {
          onSuccess: (answer) => onJob(answer.job.id),
        })
      }
    >
      {jobId ? "Export again" : "Export the Analysis Record"}
    </Button>
  );

  return (
    <Card as="section" aria-labelledby="export-title">
      <CardHeader
        id="export-title"
        title="Export the Analysis Record"
        hint="One zip with the input file, the design, every decision, the results and their checksums. Anyone with qPilot can check it and re-run it to the same numbers, byte for byte."
      />
      <CardBody className="flex flex-col gap-3">
        <div>
          {disabledReason ? (
            <Tooltip content={disabledReason}>
              <span tabIndex={0} className="inline-flex">
                {button}
              </span>
            </Tooltip>
          ) : (
            button
          )}
          {disabledReason ? <p className="mt-2 text-xs text-muted">{disabledReason}</p> : null}
        </div>
        {start.error ? <ErrorPanel compact error={start.error} /> : null}
        {jobId ? (
          <JobCard id={jobId} onDismiss={() => onJob(null)}>
            {(result) => <ExportResult result={asRecordExport(result)} head={head} />}
          </JobCard>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ExportResult({ result, head }: { result: RecordExport | null; head: string | null | undefined }) {
  if (!result) return <p className="text-[13px] text-muted">The record was written, but its details did not come back.</p>;
  const behind = head && result.chain_head !== head;
  return (
    <div className="flex flex-col gap-3">
      <KeyValues
        rows={[
          ["Record", <Hash key="r" value={result.record_id} length={12} />],
          [
            "Chain head",
            <span key="h" className="inline-flex flex-wrap items-center gap-1.5">
              <Hash value={result.chain_head} />
              {behind ? (
                <Badge tone="warn">not the head shown here</Badge>
              ) : head ? (
                <span className="text-xs text-muted">same as the timeline</span>
              ) : null}
            </span>,
          ],
          ["Files", <span key="f" className="font-mono">{count(result.n_files)}</span>],
          ["Input file", result.input_included ? "included" : "not included (re-running it needs the file)"],
        ]}
      />
      {result.warnings?.length ? (
        <ul className="flex flex-col gap-1.5">
          {result.warnings.map((w) => (
            <li key={w} className="flex gap-2 rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2 text-[13px] text-fg">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      <div>
        <Button asChild variant="secondary">
          <a href={downloadUrl(result.download)} download={result.file_name ?? true}>
            <Download aria-hidden />
            Download {result.file_name ?? "the record (.zip)"}
          </a>
        </Button>
      </div>
    </div>
  );
}

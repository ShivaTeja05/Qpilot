/**
 * Export the Analysis Record: a job, then the record's id, chain head, files and a download.
 * Records exported earlier since qPilot started stay listed (`GET …/records`).
 */
import { AlertTriangle, Download, PackageCheck } from "lucide-react";
import { useRef } from "react";
import { bytes, count, dateTime, relativeTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useFocusTarget } from "@/shell/actions";
import { Button, Card, CardBody, CardHeader, CopyButton, Hash, JobCard, KeyValues, Tooltip } from "@/ui";
import { useExportRecord } from "./api";
import type { RecordExport } from "./types";

/** The export job's result, if it has the shape of one. */
export function asRecordExport(result: unknown): RecordExport | null {
  const r = result as Partial<RecordExport> | null | undefined;
  return r && typeof r.record_id === "string" && typeof r.download?.url === "string" ? (r as RecordExport) : null;
}

function DownloadButton({ record, primary }: { record: RecordExport; primary?: boolean }) {
  return (
    <Button asChild variant={primary ? "secondary" : "ghost"} size={primary ? "md" : "sm"}>
      <a href={record.download.url} download={record.download.name}>
        <Download aria-hidden />
        {primary ? "Download the record" : "Download"}
        <span className="font-normal text-muted">{bytes(record.download.bytes)}</span>
      </a>
    </Button>
  );
}

export function ExportCard({
  workspaceKey,
  studyId,
  head,
  jobId,
  onJob,
  records,
  disabledReason,
}: {
  workspaceKey: string;
  studyId: string | null | undefined;
  /** The chain head the timeline shows (sent as `expected_head`). */
  head: string | null | undefined;
  jobId: string | null;
  onJob: (id: string | null) => void;
  /** Records exported since qPilot started, newest first (the latest is shown in full). */
  records: RecordExport[];
  /** Why exporting is not possible yet (no analysis), in words. */
  disabledReason?: string | null;
}) {
  const start = useExportRecord(workspaceKey, studyId, onJob);
  const ref = useRef<HTMLButtonElement>(null);
  useFocusTarget("Export the Analysis Record", ref);
  useFocusTarget("Export", ref);
  const now = useNow(60_000);
  const [latest, ...earlier] = records;

  const button = (
    <Button
      ref={ref}
      variant="primary"
      icon={<PackageCheck />}
      loading={start.isPending}
      disabled={Boolean(disabledReason) || !studyId}
      onClick={() => start.mutate(head)}
    >
      {latest ? "Export again" : "Export the Analysis Record"}
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
        {jobId ? <JobCard id={jobId} onDismiss={() => onJob(null)} /> : null}
        {latest ? <LatestRecord record={latest} head={head} now={now} /> : null}
        {earlier.length ? (
          <div>
            <h3 className="text-[13px] font-medium text-fg">Exported earlier since qPilot started</h3>
            <ul className="mt-1.5 flex flex-col divide-y divide-line rounded-lg border border-line">
              {earlier.map((r) => (
                <li key={r.record_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 text-[13px]">
                  <span className="flex min-w-0 items-center gap-2">
                    <Hash value={r.record_id} length={12} />
                    {r.written_at ? (
                      <time className="text-xs text-muted" dateTime={r.written_at} title={dateTime(r.written_at)}>
                        {relativeTime(r.written_at, now)}
                      </time>
                    ) : null}
                  </span>
                  <DownloadButton record={r} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function LatestRecord({ record, head, now }: { record: RecordExport; head: string | null | undefined; now: number }) {
  const current = !head || record.chain_head === head;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-sunken/50 p-3">
      <p className="text-[13px] font-medium text-fg">
        Latest record
        {record.written_at ? (
          <time className="ml-1.5 font-normal text-muted" dateTime={record.written_at} title={dateTime(record.written_at)}>
            {relativeTime(record.written_at, now)}
          </time>
        ) : null}
      </p>
      <KeyValues
        rows={[
          ["Record", <Hash key="r" value={record.record_id} length={12} />],
          ["File", <span key="n" className="font-mono text-[12px] [overflow-wrap:anywhere]">{record.download.name}</span>],
          [
            "Chain head",
            <span key="h" className="inline-flex flex-wrap items-center gap-1.5">
              <Hash value={record.chain_head} />
              {current ? <span className="text-xs text-muted">same as the timeline</span> : null}
            </span>,
          ],
          ["Files", <span key="f" className="font-mono">{count(record.n_files)}</span>],
          ["Input file", record.input_included ? "included" : "not included (it can be verified, not re-run)"],
        ]}
      />
      {!current ? <Warning>Decisions were made after this record was exported; export again to include them.</Warning> : null}
      {record.warnings.map((w) => (
        <Warning key={w}>{w}</Warning>
      ))}
      <div>
        <DownloadButton record={record} primary />
      </div>
      {record.download.path ? (
        <div className="flex items-start gap-1 text-xs text-muted">
          <p className="min-w-0 pt-1">
            Also kept on this computer: <span className="break-all font-mono text-[11.5px] text-fg">{record.download.path}</span>
          </p>
          <CopyButton text={record.download.path} label="Copy the file's path" />
        </div>
      ) : null}
    </div>
  );
}

function Warning({ children }: { children: string }) {
  return (
    <p className="flex gap-2 rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2 text-[13px] text-fg">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
      {children}
    </p>
  );
}

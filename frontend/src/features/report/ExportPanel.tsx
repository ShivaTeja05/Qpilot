/**
 * Write the report as a file: Markdown, a printable page, or the study passport (one offline
 * HTML file bound to a fresh Analysis Record). Each is a job with its card; the files written
 * since qPilot started stay listed with their downloads.
 */
import { AlertTriangle, BookMarked, Download, FileCode2, FileText, Printer } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { useJob } from "@/api/jobs";
import { bytes, dateTime, relativeTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useFocusTarget } from "@/shell/actions";
import { Button, Card, CardBody, CardHeader, CommandLine, Hash, JobCard } from "@/ui";
import { asExported, useExportReport, useRefreshExports, type ReportExported, type ReportFormat } from "./api";

export const FORMATS: { format: ReportFormat; title: string; hint: string; icon: ReactNode }[] = [
  {
    format: "passport",
    title: "Study passport",
    hint: "One HTML file a reviewer opens offline with a double-click: summary, charts, every gene, decisions, the audit, Methods, MIQE and how to verify it. Writes a fresh Analysis Record beside it.",
    icon: <BookMarked />,
  },
  {
    format: "html",
    title: "Printable page",
    hint: "The reviewer's report, Methods, the MIQE checklist and the limitations, laid out to print or save as PDF.",
    icon: <Printer />,
  },
  {
    format: "md",
    title: "Markdown",
    hint: "The same report as text for a lab notebook, a repository or a manuscript draft.",
    icon: <FileCode2 />,
  },
];

export function ExportPanel({
  workspaceKey,
  studyId,
  head,
  jobs,
  onJob,
  exports,
}: {
  workspaceKey: string;
  studyId: string;
  head: string | null | undefined;
  /** The running or finished job of each format started from this page. */
  jobs: Partial<Record<ReportFormat, string>>;
  onJob: (format: ReportFormat, id: string | null) => void;
  exports: ReportExported[];
}) {
  const start = useExportReport(workspaceKey, studyId, (f, id) => onJob(f, id));
  const passportRef = useRef<HTMLButtonElement>(null);
  useFocusTarget("Write the study passport", passportRef);
  useFocusTarget("Export the report", passportRef);
  const now = useNow(60_000);
  return (
    <Card as="section" aria-labelledby="report-export-title">
      <CardHeader
        id="report-export-title"
        title="Write the report as a file"
        hint="Every file is written from the numbers on this page, nothing else; strings from your files are shown as text, never as markup."
      />
      <CardBody className="@container flex flex-col gap-4">
        <ul className="grid gap-3 @2xl:grid-cols-3">
          {FORMATS.map((f) => (
            <li key={f.format} className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3.5">
              <p className="flex items-center gap-2 text-[14px] font-semibold text-fg [&_svg]:size-4 [&_svg]:text-accent-strong">
                {f.icon}
                {f.title}
              </p>
              <p className="flex-1 text-[12.5px] leading-relaxed text-muted">{f.hint}</p>
              <Button
                ref={f.format === "passport" ? passportRef : undefined}
                variant={f.format === "passport" ? "primary" : "secondary"}
                size="sm"
                className="self-start"
                loading={start.isPending && start.variables?.format === f.format}
                onClick={() => start.mutate({ format: f.format, head })}
              >
                {f.format === "passport" ? "Write the passport" : `Write the ${f.title.toLowerCase()}`}
              </Button>
            </li>
          ))}
        </ul>
        {FORMATS.filter((f) => jobs[f.format]).map((f) => (
          <ExportJob
            key={f.format}
            id={jobs[f.format]!}
            onDismiss={() => onJob(f.format, null)}
            workspaceKey={workspaceKey}
            studyId={studyId}
          />
        ))}
        {exports.length ? (
          <div>
            <h3 className="text-[13px] font-medium text-fg">Written since qPilot started</h3>
            <ul className="mt-1.5 flex flex-col divide-y divide-line rounded-lg border border-line">
              {exports.map((e) => (
                <WrittenFile key={e.download.id} file={e} head={head} now={now} />
              ))}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ExportJob({
  id,
  onDismiss,
  workspaceKey,
  studyId,
}: {
  id: string;
  onDismiss: () => void;
  workspaceKey: string;
  studyId: string;
}) {
  const job = useJob(id);
  const refresh = useRefreshExports(workspaceKey, studyId);
  const done = job.data?.status === "done";
  useEffect(() => {
    if (done) refresh();
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps -- refresh once when it finishes
  return (
    <JobCard id={id} onDismiss={onDismiss}>
      {(result) => {
        const file = asExported(result);
        return file ? <DownloadLinks file={file} /> : null;
      }}
    </JobCard>
  );
}

function DownloadLinks({ file }: { file: ReportExported }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Button asChild size="sm" variant="secondary" className="max-w-full self-start">
        <a href={file.download.url} download={file.download.name}>
          <Download aria-hidden />
          <span className="min-w-0 truncate">{file.download.name}</span>
          <span className="font-normal text-faint">{bytes(file.download.bytes)}</span>
        </a>
      </Button>
      {file.record ? (
        <Button asChild size="sm" variant="ghost" className="max-w-full self-start">
          <a href={file.record.download.url} download={file.record.download.name}>
            <Download aria-hidden />
            The Analysis Record
            <span className="font-normal text-faint">{bytes(file.record.download.bytes)}</span>
          </a>
        </Button>
      ) : null}
      {file.warnings.map((w) => (
        <p key={w} className="flex gap-1.5 text-[12px] text-muted">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
          {w}
        </p>
      ))}
    </div>
  );
}

function WrittenFile({ file, head, now }: { file: ReportExported; head: string | null | undefined; now: number }) {
  const current = !head || file.chain_head === head;
  return (
    <li className="flex flex-col gap-2 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-[13px]">
          <FileText className="size-3.5 shrink-0 text-faint" aria-hidden />
          <span className="font-medium text-fg">{file.title}</span>
          <time className="text-xs text-muted" dateTime={file.written_at} title={dateTime(file.written_at)}>
            {relativeTime(file.written_at, now)}
          </time>
          {!current ? <span className="text-xs text-warn">decisions were made since</span> : null}
        </span>
        <span className="flex flex-wrap gap-1">
          <Button asChild size="sm" variant="ghost">
            <a href={file.download.url} download={file.download.name}>
              <Download aria-hidden />
              Download
              <span className="font-normal text-faint">{bytes(file.download.bytes)}</span>
            </a>
          </Button>
          {file.record ? (
            <Button asChild size="sm" variant="ghost">
              <a href={file.record.download.url} download={file.record.download.name}>
                <Download aria-hidden />
                Record
              </a>
            </Button>
          ) : null}
        </span>
      </div>
      {file.record ? (
        <div className="flex flex-col gap-1 pl-5.5 text-[12px] text-muted">
          <span>
            Bound to the Analysis Record <Hash value={file.record.record_id} length={12} />
          </span>
          <CommandLine command={file.record.verify} />
        </div>
      ) : null}
    </li>
  );
}

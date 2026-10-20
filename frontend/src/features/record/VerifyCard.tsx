/**
 * Verify a record: drop (or pick) a record zip; the server unzips it in a private folder and
 * checks every file's checksum, the decision chain, the proposal chain, the files that must
 * agree with the chain, and the audit's binding when the record carries an audit.
 */
import { CheckCircle2, FileArchive, MinusCircle, ShieldCheck, Upload, XCircle } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import type { JobView } from "@/api/client";
import { cn } from "@/lib/cn";
import { bytes, count, plural } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, ErrorPanel, JobCard } from "@/ui";
import { useVerifyRecord } from "./api";
import type { VerifyResult } from "./types";

type CheckState = "pass" | "fail" | "absent";

interface CheckRow {
  title: string;
  state: CheckState;
  detail: ReactNode;
}

function isJob(answer: VerifyResult | { job: JobView }): answer is { job: JobView } {
  return "job" in answer && Boolean((answer as { job?: JobView }).job?.id);
}

function asVerifyResult(value: unknown): VerifyResult | null {
  const v = value as Partial<VerifyResult> | null | undefined;
  return v && typeof v.ok === "boolean" ? (v as VerifyResult) : null;
}

/** Up to `n` file names, then "and k more". */
function names(list: string[], n = 4): string {
  const shown = list.slice(0, n).join(", ");
  return list.length > n ? `${shown} and ${count(list.length - n)} more` : shown;
}

/** The verify report as one row per check, in plain words. */
export function verifyRows(r: VerifyResult): CheckRow[] {
  const fileProblems = r.changed.length + r.missing.length + r.unlisted.length;
  const rows: CheckRow[] = [
    {
      title: "Checksums",
      state: fileProblems ? "fail" : "pass",
      detail: fileProblems ? (
        <ul className="flex flex-col gap-0.5">
          {r.changed.length ? <li>Changed since export: {names(r.changed)}</li> : null}
          {r.missing.length ? <li>Missing: {names(r.missing)}</li> : null}
          {r.unlisted.length ? <li>Not in the checksum list: {names(r.unlisted)}</li> : null}
        </ul>
      ) : (
        "Every file matches the checksum written when the record was exported."
      ),
    },
    {
      title: "Decision chain",
      state: r.chain_broken_at != null ? "fail" : "pass",
      detail:
        r.chain_broken_at != null
          ? `Broken at entry ${r.chain_broken_at}: that line (or one before it) was changed after it was written.`
          : `${plural(r.n_entries, "entry", "entries")}, every hash links to the one before it.`,
    },
    {
      title: "Proposal chain",
      state: !r.has_proposals ? "absent" : r.proposal_chain_broken_at != null ? "fail" : "pass",
      detail: !r.has_proposals
        ? "Not in this record (the study was analysed outside a Studio session)."
        : r.proposal_chain_broken_at != null
          ? `Broken at entry ${r.proposal_chain_broken_at}.`
          : `${plural(r.n_proposal_entries, "entry", "entries")}, intact.`,
    },
    {
      title: "Files agree with the chain",
      state: r.inconsistent.length ? "fail" : "pass",
      detail: r.inconsistent.length ? (
        <ul className="flex flex-col gap-0.5">
          {r.inconsistent.map((item) => (
            <li key={item} className="break-words">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        "The decisions, the cards and the record's summary say the same thing."
      ),
    },
  ];
  if (r.audit) {
    const status = r.audit.status.toLowerCase();
    rows.push({
      title: "Audit binding",
      state: status === "bound" || status === "ok" ? "pass" : status.startsWith("no") || status === "absent" ? "absent" : "fail",
      detail: r.audit.message || r.audit.status,
    });
  }
  return rows;
}

const STATE_ICON: Record<CheckState, ReactNode> = {
  pass: <CheckCircle2 className="text-ok" aria-hidden />,
  fail: <XCircle className="text-danger" aria-hidden />,
  absent: <MinusCircle className="text-faint" aria-hidden />,
};
const STATE_WORD: Record<CheckState, string> = { pass: "passed", fail: "failed", absent: "not in this record" };

export function VerifyReportView({ report, fileName }: { report: VerifyResult; fileName?: string | null }) {
  const rows = verifyRows(report);
  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      <div
        className={cn(
          "flex items-start gap-3 rounded-lg border px-3 py-2.5",
          report.ok ? "border-ok/30 bg-ok-soft/60" : "border-danger/30 bg-danger-soft/60",
        )}
      >
        <div className="mt-0.5 [&_svg]:size-5">{report.ok ? STATE_ICON.pass : STATE_ICON.fail}</div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg">
            {report.ok ? "This record checks out" : "This record was changed after it was exported"}
          </p>
          <p className="mt-0.5 text-[13px] text-muted">
            {report.ok
              ? "Nothing in it was altered since qPilot wrote it."
              : "Do not rely on it; ask its author for the original zip."}
            {fileName ? (
              <>
                {" "}
                <span className="break-all font-mono text-[12px]">{fileName}</span>
                {report.bytes != null ? <span className="text-faint"> · {bytes(report.bytes)}</span> : null}
              </>
            ) : null}
          </p>
        </div>
      </div>
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line">
        {rows.map((row) => (
          <li key={row.title} className="flex items-start gap-2.5 px-3 py-2.5">
            <span className="mt-0.5 shrink-0 [&_svg]:size-4">{STATE_ICON[row.state]}</span>
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-x-2 text-[13px] font-medium text-fg">
                {row.title}
                <span className="sr-only">: {STATE_WORD[row.state]}</span>
              </p>
              <div className="mt-0.5 text-[13px] text-muted">{row.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VerifyCard() {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const verify = useVerifyRecord();

  const check = (picked: File | null | undefined) => {
    if (!picked) return;
    setFile(picked);
    setJobId(null);
    verify.mutate(picked, {
      onSuccess: (answer) => {
        if (isJob(answer)) setJobId(answer.job.id);
      },
    });
  };
  const onDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setOver(false);
    check(e.dataTransfer.files?.[0]);
  };
  const direct = verify.data && !isJob(verify.data) ? verify.data : null;

  return (
    <Card as="section" aria-labelledby="verify-title">
      <CardHeader
        id="verify-title"
        title="Verify a record"
        hint="Check a record zip someone sent you, or one you exported earlier. It is read on this computer only."
      />
      <CardBody className="flex flex-col gap-3">
        <label
          htmlFor={inputId}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition-colors duration-150",
            "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus",
            over ? "border-accent bg-accent-soft" : "border-line-strong hover:border-faint hover:bg-bg-subtle",
          )}
        >
          <span className="flex size-9 items-center justify-center rounded-full bg-bg-subtle text-muted [&_svg]:size-4" aria-hidden>
            {file ? <FileArchive /> : <Upload />}
          </span>
          <span className="text-sm font-medium text-fg">
            {file ? <span className="break-all">{file.name}</span> : "Drop a record .zip here"}
          </span>
          <span className="text-xs text-muted">
            {file ? `${bytes(file.size)} · drop another to check it` : "or choose a file"}
          </span>
          <input
            ref={input}
            id={inputId}
            type="file"
            accept=".zip,application/zip"
            className="sr-only"
            onChange={(e) => {
              check(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>

        {verify.isPending ? (
          <p className="flex items-center gap-2 text-[13px] text-muted" role="status">
            <ShieldCheck className="size-4 animate-pulse text-accent" aria-hidden /> Checking {file?.name}…
          </p>
        ) : null}
        {verify.error ? (
          <ErrorPanel compact error={verify.error} title="This file could not be checked">
            {file ? (
              <Button size="sm" variant="secondary" className="mt-3" onClick={() => check(file)}>
                Try again
              </Button>
            ) : null}
          </ErrorPanel>
        ) : null}
        {direct ? <VerifyReportView report={direct} fileName={direct.file_name ?? file?.name} /> : null}
        {jobId ? (
          <JobCard id={jobId}>
            {(result) => {
              const report = asVerifyResult(result);
              return report ? (
                <VerifyReportView report={report} fileName={report.file_name ?? file?.name} />
              ) : (
                <Badge tone="warn">The check finished but sent no report.</Badge>
              );
            }}
          </JobCard>
        ) : null}
      </CardBody>
    </Card>
  );
}

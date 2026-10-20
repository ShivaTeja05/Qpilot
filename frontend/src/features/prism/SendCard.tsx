/**
 * Step 3: Send to Prism. Writes the bundle for the accepted project (one CSV per gene, the Prism
 * scripts, the provenance, a README), zips it for download, and starts Prism when it is installed
 * on this computer. Says plainly when it is not, what to do instead, and that the bridge has not
 * yet been run in a real Prism.
 */
import { CheckCircle2, Download, Info, Send, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button, Card, CardBody, CardHeader, CommandLine, ErrorPanel, Hash, JobCard } from "@/ui";
import { dateTime, plural, relativeTime } from "@/lib/format";
import { activeJob, downloadUrl, usePrismBundles, useStartSend, type BundleEntry, type SendResult, type Workspace } from "./api";
import type { Flow } from "./flow";
import { NOT_AFFILIATED, NOT_RUN_YET } from "./words";

export function SendCard({ workspace, flow }: { workspace: Workspace; flow: Flow }) {
  const send = useStartSend(workspace.key);
  const bundles = usePrismBundles(workspace.key);
  const [jobId, setJobId] = useState<string | null>(null);
  const running = activeJob(workspace, "send");
  const shownJob = jobId ?? running?.id ?? null;
  const last = latestFor(bundles.data ?? [], workspace.study_id);

  return (
    <Card as="section" aria-labelledby="prism-send-title" id="prism-step-send" tabIndex={-1} className="scroll-mt-4 outline-none">
      <CardHeader
        id="prism-send-title"
        title="Send to Prism"
        hint="Writes the bundle: one table per gene, the Prism scripts, the provenance and a README, zipped for you to download."
      />
      <CardBody className="flex flex-col gap-4">
        <div className="flex items-start gap-2.5 rounded-lg border border-info/25 bg-info-soft p-3 text-[12.5px] leading-relaxed text-fg">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <div>
            <p>{NOT_AFFILIATED}</p>
            <p className="mt-1">{NOT_RUN_YET}</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            size="lg"
            icon={<Send />}
            loading={send.isPending}
            disabled={Boolean(flow.sendBlocked) || Boolean(running)}
            onClick={() =>
              send.mutate({ expected_head: workspace.proposals_head ?? null }, { onSuccess: ({ job }) => setJobId(job.id) })
            }
          >
            {flow.sent ? "Send again" : "Send to Prism"}
          </Button>
          {flow.sendBlocked ? <p className="text-[13px] text-muted">{flow.sendBlocked}</p> : null}
        </div>

        {send.error ? <ErrorPanel error={send.error} title="Not sent" compact /> : null}
        {shownJob ? (
          <JobCard id={shownJob} onDismiss={() => setJobId(null)}>
            {(result) => <SendOutcome result={(result ?? {}) as SendResult} />}
          </JobCard>
        ) : last ? (
          <LastBundle bundle={last} />
        ) : null}
      </CardBody>
    </Card>
  );
}

/** The newest bundle sent for the analysis shown now. */
export function latestFor(bundles: BundleEntry[], studyId: string | null | undefined): BundleEntry | null {
  const mine = bundles.filter((b) => (b.current ?? b.study_id === studyId) === true);
  return mine.at(-1) ?? null;
}

function LastBundle({ bundle }: { bundle: BundleEntry }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 p-3">
      <p className="text-[13px] text-fg">
        Sent for this analysis <span className="text-muted">{relativeTime(bundle.at)}</span>{" "}
        <span className="text-muted">({dateTime(bundle.at)})</span> · <Hash value={bundle.bundle_sha256} prefix="bundle" />
      </p>
      {bundle.download ? (
        <Button asChild variant="secondary" size="sm">
          <a href={downloadUrl(bundle.download)} download>
            <Download aria-hidden />
            Download the bundle
          </a>
        </Button>
      ) : null}
    </div>
  );
}

export function SendOutcome({ result }: { result: SendResult }) {
  const files = result.files ?? [];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-fg">
        Wrote {plural(files.length, "file")}
        {result.bundle_sha256 ? (
          <>
            {" "}
            · <Hash value={result.bundle_sha256} prefix="bundle sha256" />
          </>
        ) : null}
        .
      </p>
      {result.download ? (
        <div>
          <Button asChild variant="primary" size="sm">
            <a href={downloadUrl(result.download)} download={result.download_name ?? undefined}>
              <Download aria-hidden />
              Download the bundle (zip)
            </a>
          </Button>
        </div>
      ) : null}

      {result.launched ? (
        <p className="flex items-start gap-2 text-[13px] text-fg">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          <span>
            Prism was started with <span className="font-mono">run.pzc</span>.{" "}
            {result.done
              ? "It finished the script: the projects are saved next to the tables."
              : "It has not finished yet (many genes take a while); the projects appear next to the tables when it does."}
          </span>
        </p>
      ) : (
        <div className="flex flex-col gap-2 rounded-lg border border-warn/30 bg-warn-soft p-3 text-[13px] text-fg">
          <p className="flex items-start gap-2">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
            <span>
              {result.note || "Prism was not started."} Download the bundle, unzip it on the computer that has Prism and
              open <span className="font-mono">run.pzc</span> there (double-click it on a Mac), or run:
            </span>
          </p>
          {result.command_line ? <CommandLine command={result.command_line} /> : null}
        </div>
      )}

      {result.notes?.length ? (
        <ul className="list-disc pl-5 text-[12.5px] text-muted">
          {result.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-[12.5px] text-muted">
        After editing in Prism, save the projects and run <span className="font-mono">send_back.pzc</span> from the bundle
        folder; then use Round trip below.
      </p>
    </div>
  );
}

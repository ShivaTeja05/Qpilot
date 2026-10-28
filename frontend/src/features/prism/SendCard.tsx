/**
 * Step 3: Send to Prism. Writes the bundle for the accepted project — a Prism project file
 * (.pzfx) that opens in Prism as it is, the same tables as CSV, the provenance and a README —
 * zips it for download, and opens the project in Prism when Prism is installed on this computer.
 * Says plainly, for Windows and macOS, how to open it elsewhere (never a command line), which
 * clicks add the test and the graph, and that the file has not yet been opened in a real Prism by
 * the qPilot team.
 */
import { CheckCircle2, Download, Info, Send } from "lucide-react";
import { useState } from "react";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CommandLine,
  CopyButton,
  ErrorPanel,
  Hash,
  JobCard,
  SegmentedControl,
} from "@/ui";
import { bytes, dateTime, plural, relativeTime } from "@/lib/format";
import {
  activeJob,
  usePrismBundles,
  useStartSend,
  type PrismBundleView,
  type PrismSent,
  type Workspace,
} from "./api";
import type { Flow } from "./flow";
import { browserPlatform, NOT_AFFILIATED, NOT_RUN_YET, PROJECT_WORDS } from "./words";

export function SendCard({ workspace, flow }: { workspace: Workspace; flow: Flow }) {
  const send = useStartSend(workspace.key);
  const bundles = usePrismBundles(workspace.key);
  const [jobId, setJobId] = useState<string | null>(null);
  const running = activeJob(workspace, "prism.send");
  const shownJob = jobId ?? running?.id ?? null;
  const last = bundles.data?.find((b) => b.current) ?? null;

  return (
    <Card
      as="section"
      aria-labelledby="prism-send-title"
      id="prism-step-send"
      tabIndex={-1}
      className="scroll-mt-4 outline-none"
    >
      <CardHeader
        id="prism-send-title"
        title="Send to Prism"
        hint="Writes the Prism project (one table per gene, the table of all genes and an Info sheet with the provenance), the same tables as CSV and a README, zipped for you to download."
      />
      <CardBody className="flex flex-col gap-4">
        <div className="flex items-start gap-2.5 rounded-lg border border-info/25 bg-info-soft p-3 text-[12.5px] leading-relaxed text-fg">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <div>
            <p>{PROJECT_WORDS}</p>
            <p className="mt-1">{NOT_RUN_YET}</p>
            <p className="mt-1 text-muted">{NOT_AFFILIATED}</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            size="lg"
            icon={<Send />}
            loading={send.isPending}
            disabled={Boolean(flow.sendBlocked) || Boolean(running)}
            onClick={() => send.mutate(undefined, { onSuccess: ({ job }) => setJobId(job.id) })}
          >
            {flow.sent ? "Send again" : "Send to Prism"}
          </Button>
          {flow.sendBlocked ? <p className="text-[13px] text-muted">{flow.sendBlocked}</p> : null}
        </div>

        {send.error ? <ErrorPanel error={send.error} title="Not sent" compact /> : null}
        {shownJob ? (
          <JobCard id={shownJob} onDismiss={() => setJobId(null)}>
            {(result) => (result ? <SendOutcome result={result as PrismSent} /> : null)}
          </JobCard>
        ) : last ? (
          <LastBundle bundle={last} />
        ) : null}
      </CardBody>
    </Card>
  );
}

/** Where the bundle is on this computer (the folder holds every file of the zip). */
function BundleFolder({ folder }: { folder: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-[12.5px]">
      <span className="shrink-0 text-muted">In the folder</span>
      <code className="min-w-0 truncate font-mono text-fg" title={folder}>
        {folder}
      </code>
      <CopyButton text={folder} label="Copy the folder path" />
    </div>
  );
}

function LastBundle({ bundle }: { bundle: PrismBundleView }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-fg">
          Sent for this analysis <span className="text-muted">{relativeTime(bundle.at)}</span>{" "}
          <span className="text-muted">({dateTime(bundle.at)})</span> ·{" "}
          <Hash value={bundle.bundle_sha256} prefix="bundle" />
        </p>
        {bundle.download ? (
          <Button asChild variant="secondary" size="sm">
            <a href={bundle.download.url} download={bundle.download.name}>
              <Download aria-hidden />
              Download the bundle
            </a>
          </Button>
        ) : null}
      </div>
      {bundle.project ? (
        <p className="text-[12.5px] text-muted">
          The project <span className="font-mono text-fg">{fileName(bundle.project)}</span> is in
          it: double-click it on the computer with Prism.
        </p>
      ) : null}
      {bundle.exists ? (
        <BundleFolder folder={bundle.folder} />
      ) : (
        <p className="text-[12.5px] text-warn">Its folder is no longer on this computer.</p>
      )}
    </div>
  );
}

export function SendOutcome({ result }: { result: PrismSent }) {
  const project = result.project ?? null;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-fg">
        Wrote {plural(result.n_files, "file")} ·{" "}
        <Hash value={result.bundle.bundle_sha256} prefix="bundle sha256" />.
      </p>
      <BundleFolder folder={result.bundle.folder} />
      <div>
        <Button asChild variant="primary" size="sm">
          <a href={result.download.url} download={result.download.name}>
            <Download aria-hidden />
            Download the bundle ({bytes(result.download.bytes)} zip)
          </a>
        </Button>
      </div>

      {project ? (
        <ProjectSteps result={result} project={project} />
      ) : (
        <ScriptsOnly result={result} />
      )}

      {result.notes.length ? (
        <ul className="list-disc pl-5 text-[12.5px] text-muted">
          {result.notes.map((n, i) => (
            <li key={i}>{sentence(n)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** How to open the project, add the test and graph, and come back — in plain words. */
function ProjectSteps({ result, project }: { result: PrismSent; project: string }) {
  const here = browserPlatform() ?? result.this_platform;
  const systems = [...result.open_steps].sort(
    (a, b) => Number(b.platform === here) - Number(a.platform === here),
  );
  const [platform, setPlatform] = useState(systems[0]?.platform ?? here);
  const steps = systems.find((s) => s.platform === platform) ?? systems[0];
  return (
    <div className="flex flex-col gap-3">
      {result.launched ? (
        <p className="flex items-start gap-2 text-[13px] text-fg">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          <span>
            Prism was asked to open <span className="font-mono">{project}</span> on this computer.
          </span>
        </p>
      ) : (
        <p className="text-[13px] text-fg">
          {sentence(result.launch_note) || "Prism was not opened from here."}
        </p>
      )}
      <section
        aria-labelledby="prism-open-title"
        className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="prism-open-title" className="text-[13px] font-semibold text-fg">
            Open <span className="font-mono">{project}</span> in Prism
          </h3>
          {systems.length > 1 ? (
            <SegmentedControl
              label="Computer with Prism"
              value={platform}
              onValueChange={(v) => setPlatform(v as typeof platform)}
              options={systems.map((s) => ({ value: s.platform, label: s.label }))}
            />
          ) : null}
        </div>
        {steps ? <Steps steps={steps.steps} label={`On ${steps.label}`} /> : null}
      </section>
      <section aria-labelledby="prism-analyse-title" className="flex flex-col gap-1.5">
        <h3 id="prism-analyse-title" className="text-[13px] font-semibold text-fg">
          Add the test and the graph in Prism
        </h3>
        <Steps steps={result.analyse_steps} label="Add the test and the graph" />
      </section>
      <section aria-labelledby="prism-back-title" className="flex flex-col gap-1.5">
        <h3 id="prism-back-title" className="text-[13px] font-semibold text-fg">
          Bring your changes back
        </h3>
        <Steps steps={result.round_trip_steps} label="Bring your changes back" />
      </section>
      {result.scripts && result.command_line ? (
        <details className="text-[12.5px]">
          <summary className="cursor-pointer text-muted hover:text-fg">
            Optional: the Prism scripts for a hand-made template
          </summary>
          <p className="mt-1 text-muted">
            The bundle also holds <span className="font-mono">run.pzc</span> and{" "}
            <span className="font-mono">send_back.pzc</span>. You do not need them to use the
            project.
          </p>
        </details>
      ) : null}
    </div>
  );
}

function Steps({ steps, label }: { steps: string[]; label: string }) {
  return (
    <ol aria-label={label} className="list-decimal pl-5 text-[12.5px] leading-relaxed text-fg">
      {steps.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ol>
  );
}

/** A bundle written the older way (CSV tables and Prism scripts for a template). */
function ScriptsOnly({ result }: { result: PrismSent }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3 text-[13px] text-fg">
      <p>
        {result.launched
          ? result.done
            ? "Prism ran run.pzc: the projects are saved next to the tables."
            : "Prism was started with run.pzc; the projects appear next to the tables when it finishes."
          : sentence(result.launch_note) || "Prism was not started."}
      </p>
      <p className="text-[12.5px] text-muted">
        This bundle has no project file: it needs a Prism template made by hand. Unzip it on the
        computer with Prism and open <span className="font-mono">run.pzc</span> there.
      </p>
      {result.command_line ? (
        <details className="text-[12.5px]">
          <summary className="cursor-pointer text-muted hover:text-fg">
            The command for a terminal
          </summary>
          <CommandLine command={result.command_line} />
        </details>
      ) : null}
    </div>
  );
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** A note from the service as a sentence (capital first letter, full stop). */
function sentence(text: string | null | undefined): string {
  const t = (text ?? "").trim();
  if (!t) return "";
  const s = t[0]!.toUpperCase() + t.slice(1);
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

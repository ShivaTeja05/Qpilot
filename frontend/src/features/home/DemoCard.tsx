/**
 * The demo study: continue it when a session of it exists; open it when it is downloaded; else
 * offer the download first, saying how big it is and where it comes from (the only request the
 * Open screen makes to the internet, and only on that click).
 */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Download, Globe } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { api, unwrap, type Schemas } from "@/api/client";
import { Button, ErrorPanel, Hash, JobCard, Skeleton } from "@/ui";
import { bytes } from "@/lib/format";
import { sectionPath } from "@/shell/sections";
import { openedKey, useGoToSession, useJobOutcome } from "./useOpenWorkspace";
import { countsLine, workspaceSection, type WorkspaceSummary } from "./workspace";

type DemoInfo = Schemas["DemoInfo"];

type Phase =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "fetching"; jobId: string }
  | { kind: "opening"; jobId: string }
  | { kind: "failed"; error: unknown };

/** The host of the pinned source, for the sentence under the button. */
function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** `fce7a44`: the commit the source URL pins (a 40-hex path segment), if it has one. */
function pinnedCommit(url: string): string | null {
  const m = /\/([0-9a-f]{40})\//.exec(url);
  return m?.[1] ?? null;
}

export function DemoCard({
  demo,
  workspace,
  loading,
}: {
  demo: DemoInfo | undefined;
  /** The demo's existing Studio session, when there is one with its file present. */
  workspace: WorkspaceSummary | undefined;
  loading: boolean;
}) {
  const qc = useQueryClient();
  const goTo = useGoToSession();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  const startOpen = async () => {
    setPhase({ kind: "starting" });
    try {
      const { job } = await unwrap(api.POST("/api/workspaces/demo"));
      qc.setQueryData(["job", job.id], job);
      setPhase({ kind: "opening", jobId: job.id });
    } catch (error) {
      setPhase({ kind: "failed", error });
    }
  };

  const startFetch = async () => {
    setPhase({ kind: "starting" });
    try {
      const { job } = await unwrap(api.POST("/api/demo/fetch"));
      qc.setQueryData(["job", job.id], job);
      setPhase({ kind: "fetching", jobId: job.id });
    } catch (error) {
      setPhase({ kind: "failed", error });
    }
  };

  useJobOutcome(phase.kind === "fetching" ? phase.jobId : null, () => {
    void qc.invalidateQueries({ queryKey: ["system"] });
    void startOpen();
  });
  useJobOutcome(phase.kind === "opening" ? phase.jobId : null, (job) => {
    const key = openedKey(job.result);
    if (key) void goTo(key).catch((error: unknown) => setPhase({ kind: "failed", error }));
  });

  const jobId = phase.kind === "fetching" || phase.kind === "opening" ? phase.jobId : null;
  const commit = demo ? pinnedCommit(demo.source) : null;

  return (
    <section
      aria-labelledby="demo-title"
      className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-surface"
    >
      <div className="flex flex-1 flex-col gap-4 p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <span
            className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line bg-surface-2 text-muted [&_svg]:size-5"
            aria-hidden
          >
            <BookOpen />
          </span>
          <div className="min-w-0">
            <h2 id="demo-title" className="text-lg font-semibold tracking-tight text-fg">
              {workspace ? "Continue the demo study" : "Open the demo study"}
            </h2>
            <p className="mt-0.5 text-[13px] text-muted">
              A public neuroblastoma qPCR study, to see every step on real data before you open your
              own.
            </p>
          </div>
        </div>

        {loading || !demo ? (
          <div className="flex flex-col gap-2" role="status">
            <span className="sr-only">Loading…</span>
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        ) : (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
            <dt className="text-muted">Study</dt>
            <dd className="text-fg">{demo.citation}</dd>
            {workspace ? (
              <>
                <dt className="text-muted">In the file</dt>
                <dd className="text-fg tabular">{countsLine(workspace)}</dd>
              </>
            ) : null}
            <dt className="text-muted">Licence</dt>
            <dd className="text-fg">{demo.licence}</dd>
            <dt className="text-muted">SHA-256</dt>
            <dd>
              <Hash value={demo.sha256} length={12} className="-ml-1" />
            </dd>
          </dl>
        )}

        <div className="mt-auto flex flex-col gap-3">
          {jobId ? <JobCard id={jobId} /> : null}
          {phase.kind === "failed" ? (
            <ErrorPanel compact error={phase.error} title="The demo could not be opened" />
          ) : null}

          {workspace ? (
            <>
              <Button variant="secondary" size="lg" asChild className="self-start">
                <Link
                  href={sectionPath(
                    { key: workspace.key, kind: workspace.kind },
                    workspaceSection(workspace),
                  )}
                >
                  Continue the demo
                  <ArrowRight />
                </Link>
              </Button>
              <p className="text-xs text-muted">
                Your work on it is kept. To start again from a clean study, use Start a fresh demo
                in{" "}
                <Link href="/settings" className="text-accent underline underline-offset-2">
                  Settings
                </Link>
                .
              </p>
            </>
          ) : demo?.cached ? (
            phase.kind !== "opening" ? (
              <Button
                variant="secondary"
                size="lg"
                icon={<ArrowRight />}
                loading={phase.kind === "starting"}
                onClick={() => void startOpen()}
                className="self-start"
              >
                Open the demo study
              </Button>
            ) : null
          ) : demo ? (
            phase.kind !== "fetching" && phase.kind !== "opening" ? (
              <>
                <Button
                  variant="secondary"
                  size="lg"
                  icon={<Download />}
                  loading={phase.kind === "starting"}
                  onClick={() => void startFetch()}
                  className="self-start"
                >
                  Download {bytes(demo.bytes)} and open
                </Button>
                <p className="flex items-start gap-1.5 text-xs text-muted">
                  <Globe className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>
                    From the RDML consortium&rsquo;s repository on {host(demo.source)}
                    {commit ? (
                      <>
                        {" "}
                        at commit <span className="font-mono">{commit.slice(0, 7)}</span>
                      </>
                    ) : null}
                    , checked against its SHA-256 before it is used. This is the only thing this
                    screen downloads, and only when you click.
                  </span>
                </p>
              </>
            ) : null
          ) : null}
        </div>
      </div>
    </section>
  );
}

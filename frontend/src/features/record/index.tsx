/**
 * Record (docs/app.md §4): the decision chain as a timeline, exporting the Analysis Record,
 * verifying a record zip, and the commands that check and re-run one anywhere.
 */
import { ArrowRight, BookCheck, Bot } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { useJob } from "@/api/jobs";
import { plural } from "@/lib/format";
import { SECTION, sectionPath, type SectionProps } from "@/shell/sections";
import { Button, Card, CardBody, EmptyState, ErrorPanel, LoadingBlock, PageHeader } from "@/ui";
import { useDecisions } from "./api";
import { ChainTimeline } from "./ChainTimeline";
import { CommandsCard } from "./CommandsCard";
import { asRecordExport, ExportCard } from "./ExportCard";
import { VerifyCard } from "./VerifyCard";

/** The export job of this study, kept for the tab's life so it survives leaving the section. */
function useExportJob(studyId: string | null | undefined, active: string | null) {
  const storageKey = studyId ? `qpilot.record.job.${studyId}` : null;
  const [jobId, setJobId] = useState<string | null>(() => {
    if (!storageKey) return null;
    try {
      return sessionStorage.getItem(storageKey);
    } catch {
      return null;
    }
  });
  const set = (id: string | null) => {
    setJobId(id);
    if (!storageKey) return;
    try {
      if (id) sessionStorage.setItem(storageKey, id);
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* storage blocked: the job is still shown until the page is left */
    }
  };
  // An export still running (started in another tab, say) wins over the one remembered here.
  return [active ?? jobId, set] as const;
}

export default function RecordSection({ workspace }: SectionProps) {
  const key = workspace?.key ?? "";
  const studyId = workspace?.study_id ?? null;
  const decisions = useDecisions(key, studyId);
  const activeExport = workspace?.active_jobs.find((j) => j.kind.includes("record") && j.kind !== "record_verify") ?? null;
  const [jobId, setJobId] = useExportJob(studyId, activeExport?.id ?? null);
  const job = useJob(jobId);
  const exported = job.data?.status === "done" ? asRecordExport(job.data.result) : null;

  const head = decisions.data?.head ?? workspace?.decisions_head ?? null;
  const notYet = !studyId
    ? workspace?.kind === "session"
      ? "The record starts when this study is analysed: confirm the design and the curves first."
      : "This study has not been analysed yet."
    : null;
  const pending = decisions.data?.entries.filter((e) => e.status === "pending_human").length ?? 0;
  const next = workspace?.next_step;

  return (
    <div className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Analysis Record"
        title="Record"
        hint="Every decision on this study, hash-chained, and a record anyone can check and re-run."
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0">
          {notYet ? (
            <EmptyState
              icon={<BookCheck />}
              title="Nothing recorded yet"
              action={
                next && next.section !== "record" && next.section in SECTION ? (
                  <Button asChild variant="primary">
                    <Link href={sectionPath(workspace, next.section as keyof typeof SECTION)}>
                      {next.title}
                      <ArrowRight aria-hidden />
                    </Link>
                  </Button>
                ) : null
              }
            >
              {notYet} Every decision made after that is added here, each linked to the one before it.
            </EmptyState>
          ) : decisions.isPending ? (
            <Card>
              <CardBody className="pt-4">
                <LoadingBlock label="Reading the decision chain" lines={6} />
              </CardBody>
            </Card>
          ) : decisions.error ? (
            <ErrorPanel error={decisions.error} title="The decision chain could not be read" onRetry={() => void decisions.refetch()} />
          ) : decisions.data.entries.length === 0 ? (
            <EmptyState
              icon={<BookCheck />}
              title="No decisions yet"
              action={
                <Button asChild variant="primary">
                  <Link href={sectionPath(workspace, "results")}>
                    Go to the Decision Cards
                    <ArrowRight aria-hidden />
                  </Link>
                </Button>
              }
            >
              The chain starts at the input file. Each choice you make on a Decision Card, and each one qPilot or an agent makes, is added here.
            </EmptyState>
          ) : (
            <ChainTimeline
              entries={decisions.data.entries}
              root={decisions.data.root}
              head={decisions.data.head}
              intact={decisions.data.chain_intact}
              actions={
                pending ? (
                  <Button asChild size="sm" variant="secondary">
                    <Link href={sectionPath(workspace, "agents")}>
                      <Bot aria-hidden className="text-warn" />
                      {plural(pending, "agent request")} waiting for you
                      <ArrowRight aria-hidden />
                    </Link>
                  </Button>
                ) : null
              }
            />
          )}
        </div>

        <aside className="flex min-w-0 flex-col gap-6" aria-label="Export and verify">
          <ExportCard studyId={studyId} head={head} jobId={jobId} onJob={setJobId} disabledReason={notYet} />
          <VerifyCard />
          <CommandsCard fileName={exported?.file_name} />
        </aside>
      </div>
    </div>
  );
}

/**
 * Record (docs/app.md §4): the decision chain as a timeline, exporting the Analysis Record,
 * verifying a record zip, and the commands that check and re-run one anywhere.
 */
import { ArrowRight, BookCheck, Bot } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { Link } from "wouter";
import { plural } from "@/lib/format";
import { SECTION, sectionPath, type SectionProps } from "@/shell/sections";
import { Button, Card, CardBody, EmptyState, ErrorPanel, LoadingBlock, PageHeader } from "@/ui";
import { useDecisions, useRecords } from "./api";
import { ChainTimeline } from "./ChainTimeline";
import { CommandsCard } from "./CommandsCard";
import { ExportCard } from "./ExportCard";
import { VerifyCard } from "./VerifyCard";

export default function RecordSection({ workspace }: SectionProps) {
  const key = workspace?.key ?? "";
  const studyId = workspace?.study_id ?? null;
  // A Studio session stays blind until its design and curves are confirmed: nothing to read yet.
  const readable = studyId && workspace?.results_visible !== false ? studyId : null;
  const decisions = useDecisions(key, readable);
  const records = useRecords(key, readable);
  // An export started here, or one still running (started in another tab, say).
  const [startedId, setStartedId] = useState<string | null>(null);
  // the file dropped on "Verify a record": the terminal commands name it
  const [dropped, setDropped] = useState<string | null>(null);
  const running = workspace?.active_jobs.find((j) => j.kind === "record.export")?.id ?? null;
  const jobId = startedId ?? running;
  const latest = records.data?.records[0] ?? null;

  const head = decisions.data?.head ?? workspace?.decisions_head ?? null;
  const blind = decisions.error instanceof ApiError && decisions.error.code === "blind";
  const notYet =
    !readable || blind
      ? workspace?.kind === "session"
        ? "The record starts when this study is analysed: confirm the design and the curves first."
        : "This study has not been analysed yet."
      : null;
  const pending = decisions.data?.waiting.length ?? 0;
  const next = workspace?.next_step;

  return (
    <div className="mx-auto w-full max-w-[1280px]">
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
              {notYet} Every decision made after that is added here, each linked to the one before
              it.
            </EmptyState>
          ) : decisions.isPending ? (
            <Card>
              <CardBody className="pt-4">
                <LoadingBlock label="Reading the decision chain" lines={6} />
              </CardBody>
            </Card>
          ) : decisions.error ? (
            <ErrorPanel
              error={decisions.error}
              title="The decision chain could not be read"
              onRetry={() => void decisions.refetch()}
            />
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
              The chain starts at the input file. Each choice you make on a Decision Card, and each
              one qPilot or an agent makes, is added here.
            </EmptyState>
          ) : (
            <ChainTimeline
              entries={decisions.data.entries}
              root={decisions.data.root}
              head={decisions.data.head}
              intact={decisions.data.chain_intact}
              brokenAt={decisions.data.broken_at}
              waiting={decisions.data.waiting}
              attempts={decisions.data.attempts}
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
          <ExportCard
            workspaceKey={key}
            studyId={studyId}
            head={head}
            jobId={jobId}
            onJob={setStartedId}
            records={records.data?.records ?? []}
            disabledReason={notYet}
          />
          <VerifyCard onFile={setDropped} />
          <CommandsCard commands={latest?.commands} dropped={dropped} />
        </aside>
      </div>
    </div>
  );
}

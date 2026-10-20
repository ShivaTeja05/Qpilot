/**
 * Steps 1–2: the analysis choices the tables follow (confirmed in Results), and the Prism
 * project — which genes get a table, the test, the graph, the caption — drafted as a proposal
 * and accepted like any other.
 */
import { FileSpreadsheet, Lock, RefreshCw } from "lucide-react";
import { useState } from "react";
import { sectionPath } from "@/shell/sections";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  JobCard,
  KeyValues,
  LoadingBlock,
} from "@/ui";
import { effectivePayload, makerText } from "@/lib/vocab";
import {
  activeJob,
  useStartDraft,
  type PrismDrafted,
  type Proposal,
  type ProposalList,
  type Workspace,
} from "./api";
import type { Flow } from "./flow";
import { ProposalItem } from "./Inbox";

export function ProjectCard({
  workspace,
  flow,
  inbox,
}: {
  workspace: Workspace;
  flow: Flow;
  inbox: { data?: ProposalList; isPending: boolean; error: unknown; refetch: () => unknown };
}) {
  const draft = useStartDraft(workspace.key);
  const [jobId, setJobId] = useState<string | null>(null);
  const running = activeJob(workspace, "prism.draft");
  const shownJob = jobId ?? running?.id ?? null;
  const { accepted, waiting, earlier } = flow.project;

  const start = () => draft.mutate(undefined, { onSuccess: ({ job }) => setJobId(job.id) });

  const draftButton = (label: string, variant: "primary" | "secondary" = "primary") => (
    <Button
      variant={variant}
      icon={variant === "primary" ? <FileSpreadsheet /> : <RefreshCw />}
      loading={draft.isPending}
      disabled={Boolean(flow.draftBlocked) || Boolean(running)}
      title={flow.draftBlocked ?? undefined}
      onClick={start}
    >
      {label}
    </Button>
  );

  return (
    <Card
      as="section"
      aria-labelledby="prism-project-title"
      id="prism-step-project"
      tabIndex={-1}
      className="scroll-mt-4 outline-none"
    >
      <CardHeader
        id="prism-project-title"
        title="The Prism project"
        hint="Which genes get a table, the test, the graph and the caption. A proposal like any other: nothing is used until you accept it."
      />
      <CardBody className="flex flex-col gap-4">
        {!flow.choicesConfirmed ? (
          <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="flex items-start gap-2 text-[13px] text-fg">
              <Lock className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
              <span>
                First lock the analysis choices: decide the Decision Cards in Results and confirm
                them. The tables are exported at exactly those choices.
              </span>
            </p>
            <Button asChild variant="secondary" size="sm" className="shrink-0">
              <a href={`#${sectionPath(workspace, "results", "confirm")}`}>Go to the choices</a>
            </Button>
          </div>
        ) : null}

        {inbox.isPending ? (
          <LoadingBlock label="Reading the Prism draft" lines={3} />
        ) : inbox.error ? (
          <ErrorPanel
            error={inbox.error}
            title="The Prism draft could not be read"
            onRetry={() => void inbox.refetch()}
            compact
          />
        ) : waiting ? (
          <div className="flex flex-col gap-2">
            <p className="text-[13px] text-muted">
              A drafted project is waiting for you: check it, then accept or reject it.
            </p>
            <ProposalItem sid={workspace.key} proposal={waiting} head={inbox.data?.head ?? null} />
          </div>
        ) : accepted ? (
          <div className="flex flex-col gap-3">
            <ProjectSummary proposal={accepted} />
            <div className="flex flex-wrap items-center gap-3">
              {draftButton("Draft it again", "secondary")}
              <p className="text-[12px] text-muted">
                A new draft replaces this one only when you accept it.
              </p>
            </div>
          </div>
        ) : (
          <EmptyState
            icon={<FileSpreadsheet />}
            title={earlier ? "Draft the project again for this analysis" : "No Prism project yet"}
            compact
            action={draftButton("Draft the Prism project")}
          >
            {earlier
              ? "The project accepted earlier was for an analysis whose choices have changed since."
              : "qPilot drafts it from this analysis: a table for each headline gene, Welch's t test on log2 values, the graph and a caption whose numbers are facts of this study."}
            {flow.draftBlocked && flow.choicesConfirmed ? (
              <span className="mt-1 block text-faint">{flow.draftBlocked}</span>
            ) : null}
          </EmptyState>
        )}

        {draft.error ? (
          <ErrorPanel error={draft.error} title="No Prism project drafted" compact />
        ) : null}
        {shownJob ? (
          <JobCard id={shownJob} onDismiss={() => setJobId(null)}>
            {(result) => (
              <p className="text-[13px] text-fg">
                {(result as PrismDrafted | null)?.message ?? "Drafted."}
              </p>
            )}
          </JobCard>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** An accepted project in words: genes, template, test and graph, and who made it. */
export function ProjectSummary({ proposal }: { proposal: Proposal }) {
  const d = effectivePayload(proposal);
  const genes = Array.isArray(d.genes) ? d.genes.map(String) : [];
  const graph =
    d.graph && typeof d.graph === "object" ? (d.graph as Record<string, unknown>).label : d.graph;
  return (
    <div className="rounded-lg border border-ok/30 bg-ok-soft/40 p-3">
      <p className="mb-2 text-[13px] font-medium text-fg">Accepted for this analysis</p>
      <KeyValues
        rows={(
          [
            ["Tables", genes.length ? genes.join(", ") : "the headline genes"],
            ["Template", typeof d.template_id === "string" ? d.template_id : undefined],
            ["Test", typeof d.test === "string" ? d.test : undefined],
            ["Graph", typeof graph === "string" ? graph : undefined],
          ] as [string, string | undefined][]
        )
          .filter(([, v]) => Boolean(v))
          .map(([k, v]) => [k, v])}
      />
      <p className="mt-2 text-[12px] text-muted">
        {makerText(proposal.made_by)}
        {proposal.reason ? ` Reason given: ${proposal.reason}` : ""}
      </p>
    </div>
  );
}

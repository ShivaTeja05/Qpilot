/**
 * Agents (docs/app.md §4): how to connect an agent, what its tools can do, the requests waiting
 * for a person (Approve / Turn down) and recent agent activity. Live: a `study.changed` event
 * (an agent wrote, in another process) refreshes it.
 */
import { ArrowRight, Bot, Inbox } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { count } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, ErrorPanel, LoadingBlock, PageHeader, SegmentedControl } from "@/ui";
import { ActivityList } from "./ActivityList";
import { useAgents } from "./api";
import { RequestItem } from "./RequestItem";
import { ConnectCard, ToolsCard } from "./ToolsCard";
import type { AgentActivity, PendingRequest } from "./types";

type Scope = "this" | "all";

export default function AgentsSection({ workspace }: SectionProps) {
  const key = workspace?.key ?? "";
  const studyId = workspace?.study_id ?? null;
  const agents = useAgents(key, studyId);
  const now = useNow(60_000);
  const [scope, setScope] = useState<Scope>("this");

  const isHere = (s: string) => Boolean(studyId) && s === studyId;
  const note = (item: { study_id: string; study_title?: string | null }) =>
    isHere(item.study_id) ? null : <span>in {item.study_title || "another study"}</span>;
  const seeCard = (r: PendingRequest) =>
    isHere(r.study_id) ? (
      <Button asChild size="sm" variant="link">
        <Link href={sectionPath(workspace, "results")}>
          See what each option changes <ArrowRight aria-hidden />
        </Link>
      </Button>
    ) : null;

  const pending = agents.data?.pending ?? [];
  const here = pending.filter((r) => isHere(r.study_id));
  const elsewhere = pending.filter((r) => !isHere(r.study_id));
  const recent = (agents.data?.recent ?? []).filter((a: AgentActivity) => scope === "all" || isHere(a.study_id));

  return (
    <div className="mx-auto w-full max-w-[1280px]">
      <PageHeader
        eyebrow="Agents"
        title="Agents"
        hint="AI agents work on your studies through qPilot's MCP server. They can read, ask and propose; a choice that can change a conclusion always waits for a person."
      />

      {agents.isPending ? (
        <Card>
          <CardBody className="pt-4">
            <LoadingBlock label="Reading agent requests and tools" lines={6} />
          </CardBody>
        </Card>
      ) : agents.error ? (
        <ErrorPanel error={agents.error} title="The agents' requests could not be read" onRetry={() => void agents.refetch()} />
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
          <div className="flex min-w-0 flex-col gap-6">
            <section aria-labelledby="waiting-title">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 id="waiting-title" className="flex items-center gap-2 text-base font-semibold tracking-tight text-fg">
                    Waiting for you
                    {pending.length ? <Badge tone="warn">{count(pending.length)}</Badge> : null}
                  </h2>
                  <p className="mt-0.5 text-[13px] text-muted">
                    Requests an agent made on choices that can change a conclusion. Your reason goes into the record.
                  </p>
                </div>
              </div>
              {pending.length === 0 ? (
                <EmptyState compact icon={<Inbox />} title="No requests waiting">
                  When an agent asks for a choice that can change a conclusion, it waits here (and in the bell) until you
                  approve or turn it down.
                </EmptyState>
              ) : (
                <ul className="flex flex-col gap-3" aria-label="Requests waiting for a person">
                  {[...here, ...elsewhere].map((r) => (
                    <RequestItem key={r.hash} request={r} workspaceKey={key} now={now} studyNote={note(r)} seeCard={seeCard(r)} />
                  ))}
                </ul>
              )}
            </section>

            <Card as="section" aria-labelledby="recent-title">
              <CardHeader
                id="recent-title"
                title="Recent agent activity"
                hint="Requests and choices on Decision Cards, and proposals in the Studio inbox, newest first."
                actions={
                  <SegmentedControl
                    label="Show activity for"
                    size="sm"
                    value={scope}
                    onValueChange={setScope}
                    options={[
                      { value: "this", label: "This study", disabled: !studyId },
                      { value: "all", label: "All studies" },
                    ]}
                  />
                }
              />
              <CardBody>
                {recent.length ? (
                  <ActivityList items={recent} now={now} studyNote={note} />
                ) : (
                  <EmptyState compact icon={<Bot />} title={scope === "this" ? "No agent has worked on this study yet" : "No agent activity yet"}>
                    Connect an agent with the command on this page; what it asks and proposes shows up here as it happens.
                  </EmptyState>
                )}
              </CardBody>
            </Card>
          </div>

          <aside className="flex min-w-0 flex-col gap-6" aria-label="Connect an agent">
            <ConnectCard commands={agents.data.connect} />
            <ToolsCard tools={agents.data.tools} />
          </aside>
        </div>
      )}
    </div>
  );
}

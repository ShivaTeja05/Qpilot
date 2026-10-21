/**
 * Agents (docs/app.md §4): how to connect an agent, what it can and cannot do, the requests
 * waiting for a person (Approve / Turn down) and recent agent activity. Live: a `study.changed`
 * event (an agent wrote, in another process) refreshes it.
 */
import { ArrowRight, Bot, EyeOff, Inbox } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { count, plural } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  PageHeader,
  SegmentedControl,
} from "@/ui";
import { ActivityList, requestKey } from "./ActivityList";
import { useAgents } from "./api";
import { RequestItem } from "./RequestItem";
import { ConnectCard, RulesCard, ToolsCard } from "./ToolsCard";

type Scope = "this" | "all";

/** A workspace by its key and kind, as the page routes to it. */
const place = (key: string, kind: "session" | "study") => ({ key, kind });

export default function AgentsSection({ workspace }: SectionProps) {
  const key = workspace?.key ?? "";
  const studyId = workspace?.study_id ?? null;
  const agents = useAgents(key, studyId);
  const now = useNow(60_000);
  const [scope, setScope] = useState<Scope>("this");

  const isHere = (item: { key: string; study_id?: string }) =>
    item.key === key || (Boolean(studyId) && item.study_id === studyId);
  const elsewhere = (title: string, k: string, kind: "session" | "study") => (
    <Link
      href={sectionPath(place(k, kind), "agents")}
      className="text-muted underline-offset-2 hover:text-fg hover:underline"
    >
      in {title}
    </Link>
  );

  const data = agents.data;
  const pending = data
    ? [...data.pending.filter(isHere), ...data.pending.filter((r) => !isHere(r))]
    : [];
  const activity = (data?.activity ?? []).filter((a) => scope === "all" || isHere(a));
  const waiting = new Set((data?.pending ?? []).map(requestKey));

  return (
    <div className="mx-auto w-full max-w-[1280px]">
      <PageHeader
        eyebrow="Agents"
        title="Agents"
        hint="AI agents work on your studies through qPilot's MCP server. They read, open and propose; a choice that can change a conclusion always waits for a person."
      />

      {agents.error ? (
        <ErrorPanel
          error={agents.error}
          title="The agents' requests could not be read"
          onRetry={() => void agents.refetch()}
        />
      ) : !data ? (
        <Card>
          <CardBody className="pt-4">
            <LoadingBlock label="Reading agent requests and tools" lines={6} />
          </CardBody>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="flex min-w-0 flex-col gap-6">
            <section aria-labelledby="waiting-title">
              <div className="mb-3">
                <h2
                  id="waiting-title"
                  className="flex items-center gap-2 text-base font-semibold tracking-tight text-fg"
                >
                  Waiting for you
                  {pending.length ? <Badge tone="warn">{count(pending.length)}</Badge> : null}
                </h2>
                <p className="mt-0.5 text-[13px] text-muted">
                  An agent asked for these choices; you approve or turn each down, with your reason.
                  Both go into the record.
                </p>
              </div>
              {pending.length === 0 ? (
                <EmptyState compact icon={<Inbox />} title="No requests waiting">
                  When an agent asks for a choice that can change a conclusion, it waits here (and
                  in the bell) until you approve or turn it down.
                </EmptyState>
              ) : (
                <ul className="flex flex-col gap-3" aria-label="Requests waiting for a person">
                  {pending.map((r) => (
                    <RequestItem
                      key={r.hash}
                      request={r}
                      workspaceKey={key}
                      now={now}
                      studyNote={isHere(r) ? null : elsewhere(r.title, r.key, r.kind)}
                      seeCard={
                        <Button asChild size="sm" variant="link">
                          <Link href={sectionPath(place(r.key, r.kind), "results")}>
                            See what each option changes <ArrowRight aria-hidden />
                          </Link>
                        </Button>
                      }
                    />
                  ))}
                </ul>
              )}
              {data.hidden_blind ? (
                <p className="mt-3 flex items-start gap-2 text-xs text-muted">
                  <EyeOff className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {plural(data.hidden_blind, "agent entry", "agent entries")} in sessions still
                  blind are not shown until their design and curves are confirmed.
                </p>
              ) : null}
            </section>

            <Card as="section" aria-labelledby="recent-title">
              <CardHeader
                id="recent-title"
                title="Recent agent activity"
                hint="Requests and choices on Decision Cards, and proposals in Studio inboxes, newest first."
                actions={
                  <SegmentedControl
                    label="Show activity for"
                    size="sm"
                    value={scope}
                    onValueChange={setScope}
                    options={[
                      { value: "this", label: "This study" },
                      { value: "all", label: "All studies" },
                    ]}
                  />
                }
              />
              <CardBody>
                {activity.length ? (
                  <>
                    <ActivityList
                      items={activity}
                      waiting={waiting}
                      now={now}
                      where={(a) =>
                        isHere(a) ? null : elsewhere(a.title, a.key, a.workspace_kind)
                      }
                    />
                    {scope === "all" && data.activity_total > data.activity.length ? (
                      <p className="mt-3 text-xs text-faint">
                        The latest {count(data.activity.length)} of {count(data.activity_total)}.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <EmptyState
                    compact
                    icon={<Bot />}
                    title={
                      scope === "this"
                        ? "No agent has worked on this study yet"
                        : "No agent activity yet"
                    }
                  >
                    Connect an agent with the command on this page; what it asks and proposes shows
                    up here as it happens.
                  </EmptyState>
                )}
              </CardBody>
            </Card>
          </div>

          <aside className="flex min-w-0 flex-col gap-6" aria-label="Connect an agent">
            <ConnectCard
              command={data.connect}
              note={data.connect_note}
              storeNote={data.store_note}
            />
            <RulesCard rules={data.rules} />
            <ToolsCard tools={data.tools} simulator={data.simulator} />
          </aside>
        </div>
      )}
    </div>
  );
}

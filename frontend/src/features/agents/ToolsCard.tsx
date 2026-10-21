/** How to connect an agent, what it can and cannot do, and its tools by what they can change. */
import { Eye, FolderOpen, Hand, Lightbulb, PlugZap, ShieldAlert, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { count } from "@/lib/format";
import { Card, CardBody, CardHeader, CommandLine } from "@/ui";
import type { AgentTool, ToolAccess } from "./types";

const ACCESS: Record<ToolAccess, { title: string; hint: string; icon: ReactNode }> = {
  read: {
    title: "Read",
    hint: "Look at studies, genes, the audit and the inbox. They change nothing.",
    icon: <Eye aria-hidden />,
  },
  open: {
    title: "Open",
    hint: "Open a file as a study or a Studio session. They decide nothing.",
    icon: <FolderOpen aria-hidden />,
  },
  propose: {
    title: "Propose",
    hint: "Add a proposal to a Studio inbox. Only a person accepts, edits or rejects it.",
    icon: <Lightbulb aria-hidden />,
  },
  request: {
    title: "Request a decision",
    hint: "Ask for a choice on a Decision Card. One that can change a conclusion always waits for a person.",
    icon: <Hand aria-hidden />,
  },
};
const ORDER: ToolAccess[] = ["request", "propose", "open", "read"];

export function ConnectCard({
  command,
  note,
  storeNote,
}: {
  command: string;
  note: string;
  storeNote?: string | null;
}) {
  return (
    <Card as="section" aria-labelledby="connect-title">
      <CardHeader
        id="connect-title"
        title={
          <span className="inline-flex items-center gap-2">
            <PlugZap className="size-4 text-muted" aria-hidden /> Connect an agent
          </span>
        }
        hint={note}
      />
      <CardBody className="flex flex-col gap-3">
        <CommandLine command={command} />
        {storeNote ? <p className="text-xs text-muted">{storeNote}</p> : null}
        <div className="flex gap-2.5 rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2.5 text-[13px] text-fg">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <p>
            Give agents MCP access, not your shell: an agent that can run commands as you can act as
            you. What the tools return goes to the agent's own model.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}

export function RulesCard({ rules }: { rules: string[] }) {
  return (
    <Card as="section" aria-labelledby="rules-title">
      <CardHeader
        id="rules-title"
        title={
          <span className="inline-flex items-center gap-2">
            <ShieldCheck className="size-4 text-muted" aria-hidden /> What an agent can never do
          </span>
        }
        hint="Enforced by qPilot's code, whatever an agent or its model says."
      />
      <CardBody>
        <ul className="flex flex-col gap-1.5 text-[13px] text-fg">
          {rules.map((r) => (
            <li key={r} className="flex gap-2">
              <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" />
              {r}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

export function ToolsCard({ tools, simulator }: { tools: AgentTool[]; simulator: boolean }) {
  const groups = ORDER.map((access) => ({
    access,
    tools: tools.filter((t) => t.access === access),
  })).filter((g) => g.tools.length);
  return (
    <Card as="section" aria-labelledby="tools-title">
      <CardHeader
        id="tools-title"
        title="The tools"
        hint={`${count(tools.length)} tools on this install${simulator ? ", with the audit's read-only tools" : " (the audit's tools appear when the simulator is installed)"}.`}
      />
      <CardBody className="flex flex-col gap-4">
        {groups.map((g) => (
          <div key={g.access}>
            <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-fg [&_svg]:size-3.5 [&_svg]:text-muted">
              {ACCESS[g.access].icon}
              {ACCESS[g.access].title}
              <span className="font-mono text-[11px] font-normal text-faint tabular">
                {count(g.tools.length)}
              </span>
            </h3>
            <p className="mt-0.5 text-xs text-muted">{ACCESS[g.access].hint}</p>
            <ul className="mt-2 flex flex-col gap-2">
              {g.tools.map((t) => (
                <li key={t.name} className="text-[13px]">
                  <details className="group">
                    <summary className="cursor-pointer list-none rounded-md outline-offset-2 [&::-webkit-details-marker]:hidden">
                      <code className="rounded bg-sunken px-1 py-0.5 font-mono text-[12px] text-fg">
                        {t.name}
                      </code>
                      <span className="ml-2 text-muted">{t.summary}</span>
                    </summary>
                    <div className="mt-1.5 ml-1 border-l-2 border-line pl-3 text-xs text-muted">
                      {g.access !== "read" ? (
                        <p>
                          <span className="font-medium text-fg">What it can change: </span>
                          {t.effect}
                        </p>
                      ) : null}
                      <p className="mt-1 whitespace-pre-line">{t.description}</p>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/** How to connect an agent, and the tools it gets: read, ask, propose, request. */
import { Eye, Hand, Lightbulb, MessageCircleQuestion, PlugZap, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { count } from "@/lib/format";
import { Card, CardBody, CardHeader, CommandLine } from "@/ui";
import type { AgentTool, ToolKind } from "./types";

const KIND: Record<ToolKind, { title: string; hint: string; icon: ReactNode }> = {
  read: { title: "Read", hint: "Look at studies, genes, the audit and the inbox. Change nothing.", icon: <Eye aria-hidden /> },
  ask: { title: "Ask", hint: "Answer questions from the engine's numbers.", icon: <MessageCircleQuestion aria-hidden /> },
  propose: {
    title: "Propose",
    hint: "Add a proposal to the Studio inbox. Nothing applies until a person accepts it.",
    icon: <Lightbulb aria-hidden />,
  },
  request: {
    title: "Request a decision",
    hint: "Ask for a choice on a Decision Card. One that can change a conclusion waits for a person.",
    icon: <Hand aria-hidden />,
  },
};
const ORDER: ToolKind[] = ["read", "ask", "propose", "request"];

export function ConnectCard({ commands }: { commands: string[] }) {
  return (
    <Card as="section" aria-labelledby="connect-title">
      <CardHeader
        id="connect-title"
        title={
          <span className="inline-flex items-center gap-2">
            <PlugZap className="size-4 text-muted" aria-hidden /> Connect an agent
          </span>
        }
        hint="qPilot's MCP server runs on this computer and works on the same studies as this page. Run this in a terminal:"
      />
      <CardBody className="flex flex-col gap-3">
        {commands.map((c) => (
          <CommandLine key={c} command={c} />
        ))}
        <p className="text-[13px] text-muted">
          What the tools return goes to the agent's own model. Every call is recorded as an agent, never as you.
        </p>
        <div className="flex gap-2.5 rounded-lg border border-warn/30 bg-warn-soft/50 px-3 py-2.5 text-[13px] text-fg">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <p>
            Give agents MCP access, not your shell. An agent that can run commands as you can act as you, for example by
            driving this page.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}

export function ToolsCard({ tools }: { tools: AgentTool[] }) {
  const groups = ORDER.map((kind) => ({ kind, tools: tools.filter((t) => t.kind === kind) })).filter((g) => g.tools.length);
  return (
    <Card as="section" aria-labelledby="tools-title">
      <CardHeader
        id="tools-title"
        title="What an agent can do"
        hint={`${count(tools.length)} tools. None of them can decide a choice that can change a conclusion: that always waits for a person, here or on the Decision Cards.`}
      />
      <CardBody className="flex flex-col gap-4">
        {groups.map((g) => (
          <div key={g.kind}>
            <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-fg [&_svg]:size-3.5 [&_svg]:text-muted">
              {KIND[g.kind].icon}
              {KIND[g.kind].title}
              <span className="font-mono text-[11px] font-normal text-faint tabular">{count(g.tools.length)}</span>
            </h3>
            <p className="mt-0.5 text-xs text-muted">{KIND[g.kind].hint}</p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {g.tools.map((t) => (
                <li key={t.name} className="text-[13px]">
                  <code className="rounded bg-sunken px-1 py-0.5 font-mono text-[12px] text-fg">{t.name}</code>
                  <span className="ml-2 text-muted">{t.description}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/**
 * Prism (docs/app.md §4): why the usual Excel→Prism route is risky on this study, what Prism will
 * get (tables and a figure per gene), the Prism project drafted as a proposal, Send to Prism, and
 * the round trip that turns every change made in Prism into a question with its consequence.
 * Session-only; nothing here is shown or sent before the design and the curves are confirmed
 * (the server answers 403 `blind` before that).
 */
import { EyeOff, Send } from "lucide-react";
import type { SectionProps } from "@/shell/sections";
import { sectionPath } from "@/shell/sections";
import { Button, CommandLine, EmptyState, PageHeader } from "@/ui";
import { useStageInbox, type Workspace } from "./api";
import { flowOf } from "./flow";
import { PreviewCard } from "./PreviewCard";
import { ProjectCard } from "./ProjectCard";
import { RoundTripCard } from "./RoundTripCard";
import { RoutesCard } from "./RoutesCard";
import { SendCard } from "./SendCard";
import { Steps } from "./Steps";

const HINT = "Hand GraphPad Prism numbers it cannot misread, and see what changed when the tables come back.";

export default function PrismSection({ workspace }: SectionProps) {
  return <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">{body(workspace)}</div>;
}

function body(workspace: Workspace | null) {
  if (!workspace) return null;
  if (workspace.kind !== "session") return <NotASession workspace={workspace} />;
  if (!workspace.results_visible) return <StillBlind workspace={workspace} />;
  return <PrismWorkspace workspace={workspace} />;
}

function NotASession({ workspace }: { workspace: Workspace }) {
  return (
    <>
      <PageHeader title="Prism" hint={HINT} />
      <EmptyState icon={<Send />} title="Prism works inside a Studio session">
        <p>
          This study was analysed outside Studio (by <span className="font-mono">qpilot run</span> or an agent), so it has no
          Prism project to draft or accept. Export its tables for Prism from a terminal:
        </p>
        <CommandLine className="mt-3 text-left" command={`qpilot export prism --study ${workspace.study_id ?? workspace.key} --out <new folder>`} />
      </EmptyState>
    </>
  );
}

function StillBlind({ workspace }: { workspace: Workspace }) {
  const design = workspace.stages.find((s) => s.stage === "design");
  const next = design && !design.confirmed ? "design" : "curves";
  return (
    <>
      <PageHeader title="Prism" hint={HINT} />
      <EmptyState
        icon={<EyeOff />}
        title="Prism opens once the design and the curves are confirmed"
        action={
          <Button asChild variant="primary">
            <a href={`#${sectionPath(workspace, next)}`}>{next === "design" ? "Go to the design" : "Go to the curves"}</a>
          </Button>
        }
      >
        Until then no table, fold change or p-value is shown or written, so the blind stages stay blind.
      </EmptyState>
    </>
  );
}

function PrismWorkspace({ workspace }: { workspace: Workspace }) {
  const prismInbox = useStageInbox(workspace.key, "prism");
  const roundTripInbox = useStageInbox(workspace.key, "roundtrip");
  const flow = flowOf(workspace, prismInbox.data?.proposals ?? [], roundTripInbox.data?.proposals ?? []);
  return (
    <>
      <PageHeader eyebrow="Studio · GraphPad Prism" title="Prism" hint={HINT} />
      <div className="flex flex-col gap-6">
        <Steps flow={flow} />
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <RoutesCard workspace={workspace} />
          <div className="flex flex-col gap-6">
            <ProjectCard workspace={workspace} flow={flow} inbox={prismInbox} />
            <SendCard workspace={workspace} flow={flow} />
          </div>
        </div>
        <PreviewCard workspace={workspace} />
        <RoundTripCard workspace={workspace} inbox={roundTripInbox} />
      </div>
    </>
  );
}

/**
 * Prism (docs/app.md §4): why the usual Excel→Prism route is risky on this study, what Prism will
 * get (tables and a figure per gene), the Prism project drafted as a proposal, Send to Prism, and
 * the round trip that turns every change made in Prism into a question with its consequence.
 * Session-only; nothing here is shown or sent before the design and the curves are confirmed
 * (the server answers 403 `blind` before that).
 */
import type { SectionProps } from "@/shell/sections";
import { PageHeader } from "@/ui";
import { useStageInbox, type Workspace } from "./api";
import { flowOf } from "./flow";
import { PreviewCard } from "./PreviewCard";
import { ProjectCard } from "./ProjectCard";
import { RoundTripCard } from "./RoundTripCard";
import { RoutesCard } from "./RoutesCard";
import { SendCard } from "./SendCard";
import { Steps } from "./Steps";

const HINT =
  "Hand GraphPad Prism numbers it cannot misread, and see what changed when the tables come back.";

export default function PrismSection({ workspace }: SectionProps) {
  // The shell shows Prism only for a session whose results are visible (it says why otherwise);
  // the server refuses every Prism route before that (403 `blind`).
  if (!workspace) return null;
  return <PrismWorkspace workspace={workspace} />;
}

function PrismWorkspace({ workspace }: { workspace: Workspace }) {
  const prismInbox = useStageInbox(workspace.key, "prism");
  const roundTripInbox = useStageInbox(workspace.key, "roundtrip");
  const flow = flowOf(
    workspace,
    prismInbox.data?.proposals ?? [],
    roundTripInbox.data?.proposals ?? [],
  );
  return (
    <>
      <PageHeader eyebrow="Studio · GraphPad Prism" title="Prism" hint={HINT} />
      <div className="flex flex-col gap-6">
        <Steps flow={flow} />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <RoutesCard workspace={workspace} />
          <div className="flex min-w-0 flex-col gap-6">
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

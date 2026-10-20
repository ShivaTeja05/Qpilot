/**
 * What the design still needs before it can be confirmed (the stage's blockers, in the
 * engine's words), and where the missing proposals can come from when none is waiting.
 */
import { ListChecks } from "lucide-react";
import type { Proposal } from "@/lib/vocab";
import { Button } from "@/ui";

const sentence = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

export function DesignNeeds({
  blockers,
  proposals,
  onOpen,
  onSettings,
}: {
  blockers: string[];
  proposals: Proposal[];
  /** Go to Open (to open the file again with a sample sheet). */
  onOpen: () => void;
  /** Go to Settings (to connect a model). */
  onSettings: () => void;
}) {
  if (!blockers.length) return null;
  const waiting = (kinds: Proposal["kind"][]) => proposals.some((p) => p.status === "proposed" && kinds.includes(p.kind));
  const groupsMissing = blockers.some((b) => /comparison|group/i.test(b)) && !waiting(["design.group", "design.comparison", "design.preset"]);
  const refsMissing = blockers.some((b) => /reference/i.test(b)) && !waiting(["design.target_role", "design.preset"]);
  return (
    <section aria-labelledby="design-needs" className="flex gap-3 rounded-xl border border-info/30 bg-info-soft/40 p-4">
      <ListChecks className="mt-0.5 size-5 shrink-0 text-info" aria-hidden />
      <div className="min-w-0 flex-1">
        <h2 id="design-needs" className="text-sm font-semibold text-fg">
          What the design still needs before it can be confirmed
        </h2>
        <ul className="mt-1 list-disc pl-5 text-[13px] text-fg">
          {blockers.map((b) => (
            <li key={b}>{sentence(b)}.</li>
          ))}
        </ul>
        {groupsMissing || refsMissing ? (
          <>
            <p className="mt-2 text-[13px] text-muted">
              No proposal for {groupsMissing && refsMissing ? "the groups or the reference genes" : groupsMissing ? "the groups" : "the reference genes"} is
              waiting. qPilot's rules read groups from a sample sheet's group column, and a model can read them from the
              names; neither had them for this file. Open the file again with a sample sheet, or connect a model, then
              propose again.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={onOpen}>
                Open with a sample sheet
              </Button>
              <Button size="sm" variant="ghost" onClick={onSettings}>
                Model settings
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

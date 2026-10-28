/**
 * What the design still needs before it can be confirmed, each with the control on this page
 * that gives it (the target list, the sample table, the comparison, the inbox). A model is
 * optional: the person can set everything here, or attach a sample sheet.
 */
import { ListChecks } from "lucide-react";
import type { Schemas } from "@/api/client";
import { Button } from "@/ui";

export type Need = Schemas["DesignNeed"];
export type NeedPlace = Need["where"] | "sheet";

const sentence = (s: string) => {
  const t = s ? s[0]!.toUpperCase() + s.slice(1) : s;
  return /[.!?]$/.test(t) ? t : `${t}.`;
};

const GO: Record<string, { label: string; to: NeedPlace }> = {
  reference: { label: "Choose the reference genes", to: "targets" },
  gene: { label: "Mark the genes of interest", to: "targets" },
  groups: { label: "Set the groups", to: "samples" },
  comparison: { label: "Choose the comparison", to: "comparison" },
  waiting: { label: "Show the waiting proposals", to: "inbox" },
};

export function DesignNeeds({
  needs,
  blockers,
  onGo,
  unrecorded = 0,
}: {
  /** From the editor's view (each with where it is fixed); `undefined` while it loads. */
  needs: Need[] | undefined;
  /** The design stage's blockers, in the engine's words (shown while the editor loads). */
  blockers: string[];
  onGo: (where: NeedPlace) => void;
  /** Changes in the editor's draft: they count once they are recorded. */
  unrecorded?: number;
}) {
  const list: Need[] =
    needs ?? blockers.map((b) => ({ code: "engine", words: b, where: "engine" as const }));
  if (!list.length) return null;
  const fixable = list.some((n) => n.where !== "engine" && n.where !== "inbox");
  return (
    <section
      aria-labelledby="design-needs"
      className="flex gap-3 rounded-xl border border-info/30 bg-info-soft/40 p-4"
    >
      <ListChecks className="mt-0.5 size-5 shrink-0 text-info" aria-hidden />
      <div className="min-w-0 flex-1">
        <h2 id="design-needs" className="text-sm font-semibold text-fg">
          What the design still needs before it can be confirmed
        </h2>
        {unrecorded ? (
          <p className="mt-1 text-[13px] text-muted">
            Your {unrecorded} change{unrecorded === 1 ? " is" : "s are"} not recorded yet, so
            {unrecorded === 1 ? " it is" : " they are"} not counted here: review and record{" "}
            {unrecorded === 1 ? "it" : "them"} below.
          </p>
        ) : null}
        <ul className="mt-2 flex flex-col gap-2 text-[13px] text-fg">
          {list.map((n) => {
            const go = GO[n.code];
            return (
              <li
                key={`${n.code}:${n.words}`}
                className="flex flex-wrap items-center gap-x-3 gap-y-1"
              >
                <span className="min-w-0 flex-1">{sentence(n.words)}</span>
                {go ? (
                  <Button size="sm" variant="secondary" onClick={() => onGo(go.to)}>
                    {go.label}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
        {fixable ? (
          <p className="mt-3 text-[13px] text-muted">
            A model is optional: you can set all of this on this page (below), or fill the sample
            sheet template and attach it.{" "}
            <Button
              size="sm"
              variant="link"
              className="h-auto p-0 align-baseline"
              onClick={() => onGo("sheet")}
            >
              Use a sample sheet
            </Button>
          </p>
        ) : null}
      </div>
    </section>
  );
}

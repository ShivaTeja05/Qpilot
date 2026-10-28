/**
 * A person's choice carried to a new analysis, as History shows it: the step says who chose what,
 * quotes the person's own words, names the earlier analysis and entry (and whether it is found
 * there); step 0 says what was carried and what is asked again. Built on the recorded demo
 * analysis made after the round trip, with a carried step added as the server now writes it.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/ui";
import type { HistoryStep, HistoryView } from "../api";
import type { Point } from "../model";
import afterJson from "../recorded/history-e300000d4f9a.json";
import { StepPanel } from "../StepPanel";
import { pointTitle } from "../words";

const recorded = afterJson as unknown as HistoryView;
const EARLIER = "cf49ccd72052";
const ENTRY = "ab".repeat(32);
const REASON = "the lab cuts at 15 % for this cohort";

const auto = recorded.steps[1]!;
const carriedStep: HistoryStep = {
  ...auto,
  seq: 2,
  actor: "human",
  card_id: "card_cutoff",
  card_title: "Where to cut the comparison groups",
  option: "cut_15",
  option_label: "Top 15 % by MYCN expression",
  reason: REASON,
  status: "applied",
  undo: false,
  carried: {
    study_id: EARLIER,
    entry_hash: ENTRY,
    reason: REASON,
    found: true,
    decided_at: "2026-10-20T19:10:00Z",
  },
  effect: "Carried from the earlier analysis. The analysis in force stayed the same.",
  conclusions: { ...auto.conclusions!, n_changed: 0, n_moved: 0 },
};
const view: HistoryView = {
  ...recorded,
  steps: [...recorded.steps, carriedStep],
  carry: {
    from_study: EARLIER,
    carried: [
      {
        card_id: "card_cutoff",
        card_title: "Where to cut the comparison groups",
        option: "cut_15",
        option_label: "Top 15 % by MYCN expression",
        why: null,
      },
    ],
    asked_again: [
      {
        card_id: "card_refset",
        card_title: "Which control genes to normalise to",
        option: "top3",
        option_label: "The three most stable",
        why: "in this analysis the choice can change a conclusion",
      },
    ],
    gone: [],
  },
};

function point(step: HistoryStep): Point {
  return { kind: "step", id: `s${step.seq}`, step, analysis: null, genes: [] };
}

function show(step: HistoryStep, onOpenStudy = vi.fn()) {
  render(
    <TooltipProvider>
      <StepPanel
        wkey="w"
        view={view}
        point={point(step)}
        previous={null}
        onGene={() => {}}
        onOpenStudy={onOpenStudy}
      />
    </TooltipProvider>,
  );
  return onOpenStudy;
}

afterEach(cleanup);

describe("a carried choice in History", () => {
  it("names the earlier analysis and its entry, quotes the person, and opens that history", () => {
    const open = show(carriedStep);
    const panel = screen.getByRole("region", { name: /Step 2/ });
    expect(panel.textContent).toContain("A person");
    expect(panel.textContent).toContain(`“${REASON}”`);
    expect(panel.textContent).toContain(`Carried from the earlier analysis ${EARLIER}`);
    expect(within(panel).getByText("Carried")).toBeTruthy();
    expect(within(panel).getByText("found there")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: /Open its history/ }));
    expect(open).toHaveBeenCalledWith(EARLIER);
    expect(pointTitle(point(carriedStep))).toContain(
      "(carried over from the earlier analysis of these data)",
    );
  });

  it("says at step 0 what was carried, what is asked again and why", () => {
    show(recorded.steps[0]!);
    const note = screen.getByRole("region", { name: "Choices from the earlier analysis" });
    expect(note.textContent).toContain("Where to cut the comparison groups: Top 15 %");
    expect(note.textContent).toContain(
      "Asked again: Which control genes to normalise to (a person had chosen The three most stable): in this analysis the choice can change a conclusion.",
    );
    expect(note.textContent).toContain("The choices stage is never carried");
  });

  it("marks a link it cannot find", () => {
    show({ ...carriedStep, carried: { ...carriedStep.carried!, found: false, decided_at: null } });
    expect(screen.getByText("not found there")).toBeTruthy();
  });
});

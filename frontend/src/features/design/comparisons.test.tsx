// Several comparisons on the Design page, on the editor's view of a real file recorded from the
// API (src/test/recorded/record_compare2.py: the corpus' K. phaffii UPR RDML, four conditions put
// in their groups by a person). Nothing is hand-written except the person's clicks.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import editorJson from "@/test/recorded/api-design-editor-kphaffii.json";
import { TooltipProvider } from "@/ui";
import { ComparisonPanel } from "./ComparisonPanel";
import { EMPTY_DRAFT, type Draft, type EditorView } from "./draft";
import { corrections, guessControl, planItem, planNow, planPairs, type PlanChoice } from "./plan";

const view = editorJson as unknown as EditorView;
const names = Object.keys(view.groups);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const choice = (over: Partial<PlanChoice>): PlanChoice => ({
  pattern: "vs_control",
  control: "20",
  pairs: [],
  correction: "holm",
  paired: false,
  ...over,
});

describe("the plan a person sets", () => {
  it("each against a control, every pair, or a list", () => {
    expect(names).toEqual(["20", "28", "D20", "D28"]);
    expect(planPairs(names, choice({}))).toEqual([
      ["28", "20"],
      ["D20", "20"],
      ["D28", "20"],
    ]);
    expect(planPairs(names, choice({ pattern: "all_pairs" }))).toHaveLength(6);
    const own = choice({
      pattern: "chosen",
      pairs: [
        ["D20", "20"],
        ["D28", "28"],
      ],
    });
    expect(planPairs(names, own)).toEqual([
      ["D20", "20"],
      ["D28", "28"],
    ]);
    expect(guessControl(["Vehicle", "Drug A", "Drug B"])).toBe("Vehicle");
    expect(guessControl(["0 h", "24 h", "48 h"])).toBe("0 h");
    expect(guessControl(names)).toBeNull(); // 20 °C is not a control by its name
  });

  it("offers Dunnett only against a control and Tukey only for every pair, never paired", () => {
    const by = (c: PlanChoice) =>
      Object.fromEntries(corrections(c).map((o) => [o.value, o.unavailable]));
    expect(by(choice({})).dunnett).toBeNull();
    expect(by(choice({})).tukey).toContain("every pair");
    expect(by(choice({ pattern: "all_pairs" })).tukey).toBeNull();
    expect(by(choice({ paired: true })).dunnett).toContain("pairing");
  });

  it("writes the engine's payload, and one unpaired comparison stays the plain one", () => {
    const item = planItem(names, choice({ correction: "dunnett" }), null);
    expect(typeof item).not.toBe("string");
    expect(item).toMatchObject({
      kind: "design.comparison",
      payload: {
        group_a: "28",
        group_b: "20",
        pattern: "vs_control",
        control: "20",
        correction: "dunnett",
        comparisons: [
          { group_a: "28", group_b: "20" },
          { group_a: "D20", group_b: "20" },
          { group_a: "D28", group_b: "20" },
        ],
      },
    });
    const one = planItem(names, choice({ pattern: "chosen", pairs: [["D20", "20"]] }), null);
    expect(one).toEqual({
      kind: "design.comparison",
      subject: "comparison",
      payload: { group_a: "D20", group_b: "20" },
    });
    expect(planItem(names, choice({ control: null }), null)).toBe("Choose the control group.");
    // a correction that does not fit the pattern falls back to Holm's
    const tukey = planItem(names, choice({ correction: "tukey" }), null);
    expect(typeof tukey !== "string" && tukey.payload?.correction).toBe("holm");
    expect(planNow(names, null).pattern).toBe("all_pairs"); // no control-like name to guess
  });
});

describe("the comparisons editor", { timeout: 30_000 }, () => {
  it("sets each condition against 20 with Dunnett's correction, as the person's own item", () => {
    const onDraft = vi.fn<(d: Draft) => void>();
    render(
      <TooltipProvider>
        <ComparisonPanel view={view} draft={EMPTY_DRAFT} onDraft={onDraft} onGoSamples={() => {}} />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Several comparisons" }));
    const panel = screen.getByTestId("comparisons-editor");
    fireEvent.click(within(panel).getByRole("radio", { name: "Each group against a control" }));
    // the control: no name says which, so the person picks 20
    const control = within(panel).getByRole("combobox", { name: "Control group" });
    fireEvent.click(control);
    fireEvent.click(screen.getByRole("option", { name: /^20/ }));
    fireEvent.click(within(panel).getByRole("radio", { name: /Dunnett/ }));
    expect(within(panel).getByRole("radio", { name: /Tukey/ })).toHaveProperty("disabled", true);
    expect(within(panel).getByRole("status").textContent).toBe(
      "3 comparisons: 28 vs 20; D20 vs 20; D28 vs 20.",
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Set the comparisons" }));
    expect(onDraft).toHaveBeenCalledTimes(1);
    const draft = onDraft.mock.calls[0]![0];
    const item = [...draft.values()].find((i) => i.kind === "design.comparison")!;
    expect(item.payload).toMatchObject({
      control: "20",
      correction: "dunnett",
      pattern: "vs_control",
    });
  });
});

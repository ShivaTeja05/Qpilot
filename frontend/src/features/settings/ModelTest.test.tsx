import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import recorded from "./recorded/model-test.json";
import { rowModel, Scorecard } from "./ModelTest";

afterEach(cleanup);

describe("Scorecard", () => {
  it("shows each measure as a row and each model as a column, this run first", () => {
    render(<Scorecard result={recorded} />);
    const table = screen.getByRole("table");
    const r = recorded.current;
    // The saved row of this run's profile is this run: one column, not two.
    expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
    expect(within(table).getByText(rowModel(r))).toBeTruthy();
    const right = within(table).getByText("Right answers").closest("tr")!;
    expect(right.textContent).toContain(`${r.correct} of ${r.n_items}`);
    const safety = within(table).getByText("Safety held").closest("tr")!;
    expect(safety.textContent).toContain(`${r.safety_held} of ${r.safety_items}`);
    // No model: no fallbacks to count.
    const fallbacks = within(table).getByText("Fallbacks").closest("tr")!;
    expect(fallbacks.textContent).toContain("—");
    expect(screen.getByText(recorded.note)).toBeTruthy();
  });

  it("names the templates when no model answered", () => {
    expect(rowModel(recorded.current)).toBe("No model (templates)");
  });
});

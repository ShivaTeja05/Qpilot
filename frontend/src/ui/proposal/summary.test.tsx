// Recorded from the real Studio service (see ./recorded/README.md); nothing hand-written.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Proposal } from "@/lib/vocab";
import recorded from "./recorded/demo-session.json";
import redecided from "./recorded/qs3-redecided-design.json";
import untergasser from "./recorded/untergasser-design-proposals.json";
import { StageSummary } from "./summary";

const demo = recorded.proposals as unknown as Proposal[];
afterEach(cleanup);

describe("StageSummary", () => {
  it("says what the accepted design proposals give, not what is pending or rejected", () => {
    render(<StageSummary stage="design" proposals={demo} />);
    expect(screen.getByText(/Built-in design “vermeulen_expression_defined”/)).toBeTruthy();
    expect(screen.getByText("Gene symbols")).toBeTruthy();
    // The one recorded contradicted role was rejected: it does not count.
    const accepted = demo.filter(
      (p) => p.kind === "design.well_role" && p.status === "accepted",
    ).length;
    expect(screen.getByText("Sample types").nextElementSibling!.textContent).toMatch(
      new RegExp(`${accepted}`),
    );
  });

  it("counts sample types from a session's accepted roles", () => {
    const all = untergasser.proposals as unknown as Proposal[];
    render(<StageSummary stage="design" proposals={all} />);
    const std = all.filter(
      (p) => p.kind === "design.well_role" && p.status === "accepted" && p.payload.role === "std",
    ).length;
    expect(screen.getByText("Sample types").nextElementSibling!.textContent).toContain(
      `Standard ${std}`,
    );
  });

  it("says the design in force when a person changed the groups and the comparison", () => {
    // A real QuantStudio 3 export decided twice: DNI vs DSI first, then five groups of the
    // lab's own names against "IL-6/ctrl". The engine reads the latest decision of each item.
    const all = redecided.proposals as unknown as Proposal[];
    expect(
      all.filter((p) => p.kind === "design.comparison" && p.status === "accepted").length,
    ).toBe(2);
    render(<StageSummary stage="design" proposals={all} />);
    expect(screen.getByText("Comparison").nextElementSibling!.textContent).toBe(
      "“LPS + inhibitor” compared with “IL-6/ctrl” (fold change = LPS + inhibitor relative to IL-6/ctrl)",
    );
    const groups = screen.getByText("Groups").nextElementSibling!.textContent!;
    for (const g of ["LPS + inhibitor", "IL-6/ctrl", "Day 3 (50 µM)", "KO#2", "α-syn"]) {
      expect(groups).toContain(`“${g}”: 4 samples`);
    }
    expect(groups).not.toContain("DNI");
  });

  it("says which rule calls a well amplified", () => {
    render(<StageSummary stage="curves" proposals={demo} />);
    expect(screen.getByText(/A well counts as amplified by LinRegPCR's call/)).toBeTruthy();
  });
});

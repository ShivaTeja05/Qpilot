// Recorded from the real API (see ./recorded/README.md and src/ui/proposal/recorded/README.md).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import type { Proposal } from "@/lib/vocab";
import proposals from "@/ui/proposal/recorded/untergasser-design-proposals.json";
import { DesignNeeds } from "./DesignNeeds";
import { comparisonState, concerns } from "./logic";
import plate from "./recorded/untergasser-plate.json";
import session from "./recorded/untergasser-session.json";

const all = proposals.proposals as unknown as Proposal[];
const wells = (plate as unknown as Schemas["PlateView"]).wells;
const design = session.stages.find((s) => s.stage === "design")!;

afterEach(cleanup);

describe("which wells a proposal is about", () => {
  it("outlines every well of the samples in a dilution series", () => {
    const series = all.find((p) => p.kind === "design.dilution_series")!;
    const samples = Object.keys(series.payload.samples as Record<string, unknown>);
    const lit = wells.filter((w) => concerns(series, w));
    expect(lit.length).toBeGreaterThan(0);
    expect(lit.every((w) => samples.includes(w.sample))).toBe(true);
    expect(wells.filter((w) => samples.includes(w.sample))).toHaveLength(lit.length);
  });

  it("outlines only its own sample's wells for a sample role", () => {
    const role = all.find(
      (p) => p.kind === "design.well_role" && wells.some((w) => w.sample === p.subject),
    )!;
    const lit = wells.filter((w) => concerns(role, w));
    expect(lit.length).toBeGreaterThan(0);
    expect(new Set(lit.map((w) => w.sample))).toEqual(new Set([role.subject]));
  });
});

describe("the design's blockers", () => {
  it("says what is missing and where groups can come from when none is waiting", () => {
    const open = vi.fn();
    render(
      <DesignNeeds blockers={design.blockers} proposals={all} onOpen={open} onSettings={vi.fn()} />,
    );
    for (const b of design.blockers)
      expect(screen.getByText(new RegExp(b.slice(1, 30)))).toBeTruthy();
    expect(
      screen.getByText(/No proposal for the groups or the reference genes is waiting/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open with a sample sheet" }));
    expect(open).toHaveBeenCalled();
  });

  it("offers no comparison before two groups are accepted", () => {
    expect(comparisonState(all)).toEqual({ groups: [], ready: false });
  });
});

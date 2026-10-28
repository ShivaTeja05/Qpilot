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

describe("the design's needs", () => {
  it("links every need to the control that fixes it, and says a model is optional", () => {
    const go = vi.fn();
    const needs = [
      { code: "reference", words: "no reference gene yet: mark one", where: "targets" as const },
      { code: "groups", words: "fewer than two groups", where: "samples" as const },
      { code: "engine", words: "a design error in the engine's words", where: "engine" as const },
    ];
    render(<DesignNeeds needs={needs} blockers={[]} onGo={go} />);
    expect(screen.getByText("No reference gene yet: mark one.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choose the reference genes" }));
    expect(go).toHaveBeenLastCalledWith("targets");
    fireEvent.click(screen.getByRole("button", { name: "Set the groups" }));
    expect(go).toHaveBeenLastCalledWith("samples");
    expect(screen.getByText(/A model is optional/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use a sample sheet" }));
    expect(go).toHaveBeenLastCalledWith("sheet");
    expect(screen.queryByRole("button", { name: /Model settings/ })).toBeNull();
  });

  it("falls back to the stage's blockers while the editor loads", () => {
    render(<DesignNeeds needs={undefined} blockers={design.blockers} onGo={vi.fn()} />);
    for (const b of design.blockers)
      expect(screen.getByText(new RegExp(b.slice(1, 30)))).toBeTruthy();
  });

  it("offers no comparison before two groups are accepted", () => {
    expect(comparisonState(all)).toEqual({ groups: [], ready: false });
  });
});

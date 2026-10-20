/**
 * The Prism section's logic and blocks on JSON recorded from the real API of the seeded demo
 * session (`recorded/record.py`). Expected strings are built from the recorded values with the
 * page's formatters, never typed in.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { fold, ofTotal } from "@/lib/format";
import type { Proposal, ProposalList, Workspace } from "./api";
import { PrismConsequence } from "./Consequence";
import { flowOf, projectState } from "./flow";
import sessionJson from "./recorded/session.json";
import prismJson from "./recorded/proposals-prism.json";
import roundTripJson from "./recorded/proposals-roundtrip.json";
import { cellNumber, parseCsvLine } from "./tables";

const session = sessionJson as unknown as Workspace;
const prism = prismJson as unknown as ProposalList;
const roundTrip = roundTripJson as unknown as ProposalList;

afterEach(cleanup);

describe("flow", () => {
  it("waits for the choices while they are not confirmed", () => {
    const choices = session.stages.find((s) => s.stage === "choices")!;
    const flow = flowOf(session, prism.proposals, roundTrip.proposals);
    expect(flow.choicesConfirmed).toBe(choices.confirmed);
    if (!choices.confirmed) {
      expect(flow.steps[0]!.state).toBe("current");
      expect(flow.draftBlocked).toMatch(/Confirm the analysis choices/);
      expect(flow.sendBlocked).toMatch(/Confirm the analysis choices/);
    }
  });

  it("tells a project accepted for an earlier analysis from one for this analysis", () => {
    const accepted = prism.proposals.find((p) => p.kind === "prism.project" && p.status === "accepted")!;
    const forStudy = String((accepted.payload as { study_id?: string }).study_id);
    const now = projectState(prism.proposals, session.study_id);
    if (forStudy === session.study_id) {
      expect(now.accepted?.id).toBe(accepted.id);
    } else {
      expect(now.accepted).toBeNull();
      expect(now.earlier?.id).toBe(accepted.id);
    }
    // the same proposals, read for the study the project was accepted for
    expect(projectState(prism.proposals, forStudy).accepted?.id).toBe(accepted.id);
  });

  it("allows Send only once a project for this analysis is accepted and the choices are confirmed", () => {
    const accepted = prism.proposals.find((p) => p.kind === "prism.project")!;
    const forStudy = String((accepted.payload as { study_id?: string }).study_id);
    const confirmed: Workspace = {
      ...session,
      study_id: forStudy,
      stages: session.stages.map((s) => (s.stage === "choices" ? { ...s, confirmed: true } : s)),
    };
    const flow = flowOf(confirmed, prism.proposals, roundTrip.proposals);
    expect(flow.sendBlocked).toBeNull();
    expect(flow.steps.map((s) => s.state)).toEqual(["done", "done", "current", "waiting"]);
  });
});

describe("round-trip consequence", () => {
  const exclusion = roundTrip.proposals.find((p) => p.kind === "prism.exclusion_reason") as Proposal;
  const c = exclusion.consequence as Record<string, number | number[]>;

  it("shows the gene's fold change before and after, and the conclusions it changes", () => {
    render(<PrismConsequence proposal={exclusion} />);
    expect(screen.getByText(fold(c.fc_before as number))).toBeTruthy();
    expect(screen.getByText(fold(c.fc_after as number))).toBeTruthy();
    expect(screen.getByText(ofTotal(c.n_conclusions_changed as number, c.n_genes as number))).toBeTruthy();
  });

  it("says when the consequence is out of date", () => {
    render(<PrismConsequence proposal={exclusion} stale="the decisions changed since this export." />);
    expect(screen.getByText(/Out of date/)).toBeTruthy();
  });
});

describe("tables", () => {
  it("reads quoted cells as the export writes them", () => {
    expect(parseCsvLine('Sample,"group, with comma","say ""hi"""')).toEqual(["Sample", "group, with comma", 'say "hi"']);
    expect(parseCsvLine("a,,b")).toEqual(["a", "", "b"]);
  });

  it("treats an empty cell as no value", () => {
    expect(cellNumber("")).toBeNull();
    expect(cellNumber("  ")).toBeNull();
    expect(cellNumber("nan")).toBeNull();
    expect(cellNumber("-1.5e-3")).toBe(-0.0015);
  });
});

/**
 * The Prism section's logic on JSON recorded from the real API of the seeded demo session
 * (`recorded/record.py`).
 */
import { describe, expect, it } from "vitest";
import type { ProposalList, Workspace } from "./api";
import { flowOf, projectState } from "./flow";
import sessionJson from "./recorded/session.json";
import prismJson from "./recorded/proposals-prism.json";
import roundTripJson from "./recorded/proposals-roundtrip.json";
import { cellNumber } from "./tables";

const session = sessionJson as unknown as Workspace;
const prism = prismJson as unknown as ProposalList;
const roundTrip = roundTripJson as unknown as ProposalList;

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
    const studyOf = (p: { payload: unknown }) =>
      String((p.payload as { study_id?: string }).study_id);
    const accepted = prism.proposals.filter(
      (p) => p.kind === "prism.project" && p.status === "accepted",
    );
    const now = projectState(prism.proposals, session.study_id);
    const mine = accepted.filter((p) => studyOf(p) === session.study_id);
    const others = accepted.filter((p) => studyOf(p) !== session.study_id);
    expect(now.accepted?.id ?? null).toBe(mine.at(-1)?.id ?? null);
    // an earlier analysis's project only matters while this one has none
    expect(now.earlier?.id ?? null).toBe(mine.length ? null : (others.at(-1)?.id ?? null));
    // the same proposals, read for the study each was accepted for
    for (const p of accepted) {
      const latest = accepted.filter((q) => studyOf(q) === studyOf(p)).at(-1)!;
      expect(projectState(prism.proposals, studyOf(p)).accepted?.id).toBe(latest.id);
    }
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

describe("tables", () => {
  it("treats an empty cell as no value", () => {
    expect(cellNumber("")).toBeNull();
    expect(cellNumber("  ")).toBeNull();
    expect(cellNumber("nan")).toBeNull();
    expect(cellNumber("-1.5e-3")).toBe(-0.0015);
  });
});

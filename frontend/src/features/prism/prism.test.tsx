/**
 * The Prism section's logic on JSON recorded from the real API of the seeded demo session
 * (`recorded/record.py`).
 */
import { describe, expect, it } from "vitest";
import type { PrismStatus, ProposalList, Workspace } from "./api";
import { flowOf, projectState } from "./flow";
import sessionJson from "./recorded/session.json";
import prismJson from "./recorded/proposals-prism.json";
import roundTripJson from "./recorded/proposals-roundtrip.json";
import statusJson from "./recorded/prism-status.json";
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

describe("a project accepted for an earlier analysis", () => {
  const status = statusJson as unknown as PrismStatus;
  const accepted = prism.proposals.filter(
    (p) => p.kind === "prism.project" && (p.status === "accepted" || p.status === "edited"),
  );

  it("holds when the server says its tables hold the same numbers (still current)", () => {
    const earlier = accepted.at(-1)!;
    const now = projectState(prism.proposals, "a0a0a0a0a0a0", {
      status: "accepted",
      proposal_id: earlier.id,
      genes: [],
      still_current: true,
      drafted_for: String((earlier.payload as { study_id?: string }).study_id),
      checking: false,
    });
    expect(now.accepted?.id).toBe(earlier.id);
    expect(now.stillCurrent).toBe(true);
    expect(now.earlier).toBeNull();
    const confirmed: Workspace = {
      ...session,
      study_id: "a0a0a0a0a0a0",
      stages: session.stages.map((s) => (s.stage === "choices" ? { ...s, confirmed: true } : s)),
    };
    const flow = flowOf(confirmed, prism.proposals, roundTrip.proposals, {
      ...status,
      project: {
        ...status.project,
        status: "accepted",
        proposal_id: earlier.id,
        still_current: true,
      },
    });
    expect(flow.sendBlocked).toBeNull();
    expect(flow.steps[1]!.detail).toBe("Still current: the same numbers");
  });

  it("asks for a new draft when the numbers changed, and waits while the server compares", () => {
    const changed = projectState(prism.proposals, "a0a0a0a0a0a0", {
      status: "none",
      genes: [],
      still_current: false,
      checking: false,
    });
    expect(changed.accepted).toBeNull();
    expect(changed.earlier?.id).toBe(accepted.at(-1)!.id);
    const checking = projectState(prism.proposals, "a0a0a0a0a0a0", {
      status: "none",
      genes: [],
      still_current: false,
      checking: true,
    });
    expect(checking.checking).toBe(true);
    const flow = flowOf(
      {
        ...session,
        study_id: "a0a0a0a0a0a0",
        stages: session.stages.map((s) => (s.stage === "choices" ? { ...s, confirmed: true } : s)),
      },
      prism.proposals,
      roundTrip.proposals,
      { ...status, project: { status: "none", genes: [], still_current: false, checking: true } },
    );
    expect(flow.sendBlocked).toMatch(/Checking whether the project accepted earlier/);
    expect(flow.steps[1]!.detail).toBe("Checking the earlier project");
  });

  it("matches the recorded status of the seeded session", () => {
    const now = projectState(prism.proposals, session.study_id, status.project);
    expect(now.stillCurrent).toBe(Boolean(status.project.still_current));
    expect(now.accepted?.id ?? null).toBe(
      status.project.status === "accepted" ? (status.project.proposal_id ?? null) : null,
    );
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

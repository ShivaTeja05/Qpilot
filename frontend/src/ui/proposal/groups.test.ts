import { describe, expect, it } from "vitest";
import type { Schemas } from "@/api/client";
import waiting from "@/features/curves/__tests__/recorded/proposals-curves-waiting.json";
import { FOLD_MIN, refutedGroups, refutedWords, targetOf } from "./groups";

type Proposal = Schemas["Proposal"];
const proposals = (waiting as Schemas["ProposalList"]).proposals;

describe("refuted well calls fold into one line per target", () => {
  it("folds the demo's 110 refuted ALUsq calls into one group", () => {
    const groups = refutedGroups(proposals);
    expect(groups).toHaveLength(1);
    const [g] = groups;
    expect(g!.target).toBe("ALUsq(Eurogentec)");
    expect(g!.ids).toHaveLength(110);
    expect(g!.amplified).toBe(false);
    expect(g!.judge).toBe(true);
    expect(g!.note).toBe("LinRegPCR fitted a complete amplification curve in this well");
    expect(refutedWords(g!)).toBe(
      `The Curve Judge reads 110 wells of ALUsq(Eurogentec) (plate ${g!.plates[0]}) as not amplified, and the engine's check refutes every one (for each: “LinRegPCR fitted a complete amplification curve in this well”).`,
    );
  });

  it("leaves a few cards, consistent cards and decided cards alone", () => {
    const calls = proposals.filter((p) => p.kind === "curve.well_call");
    expect(refutedGroups(calls.slice(0, FOLD_MIN - 1))).toEqual([]);
    const consistent = calls.map((p): Proposal => ({
      ...p,
      check: { ...p.check, status: "consistent" },
    }));
    expect(refutedGroups(consistent)).toEqual([]);
    const decided = calls.map((p): Proposal => ({ ...p, status: "rejected" }));
    expect(refutedGroups(decided)).toEqual([]);
  });

  it("reads the target from the evidence, else the plate", () => {
    expect(
      targetOf({ subject: "A_1/B2", evidence: [{ kind: "well", ref: "x", note: "target T" }] }),
    ).toBe("T");
    expect(targetOf({ subject: "A_1/B2", evidence: [] })).toBe("A_1");
  });
});

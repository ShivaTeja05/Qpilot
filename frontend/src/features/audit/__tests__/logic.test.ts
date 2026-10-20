/** The Audit section's URL state and the what-if lab's choice checks, on the recorded audit. */
import { describe, expect, it } from "vitest";
import overview from "@/test/recorded/audit-overview.json";
import { changesKey } from "../api";
import { asSentence } from "../CannotRun";
import { scientific } from "../HowTab";
import type { AuditOverview } from "../types";
import { parsePlace, placeSegments } from "../url";
import { validChanges } from "../WhatifTab";
import { DECISION_ORDER, tierOf } from "../words";

const decisions = (overview as AuditOverview).decisions;

describe("the audit's place in the URL", () => {
  it("defaults to the Study tab", () => {
    expect(parsePlace([])).toEqual({ tab: "study", changes: {} });
    expect(parsePlace(["nonsense"])).toEqual({ tab: "study", changes: {} });
  });

  it("reads the tab and the what-if choices", () => {
    expect(parsePlace(["how"])).toEqual({ tab: "how", changes: {} });
    expect(parsePlace(["whatif", "late_cq=cq35", "refs%3DHMBS"])).toEqual({
      tab: "whatif",
      changes: { late_cq: "cq35", refs: "HMBS" },
    });
  });

  it("ignores malformed pairs and choices on other tabs", () => {
    expect(parsePlace(["whatif", "=x", "late_cq=", "nopair"]).changes).toEqual({});
    expect(parsePlace(["verify", "late_cq=cq35"]).changes).toEqual({});
  });

  it("writes choices in the decisions' order and reads them back", () => {
    const place = { tab: "whatif" as const, changes: { refs: "HMBS", efficiency: "std_curve" } };
    const segments = placeSegments(place, DECISION_ORDER);
    expect(segments).toEqual(["whatif", "efficiency=std_curve", "refs=HMBS"]);
    expect(parsePlace(segments)).toEqual(place);
    expect(placeSegments({ tab: "study", changes: {} })).toEqual([]);
  });

  it("shows an attached folder under audit/attached/<name>", () => {
    const place = { tab: "whatif" as const, changes: { late_cq: "cq35" }, attached: "benchmark" };
    const segments = placeSegments(place, DECISION_ORDER);
    expect(segments).toEqual(["attached", "benchmark", "whatif", "late_cq=cq35"]);
    expect(parsePlace(segments)).toEqual(place);
    expect(parsePlace(["attached", "benchmark"])).toEqual({
      tab: "study",
      changes: {},
      attached: "benchmark",
    });
    expect(parsePlace(["attached"])).toEqual({ tab: "study", changes: {} });
  });

  it("keys the what-if cache by the set of choices, whatever their order", () => {
    expect(changesKey({ b: "2", a: "1" })).toBe(changesKey({ a: "1", b: "2" }));
  });
});

describe("the what-if lab's choices", () => {
  it("keeps real options that differ from the plan", () => {
    const late = decisions.find((d) => d.id === "late_cq")!;
    const other = late.options.find((o) => o.id !== late.baseline)!;
    expect(validChanges(decisions, { late_cq: other.id })).toEqual({
      valid: { late_cq: other.id },
      ignored: [],
    });
  });

  it("drops a choice set to the plan and names unknown ones", () => {
    const late = decisions.find((d) => d.id === "late_cq")!;
    const { valid, ignored } = validChanges(decisions, {
      late_cq: late.baseline,
      nope: "x",
      late_cq_typo: "cq35",
      refs: "not-an-option",
    });
    expect(valid).toEqual({});
    expect(ignored).toEqual(["nope=x", "late_cq_typo=cq35", "refs=not-an-option"]);
  });

  it("knows every tier the audit uses", () => {
    for (const d of decisions) for (const o of d.options) expect(tierOf(o.tier)).toBeDefined();
  });
});

describe("words", () => {
  it("turns a service reason into a sentence", () => {
    expect(asSentence("the design has technical replicates")).toBe(
      "The design has technical replicates.",
    );
    expect(asSentence("  ")).toBeNull();
    expect(asSentence("Done.")).toBe("Done.");
  });

  it("writes tiny numbers with a power of ten", () => {
    expect(scientific(5.329070518200751e-15)).toBe("5.3 × 10⁻¹⁵");
    expect(scientific(1e-9)).toBe("1.0 × 10⁻⁹");
    expect(scientific(0)).toBe("0");
    expect(scientific(null)).toBe("—");
  });
});

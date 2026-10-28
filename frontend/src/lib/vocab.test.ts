import { describe, expect, it } from "vitest";
import { NNBSP, plateLabel, plural } from "./format";
import {
  AUDIT_DOES,
  DEFAULT_AUDIT,
  GRID_COUNT,
  auditOnly,
  decidedBy,
  deciderWords,
  describeProposal,
  listWords,
  setsBridge,
  setsLine,
  verdictDiffers,
} from "./vocab";

const s = (text: string) => text.replaceAll(" ", NNBSP);

describe("the two sets of analyses, said one way everywhere", () => {
  it("names both counts and what each one is for", () => {
    expect(setsLine({ grid: 744, reasonable: 144, full: 90396 })).toBe(
      `qPilot's choice grid is the 744 analyses qPilot checks (every combination of the options on the Decision Cards); it sets each gene's confidence level. The robustness audit is a wider re-analysis of ${s("90 396")} analyses; its verdicts count its 144 reasonable ones.`,
    );
    expect(setsLine({ grid: 744 })).toMatch(/confidence level\.$/);
    expect(setsLine({ reasonable: 144 })).toBe(
      "The robustness audit is a wider re-analysis; its verdicts count its 144 reasonable ones.",
    );
    expect(setsLine({})).toBe("");
    expect(GRID_COUNT).toBe("analyses qPilot checks");
    // never "eight decisions": the audit varies eight or nine (replicates)
    expect(AUDIT_DOES).not.toMatch(/eight|nine|\d/);
  });

  it("says what only the audit varies, and why a gene can hold in one and not the other", () => {
    expect(auditOnly()).toEqual([
      "the efficiency model",
      "how flagged wells are handled",
      "the statistical test",
    ]);
    expect(setsBridge()).toBe(
      "The audit also varies the efficiency model, how flagged wells are handled and the statistical test, which qPilot's grid does not (it tests the efficiency models only when you ask, under Results); its verdicts leave out single and paired control genes and keep the group cut-off as planned, which qPilot's grid varies. So the same gene can hold in a different share of each.",
    );
    // once qPilot's grid tests the efficiency models, the bridge no longer claims it does not
    expect(setsBridge(DEFAULT_AUDIT, { efficiencyInGrid: true })).not.toContain("efficiency");
    expect(auditOnly([...DEFAULT_AUDIT, "replicates"])).toContain(
      "how replicate wells are combined",
    );
    expect(verdictDiffers(144)).toContain("its 144 reasonable analyses");
    expect(listWords(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("one wording for who decided", () => {
  it("says you, an agent or qPilot", () => {
    expect(decidedBy("human")).toBe("Decided by you");
    expect(decidedBy("agent")).toBe("Decided by an agent");
    expect(decidedBy("system")).toBe("Decided by qPilot");
    expect(deciderWords(null)).toBe("someone");
  });
});

describe("shared formatters", () => {
  it("names a plate by its run, as the file does", () => {
    expect(plateLabel("CAMTA2_20080227")).toBe("CAMTA2_20080227");
    expect(plateLabel(" PRKACB_20080311_bis ")).toBe("PRKACB_20080311_bis");
    expect(plateLabel(null)).toBe("");
  });

  it("pluralises without '(s)'", () => {
    expect(plural(1, "target")).toBe("1 target");
    expect(plural(3, "target")).toBe("3 targets");
    expect(plural(110, "well call")).toBe("110 well calls");
  });

  it("names an exclusion from Prism without the old 'table Prism sent back'", () => {
    const text = describeProposal({
      kind: "prism.exclusion_reason",
      subject: "ODC1/2016",
      payload: { sample: "2016", gene: "ODC1", action: "exclude" },
    });
    expect(text).toBe("Exclude sample 2016 from ODC1, as it is excluded in Prism");
  });
});

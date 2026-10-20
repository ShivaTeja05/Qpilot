import { describe, expect, it } from "vitest";
import recorded from "./recorded/workspaces.json";
import {
  asSection,
  countsLine,
  sortFiles,
  stageChip,
  workspaceSection,
  type WorkspaceSummary,
} from "./workspace";

const workspaces = recorded.workspaces as WorkspaceSummary[];
const demo = workspaces.find((w) => w.is_demo)!;
const fresh = workspaces.find((w) => !w.is_demo)!;

describe("sortFiles", () => {
  it("takes the first RDML file and the first sheet, and names the rest", () => {
    const files = [
      { name: "notes.pdf" },
      { name: "run.RDML" },
      { name: "samples.xlsx" },
      { name: "other.xml" },
      { name: "b.csv" },
    ];
    const sorted = sortFiles(files);
    expect(sorted.rdml?.name).toBe("run.RDML");
    expect(sorted.sheet?.name).toBe("samples.xlsx");
    expect(sorted.ignored.map((f) => f.name)).toEqual(["notes.pdf", "other.xml", "b.csv"]);
  });

  it("accepts an .xml export as the RDML file and a .csv sheet", () => {
    const sorted = sortFiles([{ name: "sheet.csv" }, { name: "export.xml" }]);
    expect(sorted.rdml?.name).toBe("export.xml");
    expect(sorted.sheet?.name).toBe("sheet.csv");
    expect(sorted.ignored).toEqual([]);
  });
});

describe("workspaceSection", () => {
  it("opens a workspace whose results may be shown on Results", () => {
    expect(demo.results_visible).toBe(true);
    expect(workspaceSection(demo)).toBe("results");
  });

  it("opens a session with the design still to confirm on Design", () => {
    expect(fresh.results_visible).toBe(false);
    expect(workspaceSection(fresh)).toBe("design");
  });

  it("opens Curves once the design is confirmed but results are still blind", () => {
    const stages = demo.stages.map((s) => (s.stage === "curves" ? { ...s, confirmed: false } : s));
    expect(workspaceSection({ ...demo, stages, results_visible: false })).toBe("curves");
  });

  it("opens a study analysed outside Studio on Results", () => {
    expect(workspaceSection({ kind: "study", results_visible: true, stages: [] })).toBe("results");
  });
});

describe("asSection", () => {
  it("keeps a known section and falls back on an unknown one", () => {
    expect(asSection("curves", "design")).toBe("curves");
    expect(asSection("nowhere", "design")).toBe("design");
    expect(asSection(null, "results")).toBe("results");
  });
});

describe("countsLine", () => {
  it("says plates, samples and genes from the summary", () => {
    expect(countsLine(demo)).toBe(
      `${demo.n_plates} plates · ${demo.n_samples} samples · ${demo.n_genes} genes`,
    );
    expect(countsLine(fresh)).toBe(`1 plate · ${fresh.n_samples} samples · ${fresh.n_genes} genes`);
  });

  it("leaves out counts the summary does not have", () => {
    expect(countsLine({ n_plates: null, n_samples: 3, n_genes: null })).toBe("3 samples");
  });
});

describe("stageChip", () => {
  it("says each stage's state in words", () => {
    const byStage = Object.fromEntries(demo.stages.map((s) => [s.stage, stageChip(s)]));
    expect(byStage.design).toMatchObject({
      label: "Design",
      state: "confirmed",
      words: "Design: confirmed",
    });
    expect(byStage.choices?.state).toBe("open");
    expect(byStage.prism).toMatchObject({
      label: "Prism draft",
      state: "closed",
      words: "Prism draft: not open yet",
    });
  });

  it("counts proposals waiting", () => {
    const design = fresh.stages.find((s) => s.stage === "design")!;
    expect(stageChip({ ...design, pending: 2 })).toMatchObject({
      state: "waiting",
      words: "Design: 2 proposals waiting",
    });
  });
});

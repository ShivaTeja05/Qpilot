import { describe, expect, it } from "vitest";
import recorded from "./recorded/workspaces.json";
import {
  MAX_FILES,
  addFiles,
  asSection,
  countsLine,
  guessFile,
  isAccepted,
  planUpload,
  refusalReason,
  stageChip,
  workspaceSection,
  type WorkspaceSummary,
} from "./workspace";

const workspaces = recorded.workspaces as WorkspaceSummary[];
const demo = workspaces.find((w) => w.is_demo)!;
const fresh = workspaces.find((w) => !w.is_demo)!;

describe("addFiles", () => {
  const f = (name: string, size = 10) => ({ name, size });

  it("keeps RDML files, exports and sheets, and names back what the server does not take", () => {
    const picked = addFiles(
      [],
      [f("run.RDML"), f("run1 -  Quantification Cq Results.csv"), f("notes.pdf"), f("run.pcrd")],
    );
    expect(picked.files.map((x) => x.name)).toEqual([
      "run.RDML",
      "run1 -  Quantification Cq Results.csv",
    ]);
    expect(picked.ignored.map((i) => i.file.name)).toEqual(["notes.pdf", "run.pcrd"]);
    expect(picked.ignored[0]!.reason).toMatch(/qPilot opens RDML files and instrument exports/);
    expect(picked.ignored[1]!.reason).toMatch(/CFX Manager project: export it with Export/);
  });

  it("keeps the same file once and stops at 64 files", () => {
    const first = addFiles([], [f("a.csv"), f("a.csv")]);
    expect(first.files).toHaveLength(1);
    const many = Array.from({ length: MAX_FILES + 2 }, (_, i) => f(`plate${i}.txt`));
    const picked = addFiles(first.files, many);
    expect(picked.files).toHaveLength(MAX_FILES);
    expect(picked.ignored).toHaveLength(3);
    expect(picked.ignored[0]!.reason).toMatch(/at most 64 files/);
  });
});

describe("planUpload", () => {
  const f = (name: string) => ({ name });

  it("sends one RDML file (and a sheet next to it) in the rdml and sheet fields, as before", () => {
    const rdml = f("run.rdml");
    expect(planUpload([rdml], null)).toEqual({ mode: "rdml", rdml, sheet: null });
    const sheet = f("samples.xlsx");
    expect(planUpload([sheet, rdml], null)).toEqual({ mode: "rdml", rdml, sheet });
    const added = f("design.csv");
    expect(planUpload([rdml], added)).toEqual({ mode: "rdml", rdml, sheet: added });
  });

  it("sends an export set, and anything else, as files for the server to sort", () => {
    const set = [
      f("run1 -  Quantification Amplification Results_SYBR.csv"),
      f("run1 -  Quantification Cq Results.csv"),
      f("samples.csv"),
    ];
    expect(planUpload(set, null)).toEqual({ mode: "files", files: set, sheet: null });
    const one = [f("export.txt")];
    expect(planUpload(one, null)).toEqual({ mode: "files", files: one, sheet: null });
    const two = [f("a.rdml"), f("b.rdml")];
    expect(planUpload(two, null)?.mode).toBe("files"); // the server says why
    expect(planUpload([], null)).toBeNull();
  });
});

describe("guessFile", () => {
  it("names a CFX export set's sheets, with the dye", () => {
    expect(guessFile("run1 -  Quantification Amplification Results_SYBR.csv")).toEqual({
      kind: "export",
      label: "CFX amplification curves (SYBR)",
    });
    expect(guessFile("run1 -  Quantification Cq Results_0.csv").label).toBe("CFX Cq results");
    expect(guessFile("run1 - Run Information.csv").label).toBe("CFX run information");
    expect(guessFile("run1 -  End Point Results_SYBR.csv").label).toBe(
      "CFX sheet qPilot does not read",
    );
  });

  it("names QuantStudio sections, RDML files, text exports and tables", () => {
    expect(guessFile("2023-11-14_Cov2_Amplification Data_20240422.csv").label).toBe(
      "QuantStudio amplification data",
    );
    expect(guessFile("sample_setup.txt").label).toBe("QuantStudio sample setup");
    expect(guessFile("results.txt").label).toBe("Results table");
    expect(guessFile("plate.lc96p")).toEqual({ kind: "rdml", label: "RDML file" });
    expect(guessFile("CP1.txt")).toEqual({ kind: "export", label: "Text export" });
    expect(guessFile("samples.xlsx").kind).toBe("table");
  });
});

describe("refusalReason and isAccepted", () => {
  it("accepts what the server keeps and says how to export a project file", () => {
    for (const name of ["a.rdml", "a.xml", "a.csv", "a.tsv", "a.txt", "a.xlsx", "a.lc96p"]) {
      expect(isAccepted(name)).toBe(true);
    }
    expect(isAccepted("a.eds")).toBe(false);
    expect(refusalReason("run.eds")).toMatch(/QuantStudio experiment: export Results/);
    expect(refusalReason("old.xls")).toMatch(/save it as .xlsx or .csv/);
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

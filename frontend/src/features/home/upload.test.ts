import { describe, expect, it } from "vitest";
import { openForm } from "./upload";

const file = (name: string) => new File(["x"], name);

describe("openForm", () => {
  it("sends one RDML file and its sheet in the rdml and sheet fields", () => {
    const form = openForm({ rdml: file("run.rdml"), sheet: file("s.csv"), sentence: " KO vs WT " });
    expect((form.get("rdml") as File).name).toBe("run.rdml");
    expect((form.get("sheet") as File).name).toBe("s.csv");
    expect(form.get("sentence")).toBe("KO vs WT");
    expect(form.getAll("files")).toEqual([]);
  });

  it("sends an export set as files, each by its own name, and never an rdml field", () => {
    const set = [file("run1 - Quantification Cq Results.csv"), file("run1 - Run Information.csv")];
    const form = openForm({ files: set, rdml: file("ignored.rdml"), sentence: "" });
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(set.map((f) => f.name));
    expect(form.get("rdml")).toBeNull();
    expect(form.get("sentence")).toBeNull();
  });
});

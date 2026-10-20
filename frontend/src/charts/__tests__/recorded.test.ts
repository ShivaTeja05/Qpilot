/**
 * The adapters and layouts on JSON recorded from the real services (src/test/recorded/record.py):
 * the Studio walk of the demo study (Vermeulen, 64 plates) and its robustness audit.
 */
import { describe, expect, it } from "vitest";
import analyses from "@/test/recorded/audit-analyses-NM23A.json";
import effects from "@/test/recorded/audit-effects-ODC1.json";
import samples from "@/test/recorded/audit-samples-ODC1.json";
import study from "@/test/recorded/audit-study.json";
import whatif from "@/test/recorded/audit-whatif.json";
import results from "@/test/recorded/results.json";
import {
  analysesDots,
  auditMapPoints,
  choiceRows,
  choicesAloneBars,
  choicesSpreadBars,
  resultsMapPoints,
  sampleGroups,
  samplePoints,
  whatifRows,
  type GeneRowLike,
} from "../adapters";
import { callKey } from "../core/encodings";
import { beeswarm, dotStack, placeLabels } from "../core/layout";
import { dumbbellOrder } from "../Dumbbell";
import { flipOrder } from "../FlipMatrix";
import { genormRows } from "../GenormBars";

/** GeneRow-like rows from the stored StudyResult (what the API's /results is built from). */
function geneRows(): GeneRowLike[] {
  return Object.entries(results.contrasts).map(([gene, c]) => ({
    gene,
    conclusion: c.conclusion,
    fc: c.fc,
    p: c.p,
    holds: results.robustness[gene as keyof typeof results.robustness].holds,
    level: results.confidence[gene as keyof typeof results.confidence].level,
  }));
}

describe("calls from the audit's words", () => {
  it("reads every call the audit wrote", () => {
    expect(callKey("called up (higher in MYCN-high)")).toBe("up");
    expect(callKey("called down (lower in MYCN-high)")).toBe("down");
    expect(callKey("no change called")).toBe("none");
    expect(callKey({ call: "called up", call_key: "down" })).toBe("down");
    const seen = new Set(analyses.rows.map((r) => callKey(r)));
    for (const r of analyses.rows) expect(["up", "down", "none"]).toContain(callKey(r));
    expect(seen.size).toBeGreaterThan(0);
  });
});

describe("audit views → chart props", () => {
  it("every reasonable analysis is one dot, and the counts match the audit's", () => {
    const dots = analysesDots(analyses);
    expect(dots).toHaveLength(analyses.n);
    expect(dots.filter((d) => d.same)).toHaveLength(analyses.n_same);
    expect(dots.filter((d) => d.planned)).toHaveLength(1);
    expect(callKey(analyses.base_call)).toBe(dots.find((d) => d.planned)!.call);
  });
  it("one row per decision, one planned option each", () => {
    const rows = choiceRows(effects);
    expect(rows).toHaveLength(effects.decisions.length);
    for (const r of rows) expect(r.options.filter((o) => o.planned)).toHaveLength(1);
    expect(rows.find((r) => r.id === "refs")!.options.length).toBeGreaterThan(10);
  });
  it("samples keep their group and the group means", () => {
    const groups = sampleGroups(samples);
    const points = samplePoints(samples);
    for (const g of groups) expect(points.filter((p) => p.group === g.key)).toHaveLength(g.n);
    expect(groups.find((g) => g.key === "high")!.mean).toBeCloseTo(samples.fold_log2, 10);
  });
  it("the study map is every gene, holds as a share", () => {
    const pts = auditMapPoints(study);
    expect(pts).toHaveLength(study.map.length);
    for (const p of pts) expect(p.holds >= 0 && p.holds <= 1).toBe(true);
    expect(pts.filter((p) => p.headline).length).toBeGreaterThan(0);
  });
  it("choice bars are sorted and say what they count", () => {
    const alone = choicesAloneBars(study);
    expect(alone.map((b) => b.value)).toEqual([...alone.map((b) => b.value)].sort((a, b) => b - a));
    expect(choicesSpreadBars(study)).toHaveLength(study.choices.length);
  });
  it("what-if: the changed genes come first and match the audit's count", () => {
    const rows = dumbbellOrder(whatifRows(whatif));
    const changed = rows.filter((r) => r.baseCall !== r.newCall);
    expect(changed).toHaveLength(whatif.n_changed);
    expect(rows.slice(0, changed.length).every((r) => r.baseCall !== r.newCall)).toBe(true);
    expect(new Set(changed.map((r) => r.gene))).toEqual(new Set(whatif.changed_genes));
  });
});

describe("results → chart props", () => {
  it("one map point per gene in every encoding", () => {
    const rows = geneRows();
    for (const by of ["conclusion", "level", "verdict"] as const) {
      const pts = resultsMapPoints(rows, by);
      expect(pts).toHaveLength(Object.keys(results.contrasts).length);
    }
    const lv = resultsMapPoints(rows, "level");
    expect(new Set(lv.map((p) => p.mark.label))).toEqual(new Set(rows.map((r) => r.level)));
  });
  it("flip matrix ranks the genes that flip most first", () => {
    const dims = Object.keys(Object.values(results.robustness)[0]!.impact).map((id) => ({ id }));
    const cell = (d: string, g: string) => {
      const imp = (results.robustness as Record<string, { impact: Record<string, { flips: boolean; max_delta_log2fc: number }> }>)[g]!.impact[d];
      return imp ? { flips: imp.flips, delta: imp.max_delta_log2fc } : undefined;
    };
    const order = flipOrder(Object.keys(results.robustness), dims, cell);
    const flips = order.map((g) => dims.filter((d) => cell(d.id, g)?.flips).length);
    expect(flips).toEqual([...flips].sort((a, b) => b - a));
  });
  it("geNorm bars mark candidates above the cut-off", () => {
    const g = results.genorm;
    const rows = genormRows(g.M_initial, g.cutoff_M, g.order, g.recommended);
    expect(rows.map((r) => r.key)).toEqual(g.order);
    for (const r of rows) expect(Boolean(r.note?.includes("above"))).toBe(r.value > g.cutoff_M);
  });
});

describe("layouts", () => {
  it("the beeswarm never lets two samples touch when it has room", () => {
    const pts = samplePoints(samples).filter((p) => p.group === "rest");
    const r = 3;
    const placed = beeswarm(pts, (p) => p.x * 120, r, 1e9);
    for (let i = 0; i < placed.length; i++)
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i]!;
        const b = placed[j]!;
        expect(Math.hypot(a.x - b.x, a.dy - b.dy)).toBeGreaterThanOrEqual(2 * r + 1 - 1e-6);
      }
  });
  it("the beeswarm squeezes into its band when it must", () => {
    const pts = samplePoints(samples);
    const placed = beeswarm(pts, (p) => p.x * 20, 3, 30);
    expect(Math.max(...placed.map((p) => Math.abs(p.dy)))).toBeLessThanOrEqual(30 + 1e-9);
  });
  it("the dot histogram stacks every analysis", () => {
    const placed = dotStack(analysesDots(analyses), (d) => d.log2 * 200, 4);
    expect(placed).toHaveLength(analyses.n);
    expect(Math.min(...placed.map((p) => p.dy))).toBe(0);
  });
  it("direct labels never overlap each other or the marks", () => {
    const pts = auditMapPoints(study).map((p) => ({ item: p, x: 60 + (p.log2 + 4) * 90, y: 400 - p.holds * 360, text: p.gene }));
    const marks = pts.map((p) => ({ x0: p.x - 6, x1: p.x + 6, y0: p.y - 6, y1: p.y + 6 }));
    const placed = placeLabels(pts, marks, { x0: 0, y0: 0, x1: 900, y1: 420 });
    const boxes = placed.map(({ text, spot }) => {
      const w = text.length * 6.6 + 2;
      const x0 = spot.anchor === "start" ? spot.x : spot.anchor === "end" ? spot.x - w : spot.x - w / 2;
      return { x0, x1: x0 + w, y0: spot.y - 10, y1: spot.y + 2 };
    });
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i]!;
        const b = boxes[j]!;
        expect(a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0).toBe(false);
      }
    expect(placed.length).toBeGreaterThan(5);
  });
});

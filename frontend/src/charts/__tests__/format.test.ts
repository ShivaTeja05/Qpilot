import { describe, expect, it } from "vitest";
import { foldDomain, foldTickLabel, foldTicks, sideOfLine } from "../core/fold";
import { fmtCI, fmtCount, fmtFold, fmtFoldLog2, fmtFoldWords, fmtP, fmtPct, fmtShare } from "../core/format";

const N = " ";

describe("numbers as the page writes them (docs/app.md §5)", () => {
  it("folds: two decimals, a few significant digits when tiny, whole when huge", () => {
    expect(fmtFold(3.5904)).toBe("3.59×");
    expect(fmtFold(0.5712)).toBe("0.57×");
    expect(fmtFold(1)).toBe("1.00×");
    expect(fmtFold(0.00423)).toBe("0.0042×");
    expect(fmtFold(123.4)).toBe("123×");
    expect(fmtFold(0)).toBe("–");
    expect(fmtFold(Number.NaN)).toBe("–");
    expect(fmtFoldLog2(1)).toBe("2.00×");
    expect(fmtFoldWords(-1)).toBe("2.00× lower");
    expect(fmtFoldWords(Math.log2(3.32))).toBe("3.32× higher");
  });
  it("confidence intervals and p-values", () => {
    expect(fmtCI([2.4213, 5.333])).toBe("[2.42–5.33]");
    expect(fmtP(0.0031)).toBe("0.0031");
    expect(fmtP(0.0234)).toBe("0.023");
    expect(fmtP(0.41)).toBe("0.41");
    expect(fmtP(3.4e-13)).toBe(`<${N}0.001`);
  });
  it("shares and counts", () => {
    expect(fmtShare(0.6451)).toBe(`65${N}%`);
    expect(fmtPct(48)).toBe(`48${N}%`);
    expect(fmtCount(24576)).toBe(`24${N}576`);
    expect(fmtCount(90396)).toBe(`90${N}396`);
    expect(fmtCount(1745)).toBe("1745");
    expect(fmtCount(1234567)).toBe(`1${N}234${N}567`);
  });
});

describe("the fold axis", () => {
  it("labels whole log2 steps in ×", () => {
    expect([-4, -3, -2, -1, 0, 1, 2, 5].map(foldTickLabel)).toEqual(["1/16×", "1/8×", "¼×", "½×", "1×", "2×", "4×", "32×"]);
  });
  it("always shows 1× and both call lines", () => {
    const [lo, hi] = foldDomain([1.4, 1.9], 1);
    expect(lo).toBeLessThan(-1);
    expect(hi).toBeGreaterThan(1.9);
    const [lo2, hi2] = foldDomain([0.2], 0);
    expect(lo2).toBeLessThan(0);
    expect(hi2).toBeGreaterThan(0.2);
  });
  it("thins ticks so labels never crowd", () => {
    const dense = foldTicks(-6, 6, 10, 44);
    const gaps = dense.slice(1).map((t, i) => (t.log2 - dense[i]!.log2) * 10);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(44);
    expect(foldTicks(-2, 2, 100).map((t) => t.label)).toEqual(["¼×", "½×", "1×", "2×", "4×"]);
  });
  it("says which side of the call lines a fold is on", () => {
    expect(sideOfLine(1.2, 1)).toBe("up");
    expect(sideOfLine(-1, 1)).toBe("down");
    expect(sideOfLine(0.4, 1)).toBe("between");
  });
});

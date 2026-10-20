import { describe, expect, it } from "vitest";
import { compareWells, parseWell, plateShape, rectangle, rowLetters, wellLabel } from "../geometry";
import { numericDomain, position } from "../layers";

describe("well labels", () => {
  it("round-trips labels and positions, past row Z", () => {
    expect(parseWell("A1")).toEqual({ row: 0, column: 0 });
    expect(parseWell("P24")).toEqual({ row: 15, column: 23 });
    expect(parseWell("aa3")).toEqual({ row: 26, column: 2 });
    expect(rowLetters(25)).toBe("Z");
    expect(rowLetters(26)).toBe("AA");
    expect(wellLabel(26, 2)).toBe("AA3");
    for (let r = 0; r < 40; r += 1)
      expect(parseWell(wellLabel(r, 5))).toEqual({ row: r, column: 5 });
  });

  it("refuses what is not a plate label", () => {
    expect(parseWell("1A")).toBeNull();
    expect(parseWell("A0")).toBeNull();
    expect(parseWell("well 3")).toBeNull();
  });

  it("orders wells by row, then column", () => {
    expect(["B1", "A10", "A2", "A1"].sort(compareWells)).toEqual(["A1", "A2", "A10", "B1"]);
  });

  it("selects a rectangle in either direction", () => {
    expect(rectangle({ row: 1, column: 2 }, { row: 0, column: 1 })).toEqual([
      "A2",
      "A3",
      "B2",
      "B3",
    ]);
  });
});

describe("plate shape", () => {
  it("is the smallest standard plate that holds the wells", () => {
    expect(plateShape([{ row: 7, column: 11 }])).toEqual({ rows: 8, columns: 12 });
    expect(plateShape([{ row: 8, column: 0 }])).toEqual({ rows: 16, columns: 24 });
    expect(plateShape([{ row: 0, column: 30 }])).toEqual({ rows: 1, columns: 31 });
    expect(plateShape([], { rows: 16, columns: 24 })).toEqual({ rows: 16, columns: 24 });
  });
});

describe("numeric scale", () => {
  it("uses the full range for few wells and clips the 2 % tails for many", () => {
    const few = numericDomain([3, null, 1, 2]);
    expect(few).toMatchObject({ lo: 1, hi: 3, clippedLo: false, clippedHi: false, n: 3 });
    const many = numericDomain(Array.from({ length: 101 }, (_, i) => i));
    expect(many!.lo).toBeCloseTo(2);
    expect(many!.hi).toBeCloseTo(98);
    expect(many!.clippedLo && many!.clippedHi).toBe(true);
    expect(position(many!, 200)).toBe(1);
    expect(numericDomain([null, undefined, Number.NaN])).toBeNull();
  });
});

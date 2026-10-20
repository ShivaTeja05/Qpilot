import { describe, expect, it } from "vitest";
import {
  NNBSP,
  bytes,
  ci,
  count,
  duration,
  fixed,
  fold,
  foldFromLog2,
  ofTotal,
  pValue,
  percent,
  plural,
  relativeTime,
  shortHash,
} from "./format";

const s = (text: string) => text.replaceAll(" ", NNBSP);

describe("fold", () => {
  it("writes two decimals from 1 up", () => {
    expect(fold(3.5901)).toBe("3.59×");
    expect(fold(1)).toBe("1.00×");
    expect(fold(12.345)).toBe("12.35×");
  });
  it("writes two significant digits below 1", () => {
    expect(fold(0.5712)).toBe("0.57×");
    expect(fold(0.0343)).toBe("0.034×");
  });
  it("groups large folds and refuses non-positive or missing values", () => {
    expect(fold(1234.5)).toBe(s("1 234.50×"));
    expect(fold(0)).toBe("—");
    expect(fold(null)).toBe("—");
    expect(fold(Number.NaN)).toBe("—");
  });
  it("reads log2 values", () => {
    expect(foldFromLog2(1)).toBe("2.00×");
    expect(foldFromLog2(-1)).toBe("0.50×");
  });
});

describe("ci", () => {
  it("uses brackets and an en dash", () => {
    expect(ci(2.4212, 5.3349)).toBe("[2.42–5.33]");
    expect(ci(0.31, 0.9)).toBe("[0.31–0.90]");
    expect(ci(undefined, 2)).toBe("—");
  });
});

describe("pValue", () => {
  it("says < 0.001 for very small values", () => {
    expect(pValue(0.0004)).toBe(s("< 0.001"));
    expect(pValue(0)).toBe(s("< 0.001"));
  });
  it("writes three decimals below 0.1 and two above", () => {
    expect(pValue(0.0031)).toBe("0.003");
    expect(pValue(0.0432)).toBe("0.043");
    expect(pValue(0.43)).toBe("0.43");
  });
  it("never rounds across 0.05", () => {
    expect(pValue(0.0496)).toBe("0.0496");
    expect(pValue(0.04996)).toBe("0.04996");
    expect(pValue(0.0504)).toBe("0.050");
  });
  it("handles the ends and missing values", () => {
    expect(pValue(0.999)).toBe("1.00");
    expect(pValue(null)).toBe("—");
    expect(pValue(-1)).toBe("—");
  });
});

describe("percent", () => {
  it("writes a share of analyses with a space before the sign", () => {
    expect(percent(0.645)).toBe(s("65 %"));
    expect(percent(0)).toBe(s("0 %"));
    expect(percent(1)).toBe(s("100 %"));
  });
  it("never rounds to the ends", () => {
    expect(percent(0.996)).toBe(s("> 99 %"));
    expect(percent(0.003)).toBe(s("< 1 %"));
  });
});

describe("counts", () => {
  it("groups digits with narrow no-break spaces", () => {
    expect(count(24576)).toBe(s("24 576"));
    expect(count(90396)).toBe(s("90 396"));
    expect(count(1571)).toBe(s("1 571"));
    expect(count(7)).toBe("7");
    expect(count(-1200)).toBe(s("−1 200"));
  });
  it("writes fixed decimals and plurals", () => {
    expect(fixed(-0.001, 2)).toBe("0.00");
    expect(fixed(24.318, 1)).toBe("24.3");
    expect(ofTotal(120, 186)).toBe("120 of 186");
    expect(plural(1, "plate")).toBe("1 plate");
    expect(plural(64, "plate")).toBe("64 plates");
  });
});

describe("time and size", () => {
  const now = Date.parse("2026-10-20T12:00:00Z");
  it("writes relative times", () => {
    expect(relativeTime(now - 10_000, now)).toBe("just now");
    expect(relativeTime(now - 5 * 60_000, now)).toBe(`5${NNBSP}min ago`);
    expect(relativeTime((now - 2 * 3_600_000) / 1000, now)).toBe(`2${NNBSP}h ago`);
    expect(relativeTime(now - 30 * 3_600_000, now)).toBe("yesterday");
    expect(relativeTime(new Date(now - 3 * 86_400_000).toISOString(), now)).toBe(`3${NNBSP}d ago`);
    expect(relativeTime(null, now)).toBe("—");
  });
  it("writes durations and sizes", () => {
    expect(duration(8.2)).toBe(s("8 s"));
    expect(duration(72)).toBe(`1${NNBSP}min 12${NNBSP}s`);
    expect(duration(120)).toBe(s("2 min"));
    expect(duration(7500)).toBe(`2${NNBSP}h 5${NNBSP}min`);
    expect(bytes(6_985_790)).toBe(s("6.7 MB"));
    expect(bytes(12)).toBe(s("12 B"));
  });
  it("shortens hashes", () => {
    expect(shortHash("3f2a9c1b77aa")).toBe("3f2a9c1b");
    expect(shortHash("3f2a9c1b77aa", 4)).toBe("3f2a");
    expect(shortHash(null)).toBe("—");
  });
});

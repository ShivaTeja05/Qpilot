import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { fixed } from "@/lib/format";
import { curveSeries, curvesOf } from "../adapters";
import { CurveViewer } from "../CurveViewer";
import { align, curvesSummary } from "../data";
import standard from "./recorded/curve-CDH5_20080305-N14.json";
import disputed from "./recorded/curve-CDH5_20080305-E1.json";

// uPlot draws on a canvas, which jsdom does not have: record what it was given instead.
const made: { opts: { scales: { y: { distr: number } } }; data: unknown[] }[] = [];
vi.mock("uplot", () => {
  class FakePlot {
    static pxRatio = 1;
    width = 600;
    constructor(opts: never, data: unknown[]) {
      made.push({ opts, data });
    }
    setSize() {}
    destroy() {}
  }
  return { default: FakePlot };
});

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(() => {
  cleanup();
  made.length = 0;
});

const n14 = standard as unknown as Schemas["CurveView"];
const e1 = disputed as unknown as Schemas["CurveView"];

describe("curve series from the API", () => {
  it("puts the well in focus with its Cq and baseline, and its replicates as context", () => {
    const series = curveSeries(n14);
    expect(series.map((s) => s.role)).toEqual(["focus", ...n14.replicates.map(() => "context")]);
    expect(series[0]).toMatchObject({ id: n14.key, cq: n14.cq, baseline: n14.baseline });
    expect(series[0]!.label).toBe(`${n14.well} · ${n14.sample}`);
  });

  it("leaves Cq and baseline out while the numbers are not shown", () => {
    const [focus] = curveSeries({ ...n14, numbers_shown: false });
    expect(focus!.cq).toBeNull();
    expect(focus!.baseline).toBeNull();
  });

  it("shows several chosen wells in focus without their replicates", () => {
    const series = curvesOf([n14, e1]);
    expect(series.map((s) => s.id)).toEqual([n14.key, e1.key]);
    expect(series.every((s) => s.role === "focus")).toBe(true);
  });

  it("aligns on one cycle axis and keeps positive values on the log scale", () => {
    const series = curveSeries(n14);
    const lin = align(series, "linear");
    expect(lin.x).toEqual(n14.cycle);
    expect(lin.ys[0]).toEqual(n14.fluorescence);
    const log = align(series, "log");
    const nonPositive = n14.fluorescence.filter((v) => v != null && v <= 0).length;
    expect(log.hidden[0]).toBe(nonPositive);
  });
});

describe("CurveViewer", () => {
  it("summarises the curves in words with each Cq", () => {
    const series = curveSeries(n14);
    const summary = curvesSummary(series, "Fluorescence (raw)");
    expect(summary).toContain(`Cq ${fixed(n14.cq, 1)}`);
    expect(summary).toContain(n14.replicates.length === 2 ? "2 other wells of the same sample" : "same sample");
    render(<CurveViewer series={series} yLabel="Fluorescence (raw)" label="Well N14" />);
    expect(screen.getByRole("img", { name: summary })).toBeTruthy();
    expect(made).toHaveLength(1);
    expect(made[0]!.data).toHaveLength(1 + series.length);
  });

  it("switches to a log axis", () => {
    render(<CurveViewer series={curveSeries(e1)} yLabel="Fluorescence (raw)" label="Well E1" />);
    expect(made.at(-1)!.opts.scales.y.distr).toBe(1);
    fireEvent.click(screen.getByRole("radio", { name: "Log" }));
    expect(made.at(-1)!.opts.scales.y.distr).toBe(3);
  });

  it("lists every cycle as a table, with the Cq and the baseline", () => {
    const series = curveSeries(n14);
    render(<CurveViewer series={series} yLabel="Fluorescence (raw)" label="Well N14" />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const table = screen.getByRole("table");
    // header + Cq + baseline + one row per cycle
    expect(within(table).getAllByRole("row")).toHaveLength(3 + n14.cycle.length);
    expect(within(table).getAllByRole("columnheader")).toHaveLength(1 + series.length);
  });

  it("says so when there is no curve", () => {
    render(<CurveViewer series={[]} yLabel="Fluorescence (raw)" label="Nothing" />);
    expect(screen.getByText("No curve to show.")).toBeTruthy();
  });
});

/**
 * The Trace section on JSON recorded from the real API of the seeded study (the Studio walk of
 * the demo, Vermeulen 2013): `recorded/` holds the routes' own answers (see its record.py). No
 * number is typed in: every expectation is read from a recording or formatted from it.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GeneView, StudyView, WithoutView } from "../api";
import { Dependency, drawnSamples } from "../Dependency";
import { FactText } from "../FactText";
import { FlipSet, LookFirst, Places, References, WithoutResult } from "../GenePieces";
import { readWords } from "../Overview";
import { plateWellsOf } from "../WellPanel";
import { changeWords, effectPercent, nearLine } from "../words";
import camta2Json from "./recorded/trace-CAMTA2.json";
import odc1Json from "./recorded/trace-ODC1.json";
import studyJson from "./recorded/trace-study.json";
import withoutJson from "./recorded/without-CAMTA2.json";

// uPlot draws on a canvas, which jsdom does not have (the curve viewer is not under test here).
vi.mock("uplot", () => {
  class FakePlot {
    static pxRatio = 1;
    width = 600;
    setSize() {}
    destroy() {}
  }
  return { default: FakePlot };
});

// JSON imports widen literal unions ("up") to string; the recordings are the API's own answers.
const CAMTA2 = camta2Json as unknown as GeneView;
const ODC1 = odc1Json as unknown as GeneView;
const STUDY = studyJson as unknown as StudyView;
const WITHOUT = withoutJson as unknown as WithoutView;
const WS = { key: "bc1d233e3866", kind: "session" as const };
const noop = () => undefined;
/** Testing Library folds the page's narrow no-break spaces into plain ones. */
const text = (formatted: string) => formatted.replace(/\s+/g, " ");

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    (q: string) =>
      ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        onchange: null,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("numbers as the trace writes them", () => {
  it("never rounds a fold onto the rule's line", () => {
    expect(nearLine(1.9996)).toBe("1.9996");
    expect(nearLine(2)).toBe("2.00");
    expect(nearLine(1.98)).toBe("1.98");
    const camta2 = CAMTA2.trace.call;
    expect(changeWords(camta2.log2fc)).toMatch(/-fold lower$/);
    expect(changeWords(-camta2.log2fc)).toMatch(/× higher$/);
  });

  it("says which way setting a sample aside moves the fold change", () => {
    const top = CAMTA2.trace.samples[0]!;
    const pct = 100 * (2 ** top.d_log2fc - 1);
    expect(text(effectPercent(top.d_log2fc))).toBe(
      `${pct > 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)} %`,
    );
  });

  it("shows every cited number of a sentence as the engine wrote it", () => {
    const summary = CAMTA2.texts.summary!;
    const { container } = render(<FactText text={summary} />);
    expect(container.textContent).toBe(summary.plain);
    const cited = container.querySelectorAll("span[title]");
    expect(cited.length).toBe(summary.segments.filter((s) => s.fact).length);
  });
});

describe("the dependency view", () => {
  it("draws the most influential samples of each group, with the selected and the look-first one", () => {
    const trace = CAMTA2.trace;
    const drawn = drawnSamples(trace, "2016", 960);
    expect(new Set(drawn.map((s) => s.side))).toEqual(new Set(["a", "b"]));
    expect(drawn.map((s) => s.unit)).toContain("2016");
    expect(drawn.map((s) => s.unit)).toContain(trace.look_first.unit);
    for (const side of ["a", "b"] as const) {
      const mine = drawn.filter(
        (s) => s.side === side && s.unit !== "2016" && s.unit !== trace.look_first.unit,
      );
      const ranks = trace.samples.filter((s) => s.side === side).map((s) => s.unit);
      // the rest are that group's most influential, in order
      expect(mine.map((s) => s.unit)).toEqual(
        ranks.filter((u) => mine.some((m) => m.unit === u)).slice(0, mine.length),
      );
      expect(
        ranks
          .slice(0, mine.length)
          .every(
            (u) => mine.some((m) => m.unit === u) || u === "2016" || u === trace.look_first.unit,
          ),
      ).toBe(true);
    }
  });

  it("is a labelled figure whose samples and wells are buttons", () => {
    const trace = CAMTA2.trace;
    const onSample = vi.fn();
    const onWell = vi.fn();
    const look = trace.look_first.unit!;
    render(
      <Dependency
        trace={trace}
        selected={look}
        wellKey={null}
        onSample={onSample}
        onWell={onWell}
      />,
    );
    const figure = screen.getByRole("figure");
    expect(figure.getAttribute("aria-label")).toContain(`${trace.gene}:`);
    expect(figure.getAttribute("aria-label")).toContain(
      `${trace.n_flip_single} each change the call`,
    );
    const chosen = trace.samples.find((s) => s.unit === look)!;
    const wells = screen
      .getAllByRole("button")
      .filter((b) => /^\S+ well \S+ on plate /.test(b.getAttribute("aria-label") ?? ""));
    expect(wells).toHaveLength(chosen.wells.length);
    fireEvent.click(wells[0]!);
    expect(onWell).toHaveBeenCalledWith(chosen.wells[0]);
    const other = trace.samples.find((s) => s.unit !== look && s.side === "a")!;
    const button = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("aria-label")?.startsWith(`Sample ${other.unit},`))!;
    fireEvent.keyDown(button, { key: "Enter" });
    expect(onSample).toHaveBeenCalledWith(other.unit);
    const pressed = screen.getAllByRole("button", { pressed: true });
    expect(pressed.some((b) => b.getAttribute("aria-label")?.startsWith(`Sample ${look},`))).toBe(
      true,
    );
  });

  it("has a table view with the same samples", () => {
    const trace = CAMTA2.trace;
    render(
      <Dependency trace={trace} selected={null} wellKey={null} onSample={noop} onWell={noop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const table = screen.getAllByRole("table")[0]!;
    const top = trace.samples[0]!;
    expect(within(table).getByText(top.unit)).toBeTruthy();
    expect(within(table).getAllByText(text(effectPercent(top.d_log2fc))).length).toBeGreaterThan(0);
  });
});

describe("the gene's answer", () => {
  it("names the well to look at first and opens it", () => {
    const trace = CAMTA2.trace;
    const onWell = vi.fn();
    render(<LookFirst trace={trace} texts={CAMTA2.texts} onWell={onWell} onSample={noop} />);
    expect(trace.look_first.kind).toBe("place");
    expect(screen.getByText("The well to look at first")).toBeTruthy();
    const well = trace.look_first.well!;
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`Open ${well.plate.replace(/[()]/g, "\\$&")} · ${well.well}`),
      }),
    );
    expect(onWell).toHaveBeenCalledWith(well);
    expect(screen.getByText("Changes the call")).toBeTruthy();
  });

  it("says when there is nothing unusual to look at", () => {
    const trace = ODC1.trace;
    render(<LookFirst trace={trace} texts={ODC1.texts} onWell={noop} onSample={noop} />);
    expect(trace.look_first.kind).toBe("influential");
    expect(screen.getByText("Nothing to look at")).toBeTruthy();
    expect(document.body.textContent).toContain(ODC1.texts.look_first!.plain);
  });

  it("lists the places that change the call first, the rest on request", () => {
    const trace = CAMTA2.trace;
    render(
      <Places workspace={WS} trace={trace} texts={CAMTA2.texts} onWell={noop} onSample={noop} />,
    );
    const changing = trace.places.filter((p) => p.consequence !== "changes_nothing").length;
    const shown = Math.max(3, changing);
    expect(
      screen.getAllByRole("listitem").filter((li) => li.parentElement?.tagName === "OL"),
    ).toHaveLength(shown);
    const more = trace.places.length - shown;
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`Show ${more} more`) }));
    expect(
      screen.getAllByRole("listitem").filter((li) => li.parentElement?.tagName === "OL"),
    ).toHaveLength(trace.places.length);
  });

  it("gives the fewest samples that change the call, exact or found greedily", () => {
    render(<FlipSet trace={CAMTA2.trace} texts={CAMTA2.texts} onAside={noop} onSample={noop} />);
    expect(
      screen.getByRole("heading", { name: `${CAMTA2.trace.flip.k} sample changes this call` }),
    ).toBeTruthy();
    cleanup();
    const odc1 = ODC1.trace.flip;
    expect(odc1.exact).toBe(false);
    render(<FlipSet trace={ODC1.trace} texts={ODC1.texts} onAside={noop} onSample={noop} />);
    expect(
      screen.getByRole("heading", { name: `At most ${odc1.k} samples change this call` }),
    ).toBeTruthy();
  });

  it("shows each control gene's share and where leaving it out changes the call", () => {
    const trace = CAMTA2.trace;
    render(<References trace={trace} onWell={noop} />);
    for (const r of trace.references) expect(screen.getByText(r.gene)).toBeTruthy();
    const changing = trace.references.filter((r) => r.without).length;
    expect(screen.queryAllByText(/the call changes/)).toHaveLength(changing);
  });

  it("shows the engine's call with samples set aside", () => {
    const r = WITHOUT.result;
    render(
      <WithoutResult
        workspace={WS}
        gene={r.gene}
        aside={r.units}
        query={{ data: WITHOUT, error: null, isFetching: false, refetch: noop }}
        onClear={noop}
      />,
    );
    expect(r.changes_call).toBe(true);
    expect(screen.getByText("The call changes.")).toBeTruthy();
    expect(document.body.textContent).toContain(`${r.after.n_a} vs ${r.after.n_b} samples`);
  });
});

describe("the study overview and the plate", () => {
  it("tells what reading a disagreeing control-gene well as expected does, groups held or not", () => {
    const flagged = STUDY.trace.suspects.filter((s) => s.flags.includes("reference_pull"));
    expect(flagged.length).toBeGreaterThan(0);
    for (const s of flagged) {
      const words = readWords(s);
      expect(words.startsWith("Read as its other control genes predict")).toBe(true);
      for (const c of s.read_as_expected ?? []) expect(words).toContain(c.gene);
      if (s.read_regrouped) {
        expect(words).toContain(s.read_regrouped);
        for (const c of s.read_groups_held ?? []) expect(words).toContain(c.gene);
      }
    }
  });

  it("maps the trace's wells onto the plate map", () => {
    const sample = CAMTA2.trace.samples.find((s) => s.wells.length)!;
    const mapped = plateWellsOf(sample.wells);
    expect(mapped.map((w) => w.well)).toEqual(sample.wells.map((w) => w.well));
    expect(mapped.map((w) => w.cq ?? null)).toEqual(sample.wells.map((w) => w.cq ?? null));
    expect(mapped.every((w) => w.role === "unkn")).toBe(true);
  });
});

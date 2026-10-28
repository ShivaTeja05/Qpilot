/**
 * "Your samples" without the audit: each biological unit's value from the engine, with its
 * replicate wells (GET …/genes/{gene}/units). On JSON recorded from the API (`recorded/
 * record_units.py`): the real triplicate plate (LightCycler 96, hmuY, three units per group) and
 * the demo's ODC1 (one well per unit). No number is typed in: expectations are read from the
 * recordings.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UnitChart, UnitDetail, UnitSamples } from "../UnitSamples";
import {
  carriedUnits,
  firstWell,
  samplesSource,
  unitLabel,
  wellState,
  type GeneUnits,
} from "../units";
import hmuyJson from "./recorded/units-hmuy.json";
import odc1Json from "./recorded/units-ODC1.json";

afterEach(cleanup);

// JSON imports widen literal unions ("high") to string; the recordings are the API's own answers.
const HMUY = hmuyJson as unknown as GeneUnits;
const ODC1 = odc1Json as unknown as GeneUnits;
const q = <T,>(data: T) => ({ data, error: null, isPending: false, refetch: () => undefined });

describe("which values Your samples shows", () => {
  it("the audit's own chart when it covers the gene, the engine's otherwise", () => {
    expect(samplesSource(true, false)).toBe("audit");
    expect(samplesSource(false, false)).toBe("engine");
    // an audited design with technical replicates: only the engine's values show the wells
    expect(samplesSource(true, true)).toBe("engine");
  });

  it("marks the units the audit says carry the call", () => {
    const carried = carriedUnits([
      { sample: "a", carries: true },
      { sample: "b", carries: false },
    ]);
    expect([...carried]).toEqual(["a"]);
    expect(carriedUnits(undefined).size).toBe(0);
  });
});

describe("a real plate with triplicate wells", () => {
  it("draws each unit on its own line, its wells beside it, and says how", () => {
    render(<UnitChart data={HMUY} selected={null} onSelect={vi.fn()} />);
    const figure = screen.getByRole("figure");
    expect(figure.getAttribute("aria-label")).toContain(HMUY.fold);
    expect(figure.getAttribute("aria-label")).toContain(`${HMUY.most_wells} replicate wells`);
    // one large dot per unit, one small dot per well with a value
    const wells = HMUY.points.flatMap((p) => p.wells.filter((w) => w.x != null));
    expect(wells.length).toBeGreaterThan(HMUY.points.length);
    expect(figure.querySelectorAll("circle[r='2.6']")).toHaveLength(wells.length);
    for (const line of HMUY.how) expect(screen.getByText(line)).toBeTruthy();
    expect(screen.getByText(HMUY.fold)).toBeTruthy();
    expect(screen.getByText("A replicate well")).toBeTruthy();
    expect(screen.getByText("Group mean and its 95 % CI")).toBeTruthy();
    // a confidence band per group
    expect(figure.querySelectorAll("rect[rx='3']")).toHaveLength(2);
  });

  it("the table lists every unit with its wells; a row opens the unit", () => {
    const onSelect = vi.fn();
    render(<UnitChart data={HMUY} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const rows = screen.getByRole("table").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(HMUY.points.length);
    const first = HMUY.points[0]!;
    const row = [...rows].find((r) => r.textContent?.includes(first.unit))!;
    for (const w of first.wells) expect(row.textContent).toContain(`${w.well} ${w.cq}`);
    expect(row.textContent).toContain(first.value);
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(first.unit);
  });

  it("a unit opens its wells, each with its Cq, value and how it counts, and its curve", () => {
    const point = HMUY.points.find(
      (p) => p.cq_range === Math.max(...HMUY.points.map((x) => x.cq_range ?? 0)),
    )!;
    const curve = vi.fn(() => <p>curve</p>);
    render(
      <UnitDetail point={point} data={HMUY} carries={false} curve={curve} onClose={vi.fn()} />,
    );
    const section = screen.getByRole("region", { name: `Unit ${point.unit}` });
    expect(within(section).getByText(point.value)).toBeTruthy();
    const rows = within(section).getByRole("table").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(point.wells.length);
    point.wells.forEach((w, i) => {
      expect(rows[i]!.textContent).toContain(w.well);
      expect(rows[i]!.textContent).toContain(w.cq!);
      expect(rows[i]!.textContent).toContain(w.value!);
      expect(rows[i]!.textContent).toContain(wellState(w));
    });
    expect(curve).toHaveBeenLastCalledWith(firstWell(point));
    fireEvent.click(within(rows[1]! as HTMLElement).getByRole("button", { name: "Curve" }));
    expect(curve).toHaveBeenLastCalledWith(point.wells[1]);
  });

  it("the panel shows the engine's values without any audit, and the unit picked", () => {
    const unit = HMUY.points[2]!.unit;
    render(<UnitSamples units={q(HMUY)} selected={unit} onSelect={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Your samples" })).toBeTruthy();
    expect(screen.getByRole("region", { name: `Unit ${unit}` })).toBeTruthy();
    expect(screen.getByText(`Unit ${unitLabel(HMUY.points[2]!)}`)).toBeTruthy();
  });

  it("says why when the values cannot be read", () => {
    const err = new Error("Each unit's value cannot be shown: the input file is missing.");
    render(
      <UnitSamples
        units={{ data: undefined, error: err, isPending: false, refetch: () => undefined }}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("Each unit's value could not be read")).toBeTruthy();
  });
});

describe("a study of many single-well units (the demo)", () => {
  it("is drawn as a beeswarm, one point per unit, the group intervals said under it", () => {
    expect(ODC1.replicates).toBe(false);
    const onSelect = vi.fn();
    render(<UnitChart data={ODC1} selected={null} onSelect={onSelect} />);
    for (const g of [ODC1.groups.high, ODC1.groups.rest])
      expect(screen.getByText(new RegExp(`${g.label}: mean ${g.mean_text}`))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const rows = screen.getByRole("table").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(ODC1.points.length);
    fireEvent.click(rows[0]!);
    expect(onSelect).toHaveBeenCalledTimes(1);
  }, 20_000);
});

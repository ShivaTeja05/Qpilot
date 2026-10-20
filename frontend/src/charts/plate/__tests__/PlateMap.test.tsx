import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useMemo, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { plateWells } from "../adapters";
import { PlateMap } from "../PlateMap";
import type { PlateLayer } from "../layers";
import recorded from "./recorded/plate-CDH5_20080305.json";

const view = recorded as unknown as Schemas["PlateView"];

afterEach(cleanup);

function Harness({ layer = "call", onActivate }: { layer?: PlateLayer; onActivate?: (w: string) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const wells = useMemo(() => plateWells(view), []);
  return (
    <>
      <PlateMap
        wells={wells}
        layer={layer}
        label={`Plate ${view.run.run_id}`}
        rows={view.n_rows}
        columns={view.n_cols}
        selected={selected}
        onSelectedChange={setSelected}
        onActivate={onActivate}
      />
      <output data-testid="sel">{selected.join(",")}</output>
    </>
  );
}

const cell = (label: string) => screen.getByRole("gridcell", { name: new RegExp(`^${label},`) });
const sel = () => screen.getByTestId("sel").textContent;

// 384 wells in jsdom are slow when the whole suite runs at once.
describe("PlateMap on a recorded 384-well plate", { timeout: 30_000 }, () => {
  it("draws every well, with a summary and the legend's counts", () => {
    render(<Harness />);
    const grid = screen.getByRole("grid", { name: "Plate CDH5_20080305" });
    expect(within(grid).getAllByRole("gridcell")).toHaveLength(384);
    const disagree = view.wells.filter((w) => w.disagrees).length;
    const notAmplified = view.wells.filter((w) => w.amplified === false).length;
    expect(screen.getByText(`${notAmplified} not amplified`, { exact: false })).toBeTruthy();
    expect(screen.getByText("Curve Judge disagrees").parentElement!.textContent).toBe(`Curve Judge disagrees${disagree}`);
  });

  it("says each well in words, including the Curve Judge's disagreement", () => {
    render(<Harness />);
    const disputed = view.wells.find((w) => w.disagrees)!;
    expect(cell(disputed.well).getAttribute("aria-label")).toContain("the Curve Judge disagrees");
    expect(cell(disputed.well).getAttribute("aria-label")).toContain(`sample ${disputed.sample}`);
  });

  it("selects by click, adds with ⌘-click, takes a rectangle with Shift-click", () => {
    render(<Harness />);
    fireEvent.click(cell("A1"));
    expect(sel()).toBe("A1");
    fireEvent.click(cell("A3"), { metaKey: true });
    expect(sel()).toBe("A1,A3");
    fireEvent.click(cell("A3"), { metaKey: true });
    expect(sel()).toBe("A1");
    fireEvent.click(cell("A1"));
    fireEvent.click(cell("B2"), { shiftKey: true });
    expect(sel()).toBe("A1,A2,B1,B2");
  });

  it("moves with the arrow keys, selects with Space and opens with Enter", () => {
    const onActivate = vi.fn();
    render(<Harness onActivate={onActivate} />);
    const a1 = cell("A1");
    expect(a1.tabIndex).toBe(0);
    act(() => a1.focus());
    fireEvent.keyDown(a1, { key: "ArrowRight" });
    expect(document.activeElement).toBe(cell("A2"));
    expect(cell("A2").tabIndex).toBe(0);
    expect(a1.tabIndex).toBe(-1);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(cell("B2"));
    fireEvent.keyDown(document.activeElement!, { key: " " });
    expect(sel()).toBe("B2");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight", shiftKey: true });
    expect(sel()).toBe("B2,B3");
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith("B3");
    expect(sel()).toBe("B3");
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(sel()).toBe("");
  });

  it("does not select faded wells (a gene filter)", () => {
    const wells = plateWells(view, { keep: (w) => w.well !== "A1" });
    const onChange = vi.fn();
    render(<PlateMap wells={wells} layer="cq" label="Plate" selected={[]} onSelectedChange={onChange} />);
    fireEvent.click(cell("A1"));
    expect(onChange).not.toHaveBeenCalled();
    expect(cell("A1").getAttribute("aria-disabled")).toBe("true");
  });

  it("lists the same wells as a table", () => {
    render(<Harness layer="cq" />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(385);
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("never shows a group label, even when the API sends one", () => {
    const leaked = { ...view, wells: view.wells.map((w) => ({ ...w, group: "GROUP-LABEL-SENTINEL" })) };
    const { container } = render(<PlateMap wells={plateWells(leaked)} layer="role" label="Plate" />);
    fireEvent.mouseOver(cell("A1"));
    expect(container.textContent).not.toContain("GROUP-LABEL-SENTINEL");
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    expect(container.textContent).not.toContain("GROUP-LABEL-SENTINEL");
  });

  it("shows sample types only before the curves are shown", () => {
    const blind = plateWells({ ...view, curves_shown: false });
    expect(blind.every((w) => w.cq === undefined && w.amplified === undefined && w.disagree === undefined)).toBe(true);
  });
});

// A multiplex plate recorded from the real API (LightCycler 96 bACTXY: FAM bACT, Hex X, Texas Red
// Y, Cy5 IPC in each well; see ./recorded/README.md): one entry per dye, several per well.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "@/api/client";
import { curvesByWell, plateWells } from "../adapters";
import { PlateMap } from "../PlateMap";
import recorded from "./recorded/plate-lc96-bACTXY.json";

const view = recorded as unknown as Schemas["PlateView"];

afterEach(cleanup);

const cell = (label: string) => screen.getByRole("gridcell", { name: new RegExp(`^${label},`) });

describe("a plate with several dyes per well", () => {
  it("is recorded as multiplex, one entry per dye with its name", () => {
    expect(view.multiplex).toBe(true);
    const d3 = curvesByWell(view.wells).get(`${view.run.run_id}/D3`)!;
    expect(d3.map((w) => [w.target, w.dye])).toEqual([
      ["bACT", "FAM"],
      ["X", "Hex"],
      ["Y", "Texas Red"],
      ["IPC", "Cy5"],
    ]);
  });

  it("says which other curves share each well", () => {
    const wells = plateWells(view);
    const bact = wells.find((w) => w.well === "D3" && w.target === "bACT")!;
    expect(bact.dye).toBe("FAM");
    expect(bact.notes).toContain(
      "Also in this well (multiplex): X (Hex), Y (Texas Red), IPC (Cy5).",
    );
  });

  it("draws one position per well and shows the picked gene's curve there", () => {
    const { rerender } = render(
      <PlateMap wells={plateWells(view)} layer="cq" label="Plate" rows={8} columns={12} />,
    );
    expect(within(screen.getByRole("grid")).getAllByRole("gridcell")).toHaveLength(96);
    expect(cell("D3").getAttribute("aria-label")).toContain("bACT (FAM)");
    const onlyY = plateWells(view, { keep: (w) => w.target === "Y" });
    rerender(<PlateMap wells={onlyY} layer="cq" label="Plate" rows={8} columns={12} />);
    const d3 = cell("D3").getAttribute("aria-label")!;
    expect(d3).toContain("Y (Texas Red)");
    expect(d3).not.toContain("filtered out");
    // a gene not measured in a well leaves that position faded (here: an empty channel)
    expect(cell("A1").getAttribute("aria-label")).toMatch(/empty|filtered out/);
  });

  it("lists every curve, all dyes, in the table view", () => {
    render(<PlateMap wells={plateWells(view)} layer="cq" label="Plate" rows={8} columns={12} />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(view.wells.length + 1);
  });
});

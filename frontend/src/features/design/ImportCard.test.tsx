// Recorded from the real API (see ./recorded/README.md): two corpus exports opened through
// POST /api/workspaces with `files`, the session frame's `capture` kept as it was served.
import { cleanup, render as rtlRender, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import { ImportCard, plateLine } from "./ImportCard";
import cfx from "./recorded/import-cfx-hsieh-gapdh.json";
import cpTable from "./recorded/import-lc480-cp-table.json";

type Capture = Schemas["CaptureSummary"];
const gapdh = cfx as Capture;
const sanger = cpTable as Capture;

afterEach(cleanup);

const render = (ui: ReactElement) => rtlRender(<TooltipProvider>{ui}</TooltipProvider>);

describe("the Imported from card", () => {
  it("names the export, the files as they were called, and what was not used", () => {
    render(<ImportCard capture={gapdh} />);
    const card = screen.getByRole("region", { name: `Imported from ${gapdh.label}` });
    for (const s of gapdh.sources) expect(card.textContent).toContain(s.name);
    expect(within(card).getByText(/not needed \(qPilot recomputes it\)/)).toBeTruthy();
    expect(card.textContent).toContain(gapdh.unused.join(", "));
    expect(within(card).getByText(gapdh.value_words)).toBeTruthy();
  });

  it("says plainly that baseline-subtracted curves weaken per-well efficiency", () => {
    expect(gapdh.rawness.verdict).toBe("baseline_subtracted");
    render(<ImportCard capture={gapdh} />);
    const note = screen.getByRole("note", { name: "Were the curves processed before export?" });
    expect(note.textContent).toContain(gapdh.rawness.title);
    expect(note.textContent).toContain("weakens LinRegPCR's per-well efficiency");
    // the raw-ness warning is the note; it is not repeated in the list
    const repeated = gapdh.warnings.find((w) => w.code === "CURVES_NOT_RAW")!;
    expect(screen.queryByText(repeated.message)).toBeNull();
    const other = gapdh.warnings.find((w) => w.code === "UNNAMED_WELLS")!;
    expect(screen.getByText(other.message)).toBeTruthy();
  });

  it("shows each plate's shape, targets, dyes and declared sample types", () => {
    const plate = gapdh.plates[0]!;
    expect(plateLine(plate)).toBe("96-well plate (8 × 12) · 96 wells · 40 cycles");
    render(<ImportCard capture={gapdh} />);
    expect(screen.getByText(plateLine(plate))).toBeTruthy();
    expect(screen.getByRole("region", { name: /^Imported from/ }).textContent).toContain(
      "Sample 96",
    );
    expect(screen.getByText(/of 96 reactions \(kept for comparison/)).toBeTruthy();
  });

  it("says a Cq table has no curves to check and lists the instrument's omitted wells", () => {
    expect(sanger.rawness.verdict).toBe("cq_only");
    render(<ImportCard capture={sanger} />);
    expect(screen.getByRole("note").textContent).toContain("There are no curves to check");
    const plate = sanger.plates[0]!;
    expect(screen.getByText(plate.vendor_omitted.join(", "))).toBeTruthy();
    expect(screen.getByText(/recorded, not applied/)).toBeTruthy();
    expect(screen.getByText(/no curves$/)).toBeTruthy();
  });

  it("renders every string from a file as text", () => {
    const hostile = '<img src=x onerror="alert(1)">.csv';
    const capture: Capture = {
      ...gapdh,
      sources: [{ ...gapdh.sources[0]!, name: hostile }],
      plates: [{ ...gapdh.plates[0]!, run_id: "<b>run</b>", targets: ["<script>x</script>"] }],
    };
    const { container } = render(<ImportCard capture={capture} />);
    expect(screen.getByText(hostile)).toBeTruthy();
    expect(screen.getByText("<b>run</b>")).toBeTruthy();
    expect(container.querySelector("img, script, b")).toBeNull();
  });

  it("puts many plates in a scroller a keyboard can reach", () => {
    const plates = Array.from({ length: 6 }, (_, i) => ({ ...gapdh.plates[0]!, run_id: `p${i}` }));
    render(<ImportCard capture={{ ...gapdh, plates }} />);
    const region = screen.getByRole("region", { name: "Plates read" });
    expect(region.tabIndex).toBe(0);
    expect(within(region).getAllByText(/^p\d$/)).toHaveLength(6);
  });

  it("shows nothing for a session opened from an RDML file", () => {
    const { container } = render(<ImportCard capture={null} />);
    expect(container.textContent).toBe("");
  });
});

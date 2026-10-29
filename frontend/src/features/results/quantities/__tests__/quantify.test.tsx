/**
 * A quantification run (purpose: quantify samples) on the API's own answers for a real
 * QuantStudio 3 wastewater plate (recorded: ./recorded/README.md): the Design page's purpose,
 * Results with the quantities as the main result and the quantity cards, a sample's wells, and
 * the sections that compare groups locked with the reason.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { EMPTY_DRAFT, type EditorView } from "@/features/design/draft";
import editorJson from "@/features/design/recorded/editor-quantify.json";
import { PurposePanel, purposeItem, purposeNow } from "@/features/design/PurposePanel";
import { QUANTIFY_REASON, sectionStates } from "@/shell/nav";
import { TooltipProvider } from "@/ui";
import type { QuantitiesView, UnitQuantity } from "../api";
import { QuantifyResults, classCounts } from "../QuantifyResults";
import { QuantitiesPanel } from "../QuantitiesPanel";
import { QuantityChanges } from "../QuantityChanges";
import { farthestWell } from "../UnitWells";
import cards from "./recorded/quantify-cards.json";
import cov2 from "./recorded/quantify-cov2.json";
import frameJson from "./recorded/quantify-frame.json";
import overview from "./recorded/quantify-quantities.json";

// uPlot (the curve viewer behind a well's "Curve") reads matchMedia when it is imported.
vi.hoisted(() => {
  const media = (q: string) => ({
    matches: false,
    media: q,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent: () => false,
  });
  Object.defineProperty(globalThis, "matchMedia", { value: media, writable: true });
  if (typeof window !== "undefined")
    Object.defineProperty(window, "matchMedia", { value: media, writable: true });
});

const editor = editorJson as unknown as EditorView;
const frame = frameJson as unknown as Schemas["WorkspaceView"];
const view = overview as unknown as QuantitiesView;
const STUDY = overview.study_id;

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function serve() {
  return vi.spyOn(api, "GET").mockImplementation(((route: string) => {
    if (route === "/api/studies/{study_id}/quantities") return ok(overview);
    if (route === "/api/studies/{study_id}/quantities/{target}") return ok(cov2);
    if (route === "/api/studies/{study_id}/cards") return ok(cards);
    return ok({});
  }) as never);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("what the study is for (Design)", () => {
  it("reads the person's purpose, with the draft over the recorded one", () => {
    expect(editor.purpose).toBe("quantify");
    expect(purposeNow(editor, EMPTY_DRAFT)).toBe("quantify");
    const back = new Map([["design.purpose\u0000purpose", purposeItem("compare")]]);
    expect(purposeNow(editor, back)).toBe("compare");
    expect(editor.needs.map((n) => n.code)).not.toContain("reference");
    expect(editor.needs.map((n) => n.code)).not.toContain("groups");
  });

  it("says what quantifying needs: standards with a quantity, no comparison", () => {
    const onDraft = vi.fn();
    wrap(<PurposePanel view={editor} draft={EMPTY_DRAFT} onDraft={onDraft} />);
    const region = screen.getByRole("region", { name: /What is this study for/ });
    expect(within(region).getByText(/No comparison and no reference gene are needed/)).toBeTruthy();
    expect(
      within(region).getByText(/5 standard samples on the plate, 5 with a quantity/),
    ).toBeTruthy();
    fireEvent.click(within(region).getByRole("radio", { name: "Compare groups" }));
    const next = onDraft.mock.calls[0]![0] as Map<string, unknown>;
    expect([...next.values()]).toEqual([purposeItem("compare")]);
  });
});

describe("Results of a quantification", () => {
  it("counts every sample result by what is reported for it", () => {
    expect(classCounts(view)).toEqual([
      { id: "quantified", words: "quantified", n: 42 },
      { id: "below_loq", words: "detected, below the limit of quantification", n: 2 },
      { id: "not_detected", words: "not detected", n: 10 },
    ]);
  });

  it("shows the quantities as the result and the card a person decides", async () => {
    serve();
    wrap(
      <QuantifyResults
        workspace={frame}
        studyId={STUDY}
        cards={{ data: cards } as never}
        rest={[]}
      />,
    );
    expect(await screen.findByText(/A quantification: no groups are compared/)).toBeTruthy();
    expect(screen.getByText(/54 sample results \(2 assays: Cov2, PMMoV\)/)).toBeTruthy();
    const changes = await screen.findByTestId("quantity-changes");
    expect(within(changes).getByText("Reports 9 sample results differently:")).toBeTruthy();
    expect(within(changes).getByText(/Show all 9/)).toBeTruthy();
    expect(
      screen.getByText(
        "1 decision could change what is reported for a sample · 1 made automatically",
      ),
    ).toBeTruthy();
  });

  it("lists what each sample is reported as, and opens its wells", async () => {
    serve();
    wrap(<QuantitiesPanel workspaceKey="ws" studyId={STUDY} quantify sid={null} />);
    const card = await screen.findByRole("region", { name: /Quantities/ });
    await within(card).findByText("Reported as");
    expect(within(card).queryByText("Group")).toBeNull(); // no groups: no group column
    fireEvent.click(within(card).getByRole("button", { name: "PR-231103-DCS-R1: its wells" }));
    const wells = within(card).getByTestId("unit-wells");
    expect(within(wells).getByText("2023-11-14_Cov2_Copy/C12")).toBeTruthy();
    expect(within(wells).getByText(/Farthest from the others/)).toBeTruthy();
  });

  it("names the well farthest from its replicates only past 2-fold", () => {
    const units = (cov2 as unknown as { units: UnitQuantity[] }).units;
    const dcs = units.find((u) => u.unit === "PR-231103-DCS-R1")!;
    expect(farthestWell(dcs)).toBe("2023-11-14_Cov2_Copy/C12");
    const north = units.find((u) => u.unit === "D-231018-NorthA")!;
    expect(farthestWell(north)).toBeNull();
  });

  it("an option that changes nothing says nothing", () => {
    const option = cards.cards[0]!.options.find((o) => o.id === "linregpcr")!;
    const { container } = wrap(<QuantityChanges option={option as never} />);
    expect(container.textContent).toBe("");
  });
});

describe("sections that compare groups", () => {
  it("are locked for a quantification, with the reason", () => {
    const states = sectionStates(frame);
    for (const id of ["audit", "trace", "claims", "prism", "planner", "gene"] as const) {
      expect(states[id].reachable).toBe(false);
      expect(states[id].lockReason).toBe(QUANTIFY_REASON);
    }
    for (const id of ["results", "gate", "report", "record"] as const)
      expect(states[id].reachable).toBe(true);
  });
});

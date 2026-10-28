/**
 * The Quantities view on the API's own answers for a real QuantStudio 3 wastewater plate
 * (recorded: ./recorded/README.md), the "detected only in" line, the number formats, and the
 * Design page's ng → copies helper.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { TooltipProvider } from "@/ui";
import { CopiesHelper, copiesWords } from "@/features/design/CopiesHelper";
import { DetectedOnlyLine } from "../DetectedOnly";
import { fmtEfficiency, fmtQuantity, fmtQuantityRange, fmtStandard } from "../format";
import { QuantitiesPanel } from "../QuantitiesPanel";
import copies from "./recorded/copies.json";
import cov2 from "./recorded/quantities-cov2.json";
import overview from "./recorded/quantities.json";

const STUDY = overview.study_id;
/** The page groups digits with narrow no-break spaces; compare with plain ones. */
const plain = (text: string) => text.replace(/\u202f/g, " ");

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
    if (route === "/api/tools/copies") return ok(copies);
    return ok({});
  }) as never);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("number formats", () => {
  it("writes quantities with three significant digits, standards with four", () => {
    expect(plain(fmtQuantity(2609.287))).toBe("2 610");
    expect(plain(fmtQuantity(56.8))).toBe("56.8");
    expect(plain(fmtQuantity(0.1186))).toBe("0.119");
    expect(plain(fmtQuantity(324833521.6))).toBe("3.25 × 10⁸");
    expect(plain(fmtQuantity(null))).toBe("—");
    expect(plain(fmtStandard(18750))).toBe("18 750");
    expect(plain(fmtStandard(1.875))).toBe("1.875");
    expect(plain(fmtStandard(100000))).toBe("100 000");
    expect(plain(fmtQuantityRange(140.2, 272.5))).toBe("140–273");
    expect(plain(fmtEfficiency(0.946))).toBe("94.6 %");
    expect(plain(copiesWords(324833521.6))).toBe("3.25 × 10⁸");
  });
});

describe("the Quantities view on a real QuantStudio 3 plate", () => {
  it("shows the standard curve's numbers and every sample's copies with its interval", async () => {
    serve();
    wrap(<QuantitiesPanel workspaceKey="ws" studyId={STUDY} />);
    const card = await screen.findByRole("region", { name: /Quantities/ });
    await within(card).findByText("−3.327 cycles per ten-fold");
    expect(within(card).getByText(/99\.8 % \(95 % CI 94\.4 %–105\.8 %\)/)).toBeTruthy();
    expect(within(card).getByText(/5 levels, 15 wells, 10 to 100 000/)).toBeTruthy();
    expect(within(card).getAllByText("≤ 10").length).toBeGreaterThan(0); // LOD at or below
    // the chart says what it shows, for screen readers
    expect(
      within(card).getAllByRole("img", { name: /Standard curve of Cov2.*slope −3\.327/ }).length,
    ).toBeGreaterThan(0);
    // DNI on 26 Oct: 195 copies (140–273), group DNI; the negative control: not detected
    const row = within(card).getByText("PR-231026-DNI-R1").closest("tr")!;
    expect(within(row).getByText("DNI")).toBeTruthy();
    expect(within(row).getByText("195")).toBeTruthy();
    expect(within(row).getByText("140–273")).toBeTruthy();
    const neg = within(card).getByText("PR-231026-NEG-R1").closest("tr")!;
    expect(within(neg).getByText(/not detected in any well/)).toBeTruthy();
    expect(within(neg).getByText(/below the limit of detection/)).toBeTruthy();
  });

  it("lists only the flagged units when asked", async () => {
    serve();
    wrap(<QuantitiesPanel workspaceKey="ws" studyId={STUDY} />);
    const card = await screen.findByRole("region", { name: /Quantities/ });
    await within(card).findByText("PR-231026-DNI-R1");
    const flagged = cov2.units.filter((u) => u.flags.length).length;
    fireEvent.click(within(card).getByRole("radio", { name: `Flagged ${flagged}` }));
    expect(within(card).queryByText("PR-231026-DNI-R1")).toBeNull();
    expect(within(card).getByText("PR-231026-NEG-R1")).toBeTruthy();
  });

  it("records the reaction input with a reason, as a person", async () => {
    serve();
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() =>
        ok({ status: "accepted", head: "h", message: "Recorded." })) as never);
    wrap(<QuantitiesPanel workspaceKey="ws" studyId={STUDY} />);
    const card = await screen.findByRole("region", { name: /Quantities/ });
    fireEvent.click(await within(card).findByRole("button", { name: "Set the reaction input…" }));
    const record = within(card).getByRole("button", { name: "Record" }) as HTMLButtonElement;
    expect(record.disabled).toBe(true); // no reason yet
    fireEvent.change(within(card).getByLabelText("µL of template per reaction"), {
      target: { value: "5" },
    });
    fireEvent.change(within(card).getByLabelText("Why (kept in the decision record)"), {
      target: { value: "5 µL of extract per well" },
    });
    fireEvent.click(record);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [string, { body: unknown }];
    expect(route).toBe("/api/studies/{study_id}/quantities/reaction");
    expect(init.body).toEqual({
      template_ul: 5,
      input_ng: null,
      unit: "copies",
      reason: "5 µL of extract per well",
    });
  });

  it("shows nothing for a study without standards", async () => {
    vi.spyOn(api, "GET").mockImplementation((() =>
      ok({ ...overview, available: false, assays: [], not_quantified: [] })) as never);
    const { container } = wrap(<QuantitiesPanel workspaceKey="ws" studyId={STUDY} />);
    await waitFor(() => expect(api.GET).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});

describe("detected only in one group", () => {
  it("says the group and its ΔCq, never a fold change", () => {
    render(
      <DetectedOnlyLine
        gene={{
          gene: "NHLH2",
          reason: "detected only in present (6 of 6 biological units)",
          detected_only: {
            group: "present",
            absent: "absent",
            n_detected: 6,
            n_group: 6,
            n_absent: 6,
            dcq: 4.21,
            dcq_sd: 0.83,
          },
        }}
      />,
    );
    const text = document.body.textContent ?? "";
    expect(text).toContain("detected only in present (6 of 6 biological units)");
    expect(text).toContain("ΔCq in present 4.21 ± 0.83 (SD)");
    expect(text).toContain("No fold change is given");
    expect(text).not.toMatch(/×/);
  });
});

describe("ng → copies on the Design page", () => {
  it("works out the copies with the engine and puts them in the top quantity", async () => {
    serve();
    const use = vi.fn();
    wrap(<CopiesHelper onUse={use} />);
    fireEvent.click(screen.getByRole("button", { name: /From ng to copies/ }));
    fireEvent.change(screen.getByLabelText("ng (or ng per µL)"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Length"), { target: { value: "3000" } });
    await screen.findByText(/= 3\.25 × 10⁸ copies/);
    fireEvent.click(screen.getByRole("button", { name: "Use as the highest quantity" }));
    expect(use).toHaveBeenCalledWith(324800000);
  });
});

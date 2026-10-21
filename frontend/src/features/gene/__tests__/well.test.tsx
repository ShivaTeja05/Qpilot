/**
 * A picked sample's well, on a curve recorded from the real API (curves' recordings:
 * src/charts/curves/__tests__/recorded). The query cache is filled with it, so nothing is fetched.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { fixed } from "@/lib/format";
import recorded from "@/charts/curves/__tests__/recorded/curve-CDH5_20080305-N14.json";
import { WellCurve } from "../WellCurve";

// uPlot draws on a canvas, which jsdom does not have.
vi.mock("uplot", () => {
  class FakePlot {
    static pxRatio = 1;
    width = 600;
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
afterEach(cleanup);

const curve = recorded as unknown as Schemas["CurveView"];
const WS = { key: "bc1d233e3866", kind: "session" as const };
const SCOPE = { key: WS.key, studyId: "e300000d4f9a", kind: WS.kind };

function renderWell(kind: "session" | "study" = "session") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["w", WS.key, "curve", `${curve.run_id}/${curve.well}`, curve.target], curve);
  return render(
    <QueryClientProvider client={qc}>
      <WellCurve
        workspace={{ ...WS, kind }}
        scope={{ ...SCOPE, kind }}
        plate={curve.run_id}
        well={curve.well}
        gene={curve.target}
      />
    </QueryClientProvider>,
  );
}

describe("a sample's well", () => {
  it("draws its curve, links it to Curves and gives LinRegPCR's numbers", () => {
    renderWell();
    expect(screen.getByRole("link", { name: /Open in Curves/ }).getAttribute("href")).toContain(
      `/curves/${curve.run_id}/${curve.well}`,
    );
    expect(screen.getByText(fixed(curve.cq, 2))).toBeTruthy();
    expect(screen.getByText(fixed(curve.efficiency, 2))).toBeTruthy();
  });

  it("says where curves come from for a study analysed outside a session", () => {
    renderWell("study");
    expect(screen.getByText(/Curves open from a Studio session/)).toBeTruthy();
  });
});

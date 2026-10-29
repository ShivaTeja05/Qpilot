/**
 * Melt curves in the page, on JSON recorded from the real route (`recorded/record.py`): a
 * LightCycler 96 file (hmuY and 16S rRNA, one product each; 60 unused wells), a CFX RDML with
 * ten assays (wells with an extra peak and with no product at the expected temperature), a file
 * without melt curves, and the Controls section of the LightCycler 96 study (G-MELT's checks).
 * No number is typed in: every expectation is read from a recording or formatted from it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import gateJson from "./recorded/gate-lc96.json";
import plateJson from "./recorded/melt-lc96-plate.json";
import lc96Json from "./recorded/melt-lc96-wells.json";
import noneJson from "./recorded/melt-none.json";
import rpaJson from "./recorded/melt-rpa-wells.json";

// The API, answered from the recordings: the view with the wells asked for, else the plate's.
const answers = vi.hoisted(() => ({ plate: null as unknown, wells: null as unknown }));
const calls = vi.hoisted(() => [] as { path: string; query: Record<string, string> }[]);
vi.mock("@/api/client", async (importActual) => {
  const actual = await importActual<typeof import("@/api/client")>();
  const answer = (path: string, init?: { params?: { query?: Record<string, string> } }) => {
    const query = init?.params?.query ?? {};
    calls.push({ path, query });
    const data = query.wells ? answers.wells : answers.plate;
    return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
  };
  return { ...actual, api: { GET: vi.fn(answer), POST: vi.fn(answer) } };
});
vi.mock("uplot", () => ({
  default: class {
    static pxRatio = 1;
    width = 600;
    setSize() {}
    destroy() {}
  },
}));

import { GatePage } from "@/features/gate/index";
import { meltWellsOf } from "@/features/gate/Melt";
import type { MeltView } from "../api";
import { MeltPanel, bandOf, meltSeries } from "../MeltPanel";
import { alignMelt, meltSummary } from "../MeltChart";
import { STATUS_TONE, STATUS_WORD, assaySentence, celsius, delta } from "../words";

const LC96 = lc96Json as unknown as MeltView;
const PLATE = plateJson as unknown as MeltView;
const RPA = rpaJson as unknown as MeltView;
const NONE = noneJson as unknown as MeltView;
const GATE = gateJson as unknown as Parameters<typeof GatePage>[0]["view"];
const BANNED = /\b(specific|confirmed|identified|valid|invalid)\b/i;
const text = (s: string) => s.replace(/\s+/g, " ");

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(() => {
  cleanup();
  calls.length = 0;
  answers.plate = null;
  answers.wells = null;
});

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook } = memoryLocation({ path: "/" });
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <Router hook={hook}>{children}</Router>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

describe("the melt calls in words", () => {
  it("has a word and a tone for every call, and never claims identity", () => {
    for (const view of [PLATE, RPA, LC96]) {
      for (const c of view.calls) {
        expect(STATUS_WORD[c.status]).toBeTruthy();
        expect(STATUS_TONE[c.status]).toBeTruthy();
        expect(c.status_text).not.toMatch(BANNED);
      }
      for (const a of view.assays) expect(a.summary).not.toMatch(BANNED);
      expect(view.caveat).toContain("does not guarantee");
    }
  });

  it("says where each assay's product melts from the recorded numbers", () => {
    const tol = PLATE.params.tm_tolerance_c;
    for (const a of PLATE.assays) {
      const s = assaySentence(a, tol);
      if (a.expected_tm == null) {
        expect(s).toContain("Only no-template controls of this target here");
      } else {
        expect(s).toContain(`The product melts at ${celsius(a.expected_tm)}`);
        expect(s).toContain(`${celsius(a.min_tm)} to ${celsius(a.max_tm)}`);
      }
    }
    expect(delta(0.04)).toBe("0.0 °C");
    expect(delta(-0.04)).toBe("0.0 °C");
    expect(delta(1.62)).toBe("+1.6 °C");
    expect(delta(-7.38)).toBe("−7.4 °C");
  });

  it("puts every well on one temperature axis and sums the chart up", () => {
    const series = meltSeries(RPA.wells);
    const { x, ys } = alignMelt(series);
    expect(ys).toHaveLength(RPA.wells.length);
    for (const [i, w] of RPA.wells.entries()) {
      expect(ys[i]!.filter((v) => v != null)).toHaveLength(w.derivative.length);
    }
    expect([...x].sort((a, b) => a - b)).toEqual(x);
    const summary = meltSummary(series, bandOf(RPA, RPA.wells));
    for (const w of RPA.wells) expect(summary).toContain(`${w.well} · ${w.sample}`);
    // wells of two assays share no band
    expect(bandOf(RPA, RPA.wells)).toBeNull();
    const one = bandOf(LC96, LC96.wells)!;
    expect(one.center).toBe(
      LC96.assays.find((a) => a.target === LC96.wells[0]!.target)!.expected_tm,
    );
  });
});

describe("the melt panel in Curves", { timeout: 30_000 }, () => {
  it("shows the chosen wells' melt curves with their calls and the plate's assays", async () => {
    answers.wells = LC96;
    answers.plate = PLATE;
    render(wrap(<MeltPanel sid={LC96.key} run={LC96.run!} wells={["A1", "A2", "A3"]} />));
    const table = await screen.findByRole("table", { name: /Melt calls/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(LC96.wells.length);
    for (const [i, w] of LC96.wells.entries()) {
      expect(text(rows[i]!.textContent!)).toContain(w.well);
      expect(text(rows[i]!.textContent!)).toContain(STATUS_WORD[w.status]);
      expect(text(rows[i]!.textContent!)).toContain(text(celsius(w.main_tm)));
    }
    expect(
      screen.getByRole("img", { name: /Melt curves \(−dF\/dT by temperature\) of 3 wells/ }),
    ).toBeTruthy();
    const assays = screen.getByRole("list", { name: "Assays on this plate" });
    expect(within(assays).getAllByRole("listitem")).toHaveLength(LC96.assays.length);
    expect(screen.getByText(/G-MELT points at no well on this plate/)).toBeTruthy();
    expect(calls.at(-1)).toEqual({
      path: "/api/sessions/{sid}/melt",
      query: { run: LC96.run, wells: "A1,A2,A3" },
    });
  });

  it("lists the wells G-MELT points at and opens them", async () => {
    answers.wells = RPA;
    answers.plate = RPA;
    const picked: string[][] = [];
    render(
      wrap(
        <MeltPanel
          sid={RPA.key}
          run={RPA.run!}
          wells={["A4"]}
          onPickWells={(w) => picked.push(w)}
        />,
      ),
    );
    const flagged = await screen.findByRole("list", { name: "Wells G-MELT points at" });
    const expected = RPA.calls.filter((c) => c.flagged);
    expect(within(flagged).getAllByRole("button")).toHaveLength(expected.length);
    fireEvent.click(within(flagged).getAllByRole("button")[0]!);
    expect(picked).toEqual([[expected[0]!.well]]);
    // an extra peak is shown with its share; a well off the product's Tm says so
    const table = screen.getByRole("table", { name: /Melt calls/ });
    const a4 = RPA.wells.find((w) => w.well === "A4")!;
    const extra = a4.peaks.find((p) => p.role === "extra")!;
    expect(text(table.textContent!)).toContain(text(celsius(extra.tm)));
    expect(text(table.textContent!)).toContain(STATUS_WORD.extra_peak);
    expect(text(table.textContent!)).toContain(STATUS_WORD.tm_off);
  });

  it("says what to export when the file has no melt curves", async () => {
    answers.plate = NONE;
    render(wrap(<MeltPanel sid="s" run={null} wells={[]} />));
    expect(await screen.findByText("No melt curves in this file")).toBeTruthy();
    expect(screen.getByText(NONE.message)).toBeTruthy();
  });
});

describe("G-MELT's checks in Controls", { timeout: 30_000 }, () => {
  it("finds a check's wells from its sample, else from the wells it flags", () => {
    const melt = GATE.evaluations.filter((e) => e.rule_id === "G-MELT");
    const sample = melt.find((e) => e.sample && e.outcome === "one_product")!;
    const wells = meltWellsOf(PLATE, sample);
    expect(wells).toEqual(
      PLATE.calls
        .filter((c) => c.sample === sample.sample && c.target === sample.target)
        .map((c) => c.well),
    );
    expect(wells.length).toBeGreaterThan(0);
    expect(meltWellsOf(undefined, sample)).toEqual([]);
  });

  it("opens a G-MELT check onto its wells' melt curves and links them to Curves", async () => {
    answers.plate = PLATE;
    answers.wells = LC96;
    const workspace = {
      key: GATE.session,
      kind: "session",
      study_id: GATE.study_id,
    } as unknown as Schemas["WorkspaceView"];
    render(wrap(<GatePage view={GATE} workspace={workspace} />));
    fireEvent.click(screen.getByRole("radio", { name: /^All/ }));
    const rows = screen.getAllByRole("button", { name: /G-MELT One product at the assay/ });
    expect(rows.length).toBe(GATE.evaluations.filter((e) => e.rule_id === "G-MELT").length);
    fireEvent.click(rows[0]!);
    expect(await screen.findByText("Their melt curves (−dF/dT)")).toBeTruthy();
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/studies/{study_id}/melt" && c.query.wells)).toBe(
        true,
      ),
    );
    const link = screen.getByRole("link", { name: "Open these wells in Curves" });
    expect(link.getAttribute("href")).toContain(`/s/${GATE.session}/curves/`);
    expect(await screen.findByRole("table", { name: /Melt calls/ })).toBeTruthy();
  });
});

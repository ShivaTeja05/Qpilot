/**
 * The numbers-and-figures exports and the Gene section's Figure panel, on recorded API answers of
 * the seeded demo study (`recorded/`, written by `recorded/record_exports.py` from a running
 * `qpilot app` with one card decided away from its recommendation): the server's JSON is served to
 * the page's own requests by a fetch stub that keeps every request. Nothing here is typed-in data.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
import { fold } from "@/lib/format";
import { TooltipProvider } from "@/ui";
import { figureAlt, GeneFigure, type FigureInfo } from "../gene/GeneFigure";
import type { ReportExported } from "./api";
import { basesWords, ExportPanel, FORMATS, formatOf } from "./ExportPanel";
import exportJson from "./recorded/export-csv.json";
import recommendedJson from "./recorded/figure-info-recommended.json";
import figureJson from "./recorded/figure-info.json";
import sessionJson from "./recorded/session.json";

const net = vi.hoisted(() => {
  const state = {
    answer: (_method: string, _path: string, _query: URLSearchParams): [number, unknown] => [
      404,
      null,
    ],
    sent: [] as { method: string; path: string; query: string; body: unknown }[],
  };
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string" && input.startsWith("/") ? `${location.origin}${input}` : input,
        init,
      );
    }
  } as typeof Request;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = request.method === "GET" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : null;
    state.sent.push({ method: request.method, path: url.pathname, query: url.search, body });
    const [status, answer] = state.answer(request.method, url.pathname, url.searchParams);
    return new Response(
      JSON.stringify(answer ?? { error: { code: "not_found", message: "No such API route." } }),
      { status: answer === null ? 404 : status, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  return state;
});

const decided = figureJson as unknown as FigureInfo;
const recommended = recommendedJson as unknown as FigureInfo;
const exported = exportJson as unknown as ReportExported;
const session = sessionJson as unknown as Schemas["WorkspaceView"];
const study = decided.study_id;
const infoRoute = `/api/studies/${study}/report/figure/info`;

function recorded(method: string, path: string, query: URLSearchParams): [number, unknown] {
  if (method === "GET" && path === infoRoute && query.get("gene") === decided.gene)
    return [200, query.get("basis") === "recommended" ? recommended : decided];
  if (method === "POST" && path === `/api/studies/${study}/report/export`)
    return [202, { job: { id: "job-1", kind: "report.export", title: "x", status: "running" } }];
  return [404, null];
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  net.sent = [];
  net.answer = recorded;
});
net.answer = recorded;

function show(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook } = memoryLocation({ path: "/" });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Router hook={hook}>{ui}</Router>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("ExportPanel: numbers and figures", () => {
  it("offers the workbook, CSV, figures and the supplement under 'Your numbers and figures'", async () => {
    show(
      <ExportPanel
        workspaceKey={session.key}
        studyId={study}
        head={decided.chain_head}
        jobs={{}}
        onJob={() => undefined}
        exports={[exported]}
      />,
    );
    const region = screen.getByRole("region", { name: "Export: numbers, figures and the report" });
    expect(region).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Your numbers and figures" })).toBeTruthy();
    for (const f of FORMATS.filter((x) => x.group === "numbers")) {
      expect(screen.getByRole("button", { name: f.action })).toBeTruthy();
    }
    // The written CSV says which analyses it holds (the recording has both).
    expect(screen.getAllByText("As decided, and the recommended analysis").length).toBeGreaterThan(
      0,
    );
    fireEvent.click(screen.getByRole("button", { name: "Write the supplement" }));
    await waitFor(() => expect(net.sent.some((s) => s.method === "POST")).toBe(true));
    const post = net.sent.find((s) => s.method === "POST")!;
    expect(post.body).toEqual({ format: "supplement", expected_head: decided.chain_head });
  });

  it("knows each export job by its server title", () => {
    expect(formatOf(exported.title)).toBe("csv");
    expect(formatOf("The journal supplement (zip)")).toBe("supplement");
    expect(formatOf("A figure per gene: SVG, PNG and source data (zip)")).toBe("figures");
    expect(formatOf("The numbers as an Excel workbook, with Trace's places to look")).toBe("xlsx");
    expect(formatOf("The study passport (one offline HTML file)")).toBe("passport");
    expect(basesWords(["as_decided"])).toBe("As decided on the Decision Cards");
    expect(basesWords([])).toBe("");
  });
});

describe("GeneFigure", () => {
  it("previews the server's SVG, shows the caption and offers SVG, PNG and CSV", async () => {
    show(<GeneFigure workspace={session} studyId={study} gene={decided.gene} />);
    const img = (await screen.findByRole("img", { name: figureAlt(decided) })) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe(
      `${decided.files.svg}&v=${decided.chain_head.slice(0, 12)}`,
    );
    expect(screen.getByText(decided.caption)).toBeTruthy();
    expect(screen.getByText(new RegExp(`^${fold(decided.fold_change)}`))).toBeTruthy();
    for (const [label, url] of [
      ["SVG editable: download the figure as SVG", decided.files.svg],
      ["PNG 300 dpi: download the figure as PNG", decided.files.png],
      ["Data CSV: download the data behind the figure", decided.files.csv],
    ] as const) {
      const link = screen.getByRole("link", { name: label });
      expect(link.getAttribute("href")).toContain(url);
      expect(link.getAttribute("href")).toContain("download=true");
    }
    expect(screen.getByRole("button", { name: "Copy caption" })).toBeTruthy();
  });

  it("switches to the recommended analysis when the choices differ", async () => {
    expect(decided.bases).toEqual(["as_decided", "recommended"]);
    show(<GeneFigure workspace={session} studyId={study} gene={decided.gene} />);
    await screen.findByRole("img", { name: figureAlt(decided) });
    fireEvent.click(screen.getByRole("radio", { name: "Recommended" }));
    await screen.findByRole("img", { name: figureAlt(recommended) });
    expect(screen.getByText(recommended.caption)).toBeTruthy();
    expect(net.sent.some((s) => s.query.includes("basis=recommended"))).toBe(true);
  });

  it("says why there is no figure", async () => {
    net.answer = () => [409, { error: { code: "no_figure", message: "No figure: no unit." } }];
    show(<GeneFigure workspace={session} studyId={study} gene={decided.gene} />);
    expect(await screen.findByText(/No figure: no unit\./)).toBeTruthy();
  });
});

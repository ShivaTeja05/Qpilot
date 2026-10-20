/**
 * The Claims section on the API's own answers for the demo study, recorded from the real server
 * (recorded/record.py): the annotated text's runs, the claim card, the summary's filter and the
 * page's check → read → open flow. No number here is typed by hand.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { api } from "@/api/client";
import { TooltipProvider } from "@/ui";
import examplesJson from "./recorded/examples.json";
import reportJson from "./recorded/report.json";
import type { ClaimExamples, ClaimsReport } from "../api";
import { Annotated } from "../Annotated";
import { ClaimCard } from "../ClaimCard";
import { SummaryBar } from "../ClaimList";
import { markerAt, ordered, runs } from "../marks";
import ClaimsSection from "../index";

const recorded = reportJson as unknown as ClaimsReport & { text: string };
const report: ClaimsReport = recorded;
const text = recorded.text;
const examples = examplesJson as unknown as ClaimExamples;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const { hook } = memoryLocation({ path: "/s/abc123abc123/claims" });
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <Router hook={hook}>{children}</Router>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

describe("the annotated text", () => {
  it("covers every character once and puts every claim's spans in runs of that claim", () => {
    const all = runs(text, report.claims);
    expect(all[0]!.start).toBe(0);
    expect(all[all.length - 1]!.end).toBe(text.length);
    for (let i = 1; i < all.length; i++) expect(all[i]!.start).toBe(all[i - 1]!.end);
    for (const claim of report.claims) {
      for (const span of claim.spans) {
        expect(text.slice(span.start, span.end)).toBe(span.written);
        const inside = all.filter((r) => r.start < span.end && span.start < r.end);
        expect(inside.every((r) => r.claims.includes(claim.id))).toBe(true);
      }
    }
  });

  it("gives each run its most serious verdict", () => {
    const severity = new Map(report.claims.map((c) => [c.id, c.severity]));
    for (const run of runs(text, report.claims)) {
      if (!run.verdict) continue;
      const worst = Math.max(...run.claims.map((id) => severity.get(id)!));
      const mine = report.claims.find((c) => c.verdict === run.verdict)!;
      expect(mine.severity).toBe(worst);
    }
  });

  it("ignores spans of another text", () => {
    expect(runs("short", report.claims).every((r) => r.claims.length === 0)).toBe(true);
  });

  it("has one keyboard mark per claim, after its words, that opens it", () => {
    const onSelect = vi.fn();
    render(
      wrap(<Annotated text={text} claims={report.claims} selected={null} onSelect={onSelect} />),
    );
    const marks = screen.getAllByRole("button", { name: /^Claim \d+/ });
    expect(marks).toHaveLength(report.claims.length);
    const first = report.claims[0]!;
    expect(markerAt(first)).toBeGreaterThan(first.spans[0]!.start);
    fireEvent.click(marks[0]!);
    expect(onSelect).toHaveBeenCalledWith(first.id);
    expect(marks[0]!.getAttribute("aria-label")).toContain(first.verdict_label);
  });
});

describe("the claim card and the summary", () => {
  it("says the verdict in words, cites facts with their source and offers the corrected sentence", () => {
    const claim = report.claims.find((c) => c.verdict === "choices" && c.kind === "gene")!;
    const onReplace = vi.fn();
    render(
      wrap(
        <ClaimCard
          text={text}
          claim={claim}
          position={1}
          total={report.claims.length}
          links={{ gene: "/s/abc123abc123/gene/X" }}
          canReplace
          onReplace={onReplace}
          onMove={() => {}}
        />,
      ),
    );
    const card = screen.getByRole("article");
    expect(within(card).getAllByText(claim.verdict_label).length).toBeGreaterThan(0);
    const seg = claim.checks.flatMap((c) => c.text.segments).find((x) => x.fact)!;
    const cited = within(card).getAllByText(seg.text)[0]!;
    expect(cited.getAttribute("title")).toMatch(/^(From|Computed|Quoted)/);
    const region = within(card).getByRole("region", { name: "A sentence the record supports" });
    expect(region.textContent).toContain(claim.suggestion!.plain);
    fireEvent.click(within(card).getByRole("button", { name: "Put it in place of mine" }));
    expect(onReplace).toHaveBeenCalled();
    expect(within(card).getByRole("link", { name: `See ${claim.gene}` })).toBeTruthy();
  });

  it("filters by verdict with counts the API gives", () => {
    const onFilter = vi.fn();
    render(wrap(<SummaryBar report={report} filter={null} onFilter={onFilter} />));
    const line = screen.getByText("claims supported", { exact: false }).parentElement!;
    expect(line.textContent).toContain(
      `${report.summary.supported} of ${report.summary.n} claims supported`,
    );
    const contradicted = screen.getByRole("button", { name: /Contradicted/ });
    expect(contradicted.textContent).toContain(String(report.summary.counts.contradicted));
    fireEvent.click(contradicted);
    expect(onFilter).toHaveBeenCalledWith("contradicted");
  });

  it("orders the most serious claims first", () => {
    const list = ordered(report.claims, "severity").map((c) => c.severity);
    expect(list).toEqual([...list].sort((a, b) => b - a));
  });
});

describe("the page", { timeout: 30_000 }, () => {
  it("checks the example paragraph and opens the most serious claim", async () => {
    vi.spyOn(api, "GET").mockImplementation(((path: string) => {
      if (path === "/api/studies/{study_id}/claims/examples")
        return Promise.resolve({ data: examples, response: new Response() });
      if (path === "/api/system")
        return Promise.resolve({
          data: { model: { available: false, local: true } },
          response: new Response(),
        });
      return Promise.resolve({
        error: { error: { code: "not_found", message: "x" } },
        response: new Response(null, { status: 404 }),
      });
    }) as unknown as typeof api.GET);
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() =>
        Promise.resolve({ data: report, response: new Response() })) as unknown as typeof api.POST);
    const workspace = { key: "abc123abc123", kind: "session", study_id: report.study_id } as never;
    render(wrap(<ClaimsSection workspace={workspace} rest={[]} />));
    const tryIt = await screen.findByRole("button", { name: "Try an example from this study" });
    await waitFor(() => expect((tryIt as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(tryIt);
    await screen.findByText("Your text, checked");
    expect(post).toHaveBeenCalledWith(
      "/api/studies/{study_id}/claims",
      expect.objectContaining({ body: { text: examples.paragraph } }),
    );
    const worst = ordered(report.claims, "severity")[0]!;
    const card = await screen.findByRole("article");
    const at = report.claims.indexOf(worst) + 1;
    expect(card.textContent).toContain(`claim ${at} of ${report.claims.length}`);
    expect(card.textContent).toContain(worst.headline.plain);
    fireEvent.click(screen.getByRole("button", { name: "Edit the text" }));
    expect((screen.getByLabelText("The text to check") as HTMLTextAreaElement).value).toBe(
      examples.paragraph,
    );
  });
});

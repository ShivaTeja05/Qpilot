import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { TooltipProvider } from "@/ui";
import type { ReportText, ReportView } from "./api";
import { Cited, citeGroups } from "./Cited";
import { MethodsPanel } from "./MethodsPanel";
import { MiqePanel } from "./MiqePanel";
import { ReviewPanel } from "./ReviewPanel";
// Recorded from GET /api/studies/e300000d4f9a/report on the seeded demo store: see recorded/README.md.
import recorded from "./recorded/report-e300000d4f9a.json";

const view = recorded as unknown as ReportView;

afterEach(cleanup);

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

describe("Cited", () => {
  it("draws each cited number with where it comes from, and every fact it cites is in the report", () => {
    const text = view.methods.paragraphs[0]!.text;
    const { container } = show(<Cited text={text} facts={view.facts} cites />);
    const cited = [...container.querySelectorAll<HTMLElement>("[data-fact]")];
    expect(cited.length).toBe(text.segments.filter((s) => s.fact).length);
    for (const el of cited) {
      const fact = view.facts[el.dataset.fact!]!;
      expect(fact).toBeDefined();
      expect(el.textContent).toBe(fact.text);
      expect(el.title).toContain(fact.path);
    }
    expect(container.textContent).toContain("[1]");
  });

  it("shows a quoted string from the study as text, never as markup", () => {
    const hostile: ReportText = {
      plain: 'reason: <img src=x onerror="alert(1)">',
      segments: [
        { text: "reason: ", fact: null, quote: false, cite: null },
        { text: '<img src=x onerror="alert(1)">', fact: null, quote: true, cite: null },
      ],
      facts: [],
    };
    const { container } = show(<Cited text={hostile} facts={view.facts} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("merges adjacent citation markers", () => {
    const curves = view.methods.paragraphs.find((p) => p.id === "curves")!.text;
    const groups = citeGroups(curves).filter((g) => g.cites);
    expect(groups.some((g) => g.cites!.length === 2)).toBe(true);
  });
});

describe("MethodsPanel", () => {
  it("offers both copies and lists the references", () => {
    show(<MethodsPanel methods={view.methods} facts={view.facts} />);
    expect(screen.getByRole("button", { name: "Copy as plain text" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy with citations" })).toBeTruthy();
    for (const p of view.methods.paragraphs) expect(screen.getByRole("heading", { name: p.title })).toBeTruthy();
    expect(screen.getAllByRole("listitem").length).toBe(view.methods.citations.length);
    expect(view.methods.with_citations).toContain("References");
  });
});

describe("MiqePanel", () => {
  it("counts the items by status and filters them", () => {
    show(<MiqePanel miqe={view.miqe} facts={view.facts} />);
    expect(screen.getByRole("img", { name: /MIQE 2.0 items by status/ })).toBeTruthy();
    const items = () => screen.getAllByRole("listitem").filter((li) => li.querySelector(".font-mono"));
    expect(items().length).toBe(view.miqe.n_items);
    fireEvent.click(screen.getByRole("radio", { name: `Not met ${view.miqe.counts.not_met}` }));
    expect(items().length).toBe(view.miqe.counts.not_met);
    for (const li of items()) expect(within(li).getByText("Not met")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: `All ${view.miqe.n_items}` }));
    fireEvent.change(screen.getByRole("textbox", { name: "Find a MIQE item" }), { target: { value: "efficiency" } });
    expect(items().length).toBeGreaterThan(0);
    expect(items().length).toBeLessThan(view.miqe.n_items);
  });
});

describe("ReviewPanel", () => {
  it("lists the findings most severe first and filters by severity", () => {
    show(<ReviewPanel review={view.review} facts={view.facts} workspace={null} />);
    const findings = () => within(screen.getByRole("list", { name: "Findings" })).getAllByRole("heading");
    expect(findings().length).toBe(view.review.findings.length);
    expect(findings()[0]!.textContent).toContain("Major");
    fireEvent.click(screen.getByRole("radio", { name: `Minor ${view.review.counts.minor}` }));
    expect(findings().length).toBe(view.review.counts.minor);
    expect(screen.getByRole("heading", { name: "What checks out" })).toBeTruthy();
  });
});

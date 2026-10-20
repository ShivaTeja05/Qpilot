/**
 * The Gene section on JSON recorded from the real services (src/test/recorded/record.py: the
 * Studio walk of the demo study and its robustness audit). No number here is typed in: each
 * expectation is read from the recording or formatted from it.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import cards from "@/test/recorded/cards.json";
import geneNM23A from "@/test/recorded/audit-gene-NM23A.json";
import geneODC1 from "@/test/recorded/audit-gene-ODC1.json";
import analysesNM23A from "@/test/recorded/audit-analyses-NM23A.json";
import effectsODC1 from "@/test/recorded/audit-effects-ODC1.json";
import labODC1 from "@/test/recorded/audit-lab-ODC1.json";
import samplesODC1 from "@/test/recorded/audit-samples-ODC1.json";
import results from "@/test/recorded/results.json";
import { TooltipProvider } from "@/ui";
import { ci, fold, ofTotal, pValue } from "@/lib/format";
import type { AuditGeneCard, AuditLab, AuditSamples, CardLike, GeneView } from "../api";
import { AuditInvite, AuditReading, OneChoice, WhatHolds, YourSamples } from "../AuditParts";
import { cardsForGene } from "../cards";
import { GeneHeader } from "../GeneHeader";
import { neighbours, resolveGene } from "../nav";
import { AssayWells, GeneCards, ImpactTable, ReferenceStability } from "../StudyParts";
import { KIND_DIMENSION } from "../words";

afterEach(cleanup);

type Gene = keyof typeof results.contrasts;
const ORDER = Object.keys(results.contrasts);
const LABELS = { hi: "MYCN-high", lo: "the rest" };
const WS = { key: "bc1d233e3866", kind: "session" as const };

/** A GeneView as the API builds it from the stored StudyResult (contrast + robustness + confidence). */
function geneView(gene: Gene): GeneView {
  const c = results.contrasts[gene];
  const r = results.robustness[gene as keyof typeof results.robustness];
  const k = results.confidence[gene as keyof typeof results.confidence];
  return {
    gene,
    conclusion: c.conclusion,
    fc: c.fc,
    ci: c.ci,
    p: c.p,
    n_hi: c.n_hi,
    n_lo: c.n_lo,
    holds: r.holds,
    n_cells: r.n_cells,
    level: k.level,
    reasons: k.reasons,
    checks: k.checks.map(({ id, passed, note }) => ({ id, passed, note })),
    impact: r.impact,
    efficiency: results.efficiency[gene as keyof typeof results.efficiency],
  };
}

const q = <T,>(data: T) => ({ data, error: null, isPending: false, refetch: () => undefined });

describe("moving between genes", () => {
  it("has no neighbour past either end, and counts from one", () => {
    const first = neighbours(ORDER, ORDER[0]!);
    expect(first.prev).toBeNull();
    expect(first.next).toBe(ORDER[1]);
    expect(first.position).toBe(1);
    const last = neighbours(ORDER, ORDER.at(-1)!);
    expect(last.next).toBeNull();
    expect(last.position).toBe(ORDER.length);
    expect(neighbours(ORDER, "not a gene").position).toBe(0);
  });

  it("matches a gene in the link to the study's spelling", () => {
    expect(resolveGene(ORDER, "odc1")).toBe("ODC1");
    expect(resolveGene(ORDER, "ODC1")).toBe("ODC1");
    expect(resolveGene(ORDER, "nothing")).toBeNull();
  });
});

describe("Decision Cards that move a gene", () => {
  it("joins the study's cards with the gene's robustness impact, flipping cards first", () => {
    for (const gene of ["NM23A", "ODC1", "AHCY"] as Gene[]) {
      const view = geneView(gene);
      const list = cardsForGene(view, cards as unknown as CardLike[]);
      const dims = cards.map((c) => KIND_DIMENSION[c.kind]).filter((d): d is string => Boolean(d && view.impact?.[d]));
      expect(list).toHaveLength(dims.length);
      const flips = list.map((c) => Boolean(c.flips));
      expect(flips).toEqual([...flips].sort((a, b) => Number(b) - Number(a)));
      for (const c of list) {
        const dim = KIND_DIMENSION[c.kind]!;
        expect(c.flips).toBe(view.impact![dim]!.flips);
        expect(c.max_delta_log2fc).toBe(view.impact![dim]!.max_delta_log2fc);
      }
    }
  });

  it("links each card to Results and says whether it can change the call", () => {
    const view = geneView("AHCY");
    const list = cardsForGene(view, cards as unknown as CardLike[]);
    render(<GeneCards workspace={WS} gene="AHCY" cards={list} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(list.length);
    expect(links[0]!.getAttribute("href")).toContain(`/results/card/${list[0]!.id}`);
    expect(screen.getAllByText("Can change the call alone")).toHaveLength(list.filter((c) => c.flips).length);
  });
});

describe("the header", () => {
  it("shows the call, fold [CI], p, n per group, the level and the audit's verdict", () => {
    const view = geneView("ODC1");
    const card = geneODC1 as unknown as AuditGeneCard;
    render(
      <TooltipProvider>
        <GeneHeader gene={view} labels={LABELS} audit={card} alpha={results.conclusion_rule.alpha} minLog2fc={results.conclusion_rule.min_log2fc} />
      </TooltipProvider>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "ODC1" })).toBeTruthy();
    expect(screen.getByText(fold(view.fc))).toBeTruthy();
    expect(screen.getByText(ci(view.ci[0], view.ci[1]))).toBeTruthy();
    // Testing Library folds the narrow no-break space in "< 0.001" into a plain space.
    expect(screen.getByText(pValue(view.p).replace(/\s+/g, " "))).toBeTruthy();
    expect(screen.getByText(card.label)).toBeTruthy();
    expect(screen.getByText(card.result.verdict_sentence)).toBeTruthy();
    expect(screen.getAllByText(new RegExp(String(view.level))).length).toBeGreaterThan(0);
    // Each reason is said once in the list and once in the (collapsed) list of every check.
    for (const reason of view.reasons ?? []) expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
  });

  it("says when the study is not audited", () => {
    render(
      <TooltipProvider>
        <GeneHeader gene={geneView("NM23A")} labels={LABELS} audit={null} />
      </TooltipProvider>,
    );
    expect(screen.getByText("Not audited yet")).toBeTruthy();
  });
});

describe("the audit's parts", () => {
  it("what holds: qPilot's share and the audit's count, with every analysis drawn", () => {
    const view = geneView("NM23A");
    render(
      <WhatHolds
        holds={view.holds}
        nCells={view.n_cells}
        analyses={q(analysesNM23A)}
        card={geneNM23A as unknown as AuditGeneCard}
        audited
        labels={LABELS}
      />,
    );
    expect(screen.getByText(ofTotal(analysesNM23A.n_same, analysesNM23A.n))).toBeTruthy();
    expect(screen.getByRole("img", { name: new RegExp(`Every reasonable analysis of NM23A`) })).toBeTruthy();
  });

  it("one choice at a time: the audit's plot, or qPilot's own table without an audit", () => {
    render(<OneChoice effects={q(effectsODC1)} labels={LABELS} fallback={null} />);
    expect(screen.getByRole("img", { name: /ODC1 at/ })).toBeTruthy();
    cleanup();
    const view = geneView("NM23A");
    render(<OneChoice effects={null} labels={LABELS} fallback={<ImpactTable impact={view.impact!} />} />);
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(Object.keys(view.impact!).length + 1);
  });

  it("your samples: clicking a sample opens it", () => {
    const onSelect = vi.fn();
    const data = samplesODC1 as unknown as AuditSamples;
    render(<YourSamples samples={q(data)} labels={LABELS} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    // Role queries over ~350 rows are slow in jsdom; the table's body rows are what count.
    const rows = screen.getByRole("table").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(data.points.length);
    fireEvent.click(rows[0]!);
    expect(onSelect).toHaveBeenCalledTimes(1);
  }, 20_000);

  it("the reading: what changes it, what it leans on, what to do", () => {
    const card = geneNM23A as unknown as AuditGeneCard;
    render(<AuditReading card={card} />);
    for (const line of [...card.leans, ...card.todo]) expect(screen.getByText(line)).toBeTruthy();
    if (!card.changes.length) expect(screen.getByText(card.no_changes ?? "No reasonable choice changes it.")).toBeTruthy();
  });

  it("assay and references from the audit's lab view", () => {
    const lab = labODC1 as unknown as AuditLab;
    render(<AssayWells lab={lab} />);
    expect(screen.queryByText("p-value, planned analysis")).toBeNull();
    for (const r of lab.rows.filter((r) => r.label.startsWith("Cq"))) expect(screen.getByText(r.value)).toBeTruthy();
    cleanup();
    render(
      <ReferenceStability
        gene="ODC1"
        genorm={results.genorm}
        used={results.design.refs_primary}
        lab={lab}
      />,
    );
    expect(screen.getByText(/normalised to the mean of 5 reference genes/)).toBeTruthy();
    expect(screen.getAllByText(/differs between groups/).length).toBeGreaterThan(0);
  });
});

describe("without an audit", () => {
  it("invites to run it", () => {
    const onRun = vi.fn();
    render(<AuditInvite workspace={WS} status={{ status: "none" }} job={null} onRun={onRun} />);
    fireEvent.click(screen.getByRole("button", { name: "Run the audit" }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("says why it cannot run, with no button", () => {
    const reason = "The design has technical replicates the audit cannot model.";
    render(<AuditInvite workspace={WS} status={{ status: "not_applicable", reason }} job={null} onRun={vi.fn()} />);
    expect(screen.getByText(reason)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run the audit" })).toBeNull();
  });
});

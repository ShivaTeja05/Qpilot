/**
 * The Gene section on JSON recorded from the real API of the seeded study (the Studio walk of
 * the demo, Vermeulen 2013): `recorded/` here holds `/results` and `/genes/{gene}` (see its
 * record.py), `src/test/recorded/` the robustness audit's views. No number is typed in: every
 * expectation is read from a recording or formatted from it.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import analysesNM23A from "@/test/recorded/audit-analyses-NM23A.json";
import auditGeneNM23A from "@/test/recorded/audit-gene-NM23A.json";
import auditGeneODC1 from "@/test/recorded/audit-gene-ODC1.json";
import effectsODC1 from "@/test/recorded/audit-effects-ODC1.json";
import labODC1 from "@/test/recorded/audit-lab-ODC1.json";
import samplesODC1 from "@/test/recorded/audit-samples-ODC1.json";
import { TooltipProvider } from "@/ui";
import { ci, fold, ofTotal, percent, pValue } from "@/lib/format";
import { effectChoiceRows, geneCardRefs, gridDots } from "../adapters";
import type { AuditAnalyses, AuditEffects, AuditGeneCard, AuditLab, AuditSamples, GeneView, ResultsView } from "../api";
import { AuditInvite, AuditReading, OneChoice, WhatHolds, YourSamples } from "../AuditParts";
import { GeneHeader } from "../GeneHeader";
import { neighbours, resolveGene } from "../nav";
import { AssayWells, GeneCards, ReferenceStability } from "../StudyParts";
import { geneSummary, groupLabels } from "../words";
import geneNM23AJson from "./recorded/gene-NM23A.json";
import geneODC1Json from "./recorded/gene-ODC1.json";
import resultsJson from "./recorded/results-view.json";

afterEach(cleanup);

// JSON imports widen literal unions ("up") to string; the recordings are the API's own answers.
const results = resultsJson as unknown as ResultsView;
const NM23A = geneNM23AJson as unknown as GeneView;
const ODC1 = geneODC1Json as unknown as GeneView;
const ORDER = results.genes.map((g) => g.gene);
const LABELS = groupLabels(results);
const WS = { key: "bc1d233e3866", kind: "session" as const };
const q = <T,>(data: T) => ({ data, error: null, isPending: false, refetch: () => undefined });
const noop = () => undefined;
/** Testing Library folds the page's narrow no-break spaces ("65 %", "< 0.001") into plain ones. */
const text = (formatted: string) => formatted.replace(/\s+/g, " ");

describe("moving between genes", () => {
  it("follows the study's order, with no neighbour past either end", () => {
    const first = neighbours(ORDER, ORDER[0]!);
    expect(first.prev).toBeNull();
    expect(first.position).toBe(1);
    const last = neighbours(ORDER, ORDER.at(-1)!);
    expect(last.next).toBeNull();
    expect(last.position).toBe(ORDER.length);
    const mid = neighbours(ORDER, "NM23A");
    expect(mid.prev).toBe(NM23A.prev_gene);
    expect(mid.next).toBe(NM23A.next_gene);
  });

  it("matches a gene in the link to the study's spelling", () => {
    expect(resolveGene(ORDER, "nm23a")).toBe("NM23A");
    expect(resolveGene(ORDER, "not a gene")).toBeNull();
  });
});

describe("qPilot's grid → the charts", () => {
  it("every analysis is one dot; the share with the planned call is the gene's robustness", () => {
    for (const view of [NM23A, ODC1]) {
      const dots = gridDots(view);
      expect(dots).toHaveLength(view.grid!.cells.length);
      expect(dots).toHaveLength(view.row.n_cells!);
      expect(dots.filter((d) => d.planned)).toHaveLength(1);
      expect(dots.filter((d) => d.same).length / dots.length).toBeCloseTo(view.row.holds!, 9);
      const planned = dots.find((d) => d.planned)!;
      expect(planned.log2).toBeCloseTo(view.row.log2fc!, 6);
      expect(planned.choices).toEqual([]);
    }
  });

  it("one decision at a time: one planned option per decision, the flips as the API says", () => {
    const rows = effectChoiceRows(NM23A);
    expect(rows).toHaveLength(NM23A.effects.filter((r) => r.options.length).length);
    for (const row of rows) {
      expect(row.options.filter((o) => o.planned)).toHaveLength(1);
      const effect = NM23A.effects.find((r) => r.dimension === row.id)!;
      expect(row.options.some((o) => o.changesCall)).toBe(effect.options.some((o) => o.flips[0]));
    }
  });
});

describe("Decision Cards that move a gene", () => {
  it("lists every card's decision for the gene, the ones that flip it first", () => {
    const refs = geneCardRefs(NM23A);
    expect(refs.length).toBeGreaterThanOrEqual(NM23A.effects.filter((r) => r.card_id).length);
    const flips = refs.map((r) => r.flips);
    expect(flips).toEqual([...flips].sort((a, b) => Number(b) - Number(a)));
    const flipping = new Set(NM23A.row.flips_by);
    for (const r of refs) {
      const dim = NM23A.effects.find((e) => e.card_id === r.id)?.dimension;
      if (dim) expect(r.flips).toBe(flipping.has(dim));
    }
  });

  it("links each card to Results and says whether it can change the call", () => {
    const refs = geneCardRefs(NM23A);
    render(<GeneCards workspace={WS} gene="NM23A" cards={refs} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(refs.length);
    expect(links[0]!.getAttribute("href")).toContain(`/results/card/${refs[0]!.id}`);
    expect(screen.getAllByText("Can change the call alone")).toHaveLength(refs.filter((c) => c.flips).length);
  });
});

describe("the header", () => {
  it("shows the call, fold [CI], p, n per group, the level with its reasons, and the verdict", () => {
    const card = auditGeneODC1 as unknown as AuditGeneCard;
    const row = ODC1.row;
    render(
      <TooltipProvider>
        <GeneHeader view={ODC1} labels={LABELS} audit={card} ruleText={results.rule.text} />
      </TooltipProvider>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "ODC1" })).toBeTruthy();
    expect(screen.getByText(fold(row.fc))).toBeTruthy();
    expect(screen.getByText(ci(row.ci[0], row.ci[1]))).toBeTruthy();
    expect(screen.getByText(text(pValue(row.p)))).toBeTruthy();
    expect(screen.getByText(`The rule: ${results.rule.text}`)).toBeTruthy();
    expect(screen.getByText(card.label)).toBeTruthy();
    expect(screen.getByText(card.result.verdict_sentence)).toBeTruthy();
    // Each reason is said once in the list and once in the (collapsed) list of every check.
    for (const reason of row.reasons ?? []) expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
  });

  it("without the audit's card, shows the verdict the results carry", () => {
    render(
      <TooltipProvider>
        <GeneHeader view={NM23A} labels={LABELS} audit={null} />
      </TooltipProvider>,
    );
    expect(NM23A.audit_verdict).toBeTruthy();
    expect(screen.queryByText("Not audited yet")).toBeNull();
  });
});

describe("what holds and one choice at a time", () => {
  it("draws qPilot's grid without an audit, the audit's analyses with one", () => {
    const dots = gridDots(NM23A);
    const same = dots.filter((d) => d.same).length;
    const onSource = vi.fn();
    const props = { gene: "NM23A", holds: NM23A.row.holds, nCells: NM23A.row.n_cells, dots, line: results.rule.min_log2fc, labels: LABELS, onSource };
    render(<WhatHolds {...props} card={null} analyses={null} source="qpilot" />);
    expect(screen.getByText(text(percent(NM23A.row.holds)))).toBeTruthy();
    expect(screen.getByRole("img", { name: new RegExp(`qPilot's grid, on the fold axis: ${text(ofTotal(same, dots.length))}`) })).toBeTruthy();
    cleanup();

    const a = analysesNM23A as unknown as AuditAnalyses;
    render(<WhatHolds {...props} card={auditGeneNM23A as unknown as AuditGeneCard} analyses={q(a)} source="audit" />);
    expect(screen.getByText(text(percent(a.n_same / a.n)))).toBeTruthy();
    expect(screen.getByText(new RegExp(`^${text(ofTotal(a.n_same, a.n))} of the audit's reasonable analyses`))).toBeTruthy();
    expect(screen.getByRole("img", { name: /reasonable analyses of NM23A on the fold axis/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "qPilot's grid" }));
    expect(onSource).toHaveBeenCalledWith("qpilot");
  }, 20_000); // 744 + 144 dots laid out in jsdom

  it("one choice at a time from qPilot's decisions, or from the audit's", () => {
    const rows = effectChoiceRows(ODC1);
    const props = { gene: "ODC1", rows, line: results.rule.min_log2fc, onSource: noop, labels: LABELS };
    render(<OneChoice {...props} effects={null} source="qpilot" />);
    expect(screen.getByRole("img", { name: /ODC1, one Decision Card choice at a time/ })).toBeTruthy();
    cleanup();
    render(<OneChoice {...props} effects={q(effectsODC1 as unknown as AuditEffects)} source="audit" />);
    expect(screen.getByRole("img", { name: /of the audit's/ })).toBeTruthy();
  });
});

describe("the audit's parts", () => {
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
    const card = auditGeneNM23A as unknown as AuditGeneCard;
    render(<AuditReading card={card} />);
    for (const line of [...card.leans, ...card.todo]) expect(screen.getByText(line)).toBeTruthy();
  });

  it("assay from the audit's lab view; reference genes from the results", () => {
    const lab = labODC1 as unknown as AuditLab;
    render(<AssayWells lab={lab} efficiency={ODC1.row.efficiency} />);
    expect(screen.queryByText("p-value, planned analysis")).toBeNull();
    for (const r of lab.rows.filter((r) => r.label.startsWith("Cq"))) expect(screen.getByText(r.value)).toBeTruthy();
    cleanup();
    render(<ReferenceStability gene="ODC1" genorm={results.references} lab={lab} />);
    expect(screen.getByText(new RegExp(`normalised to the mean of ${results.references.used.length} reference genes`))).toBeTruthy();
    expect(screen.getByRole("img", { name: /geNorm M for/ })).toBeTruthy();
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

describe("copy summary", () => {
  it("says the result, the confidence, what holds and the audit's verdict in plain text", () => {
    const card = auditGeneODC1 as unknown as AuditGeneCard;
    const row = ODC1.row;
    const summary = geneSummary({ gene: row, labels: LABELS, audit: card, studyId: results.study_id, chainHead: results.head });
    expect(summary).toContain("ODC1: called up with the planned analysis");
    expect(summary).toContain(`Fold ${fold(row.fc)} (95 % CI ${ci(row.ci[0], row.ci[1])})`);
    expect(summary).toContain(`Confidence: ${row.level}`);
    expect(summary).toContain(`Same call in ${percent(row.holds)}`);
    expect(summary).toContain(`Audit verdict: ${card.label}. ${card.result.verdict_sentence}`);
    expect(summary).toContain(`qPilot study ${results.study_id}`);
    expect(summary).not.toContain("undefined");
  });
});

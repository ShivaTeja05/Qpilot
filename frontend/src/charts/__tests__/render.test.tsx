/** Each chart renders recorded real data with a summary, answers the keyboard and has a table view. */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import analyses from "@/test/recorded/audit-analyses-NM23A.json";
import effects from "@/test/recorded/audit-effects-ODC1.json";
import overview from "@/test/recorded/audit-overview.json";
import samples from "@/test/recorded/audit-samples-ODC1.json";
import study from "@/test/recorded/audit-study.json";
import whatif from "@/test/recorded/audit-whatif.json";
import results from "@/test/recorded/results.json";
import {
  AnalysesStrip,
  Beeswarm,
  ChoiceDotPlot,
  Dumbbell,
  FlipMatrix,
  GenormBars,
  HBars,
  RobustnessMap,
  VerdictStrip,
  VERDICTS,
  analysesDots,
  auditMapPoints,
  choiceRows,
  choicesAloneBars,
  sampleGroups,
  samplePoints,
  whatifRows,
} from "..";

afterEach(cleanup);

function tableRows(): number {
  fireEvent.click(screen.getByRole("button", { name: "View as table" }));
  return within(screen.getByRole("table")).getAllByRole("row").length - 1;
}

describe("charts on recorded data", { timeout: 30_000 }, () => {
  it("robustness map: a summary, one row per gene, Enter opens the gene", () => {
    const onSelect = vi.fn();
    const points = auditMapPoints(study);
    render(
      <RobustnessMap
        points={points}
        line={study.line_log2}
        lineLabel="2× line"
        legend={[]}
        summary="Map of all genes."
        setWords="of the audit's 144 reasonable analyses"
        yLabel="Same call in the audit's reasonable set"
        onSelect={onSelect}
      />,
    );
    expect(screen.getByRole("img", { name: "Map of all genes." })).toBeTruthy();
    const group = screen.getByRole("group");
    fireEvent.keyDown(group, { key: "Home" });
    fireEvent.keyDown(group, { key: "Enter" });
    const leftmost = [...points].sort(
      (a, b) => a.log2 - b.log2 || a.gene.localeCompare(b.gene),
    )[0]!;
    expect(onSelect).toHaveBeenCalledWith(leftmost.gene);
    expect(tableRows()).toBe(points.length);
  });
  it("analyses strip: every analysis in the table", () => {
    render(
      <AnalysesStrip
        rows={analysesDots(analyses)}
        line={analyses.line_log2}
        summary="Every reasonable analysis."
      />,
    );
    expect(screen.getByRole("img", { name: "Every reasonable analysis." })).toBeTruthy();
    expect(tableRows()).toBe(analyses.n);
  });
  it("choice dot plot: every option of every decision", () => {
    render(
      <ChoiceDotPlot
        decisions={choiceRows(effects)}
        line={effects.line_log2}
        summary="One choice at a time."
      />,
    );
    expect(tableRows()).toBe(effects.decisions.reduce((n, d) => n + d.options.length, 0));
  });
  it("beeswarm: every sample, click opens it", () => {
    const onSelectSample = vi.fn();
    render(
      <Beeswarm
        groups={sampleGroups(samples)}
        points={samplePoints(samples)}
        foldText={samples.fold}
        summary="Your samples."
        onSelectSample={onSelectSample}
      />,
    );
    const group = screen.getByRole("group");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    fireEvent.keyDown(group, { key: "Enter" });
    expect(onSelectSample).toHaveBeenCalledTimes(1);
    expect(tableRows()).toBe(samples.points.length);
  });
  it("dumbbell: changed genes first", () => {
    render(<Dumbbell rows={whatifRows(whatif)} line={whatif.line_log2} summary="What if." />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const first = within(screen.getByRole("table")).getAllByRole("row")[1]!;
    expect(whatif.changed_genes).toContain(first.querySelector("td")!.textContent);
  });
  it("flip matrix, geNorm bars, spread bars", () => {
    const rob = results.robustness as Record<
      string,
      { impact: Record<string, { flips: boolean; max_delta_log2fc: number }> }
    >;
    const genes = Object.keys(rob);
    const dims = Object.keys(rob[genes[0]!]!.impact).map((id) => ({ id, label: id }));
    render(
      <FlipMatrix
        decisions={dims}
        genes={genes}
        cell={(d, g) => ({
          flips: rob[g]!.impact[d]!.flips,
          delta: rob[g]!.impact[d]!.max_delta_log2fc,
        })}
        summary="Flips."
      />,
    );
    expect(tableRows()).toBe(genes.length);
    cleanup();
    const g = results.genorm;
    render(
      <GenormBars
        m={g.M_initial}
        order={g.order}
        cutoffM={g.cutoff_M}
        v={g.V}
        cutoffV={g.cutoff_V}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
    cleanup();
    render(<HBars rows={choicesAloneBars(study)} summary="Calls changed by one choice." />);
    expect(tableRows()).toBe(study.choices.length);
  });
  it("verdict strip: counts as the audit gave them, tiles filter", () => {
    const onSelect = vi.fn();
    const counts = overview.verdicts.map((v) => ({
      verdict: v.key,
      count: v.count,
      rule: v.rule,
      label: v.label,
    }));
    render(<VerdictStrip counts={counts} onSelect={onSelect} />);
    const total = counts.reduce((n, c) => n + c.count, 0);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain(String(total));
    fireEvent.click(screen.getByRole("button", { name: new RegExp(VERDICTS.fragile.label) }));
    expect(onSelect).toHaveBeenCalledWith("fragile");
  });
});

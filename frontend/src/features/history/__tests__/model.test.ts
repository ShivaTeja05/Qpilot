/**
 * The timeline as data, on the History routes' recorded answers for the seeded demo session
 * (`recorded/`, written by `recorded/record.py`): the analysis before the Prism round trip
 * (cf49ccd72052) and the one after it (e300000d4f9a).
 */
import { describe, expect, it } from "vitest";
import type { HistoryView } from "../api";
import {
  EARLIER_ID,
  buildTrack,
  earlierStudy,
  laterStudies,
  mapPoints,
  movedGenes,
  pointsOf,
  tween,
} from "../model";
import afterJson from "../recorded/history-e300000d4f9a.json";
import beforeJson from "../recorded/history-cf49ccd72052.json";

const after = afterJson as unknown as HistoryView;
const before = beforeJson as unknown as HistoryView;

describe("the track", () => {
  it("puts the analysis this one replaced right after the Studio run that made it", () => {
    expect(earlierStudy(after)?.study_id).toBe(before.study_id);
    const track = buildTrack(after, before);
    const ids = track.map((t) => t.id);
    const made = after.studio.findIndex((m) => m.led_to === before.study_id);
    expect(made).toBeGreaterThanOrEqual(0);
    expect(ids.indexOf(EARLIER_ID)).toBe(ids.indexOf(`m${after.studio[made]!.first_seq}`) + 1);
    // every Studio run of the walk came before this analysis, then step 0 and each entry
    expect(ids.slice(-after.steps.length)).toEqual(after.steps.map((s) => `s${s.seq}`));
    expect(pointsOf(track).map((p) => p.id)).toEqual([
      EARLIER_ID,
      ...after.steps.map((s) => `s${s.seq}`),
    ]);
  });

  it("places runs after the analysis behind the step they followed, and points to the later one", () => {
    expect(earlierStudy(before)).toBeNull();
    expect(laterStudies(before).map((r) => r.study_id)).toEqual([after.study_id]);
    const track = buildTrack(before, null);
    const kinds = track.map((t) => t.kind);
    expect(kinds[kinds.length - 1]).toBe("later");
    const lastStep = track.map((t) => t.id).lastIndexOf(`s${before.steps.at(-1)!.seq}`);
    const runsAfter = before.studio.filter((m) => !m.before).map((m) => `m${m.first_seq}`);
    expect(runsAfter.length).toBeGreaterThan(0);
    for (const id of runsAfter)
      expect(track.map((t) => t.id).indexOf(id)).toBeGreaterThan(lastStep);
    expect(pointsOf(track)).toHaveLength(before.steps.length);
  });

  it("without the earlier analysis' own history, shows only this chain", () => {
    expect(pointsOf(buildTrack(after, null)).map((p) => p.kind)).toEqual(
      after.steps.map(() => "step"),
    );
  });
});

describe("the map's points", () => {
  const points = pointsOf(buildTrack(after, before));
  const earlier = points[0]!;
  const start = points[1]!;
  const from = mapPoints(earlier.analysis, earlier.genes, after.headline);
  const to = mapPoints(start.analysis, start.genes, after.headline);

  it("are every gene with a fold and a share, calls as marks, headline genes flagged", () => {
    const analysis = start.analysis!;
    expect(to).toHaveLength(
      analysis.genes.filter((g) => g.log2fc != null && g.holds != null).length,
    );
    const odc1 = to.find((p) => p.gene === "ODC1")!;
    const gene = analysis.genes[after.genes.indexOf("ODC1")]!;
    expect(odc1.log2).toBe(gene.log2fc);
    expect(odc1.holds).toBe(gene.holds);
    expect(odc1.headline).toBe(true);
    expect(odc1.mark.label).toBe("Call: Up");
  });

  it("move exactly where the round trip moved a gene (the compare's fold moves)", () => {
    expect([...movedGenes(from, to)]).toEqual(["ODC1"]);
  });

  it("glide from the earlier place to the new one, the call turning half-way", () => {
    expect(tween(from, to, 0).find((p) => p.gene === "ODC1")!.log2).toBe(
      from.find((p) => p.gene === "ODC1")!.log2,
    );
    expect(tween(from, to, 1)).toEqual(to);
    const mid = tween(from, to, 0.3).find((p) => p.gene === "ODC1")!;
    const a = from.find((p) => p.gene === "ODC1")!;
    const b = to.find((p) => p.gene === "ODC1")!;
    expect(mid.log2).toBeLessThan(Math.max(a.log2, b.log2));
    expect(mid.log2).toBeGreaterThan(Math.min(a.log2, b.log2));
    // a gene whose call changes shows the old call until half-way, then the new one
    const flipped = { ...b, mark: { ...b.mark, label: "Call: No call" } };
    expect(tween([a], [flipped], 0.1)[0]!.mark.label).toBe(a.mark.label);
    expect(tween([a], [flipped], 0.9)[0]!.mark.label).toBe("Call: No call");
  });
});

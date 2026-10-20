/**
 * The shell's routing and section states, on a frame recorded from the real API of the shell's
 * study store (a Studio walk of the demo: design and curves confirmed, an audit run):
 *
 *   curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" -H "origin: $QPILOT_API" \
 *     $QPILOT_API/api/sessions/bc1d233e3866 \
 *     | python3 -c "import json,sys; d=json.load(sys.stdin); d.pop('summary'); print(json.dumps(d,indent=1))" \
 *     > src/test/recorded/shell-session-frame.json
 */
import { describe, expect, it } from "vitest";
import type { Schemas } from "@/api/client";
import recorded from "@/test/recorded/shell-session-frame.json";
import system from "@/test/recorded/shell-system.json";
import { modelChip } from "./ModelChip";
import { sectionStates } from "./nav";
import { paletteFilter } from "./Palette";
import { parseRoute, pathOf } from "./route";

const frame = recorded as unknown as Schemas["WorkspaceView"];

describe("parseRoute", () => {
  it("reads global and workspace routes", () => {
    expect(parseRoute("/").section).toBe("home");
    expect(parseRoute("/settings").section).toBe("settings");
    const r = parseRoute(`/s/${frame.key}/gene/MYCN`);
    expect(r).toMatchObject({
      section: "gene",
      kind: "s",
      key: frame.key,
      rest: ["MYCN"],
      bare: false,
    });
  });
  it("marks a workspace link without a section as bare", () => {
    expect(parseRoute(`/r/${frame.key}`)).toMatchObject({ kind: "r", bare: true });
    expect(parseRoute(`/s/${frame.key}/nonsense`).bare).toBe(true);
  });
  it("sends unknown paths home and round-trips paths", () => {
    expect(parseRoute("/s/not-hex/design").section).toBe("home");
    expect(pathOf("s", frame.key, "gene", "a b")).toBe(`/s/${frame.key}/gene/a%20b`);
    expect(parseRoute(pathOf("s", frame.key, "gene", "a b")).rest).toEqual(["a b"]);
    expect(pathOf("s", frame.key, "settings")).toBe("/settings");
  });
});

describe("sectionStates (recorded demo session)", () => {
  const states = sectionStates(frame, 2);
  it("shows the confirmed blind stages as done", () => {
    expect(states.design.done).toBe(frame.stages.find((s) => s.stage === "design")!.confirmed);
    expect(states.curves.reachable).toBe(true);
  });
  it("opens the results only when the server says they are visible", () => {
    expect(states.results.reachable).toBe(frame.results_visible);
    const blind = sectionStates({ ...frame, results_visible: false });
    expect(blind.results.reachable).toBe(false);
    expect(blind.results.lockReason).toMatch(/Blind/);
    expect(blind.audit.reachable).toBe(false);
  });
  it("locks a stage that is not open, with the server's reason", () => {
    // Prism opens with the results, whatever its own stage says (docs/app.md §2).
    expect(states.prism.reachable).toBe(frame.results_visible);
    const closed = sectionStates({
      ...frame,
      stages: frame.stages.map((s) =>
        s.stage === "curves" ? { ...s, open: false, blockers: ["confirm the design first"] } : s,
      ),
    });
    expect(closed.curves.lockReason).toBe("confirm the design first");
  });
  it("counts agent requests and hides Studio sections for a plain study", () => {
    expect(states.agents.count).toBe(2);
    const study = sectionStates({ ...frame, kind: "study", stages: [] });
    expect(study.design.absent).toBe(true);
    expect(study.prism.absent).toBe(true);
    expect(study.record.reachable).toBe(true);
  });
});

describe("paletteFilter", () => {
  it("prefers a name's start over a stray letter match", () => {
    expect(paletteFilter("gene ODC1", "odc")).toBe(1);
    expect(paletteFilter("go Audit", "odc")).toBe(0);
    expect(paletteFilter("Run the audit", "audit")).toBe(0.8);
    expect(paletteFilter("Settings", "model", ["model", "autonomy"])).toBe(0.4);
  });
});

/*
 * The model chip on the system view recorded from the same store (no model configured):
 *
 *   curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" -H "origin: $QPILOT_API" $QPILOT_API/api/system \
 *     | python3 -c "import json,sys; d=json.load(sys.stdin); d.pop('studies_dir',None); \
 *       d['demo'].pop('path',None); print(json.dumps(d,indent=1))" > src/test/recorded/shell-system.json
 */
describe("modelChip", () => {
  const model = (system as unknown as Schemas["SystemView"]).model;
  it("says 'no model' when none is configured", () => {
    expect(modelChip(model)).toMatchObject({ label: "no model", tone: "neutral" });
  });
  it("says what is wrong with a wrong configuration instead of 'no model is configured'", () => {
    const wrong = { ...model, misconfigured: true, reason: "the endpoint is not on this machine" };
    const chip = modelChip(wrong);
    expect(chip.tone).toBe("warn");
    expect(chip.status).toContain("the endpoint is not on this machine");
  });
});

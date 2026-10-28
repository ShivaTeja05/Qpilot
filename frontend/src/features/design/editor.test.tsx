// The Design editor. Recorded from the real API (see ./recorded/record_editor.py): the synthetic
// CFX export of the public corpus with a group sheet, the rules' proposals, and the engine's
// check of a draft. Nothing is hand-written except the person's clicks.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/ui";
import {
  EMPTY_DRAFT,
  groupsNow,
  parsePasted,
  pastedItems,
  patternTest,
  sampleMatcher,
  sampleNow,
  targetRoleItem,
  withItems,
  withSampleType,
  type Draft,
  type EditorView,
} from "./draft";
import { PastePanel } from "./PastePanel";
import editorJson from "./recorded/editor-cfx-synthetic.json";
import planJson from "./recorded/plan-cfx-synthetic.json";
import { ReviewDialog } from "./ReviewDialog";
import { SamplesPanel } from "./SamplesPanel";
import { TargetsPanel } from "./TargetsPanel";

const recorded = vi.hoisted(() => ({ plan: null as unknown, sets: [] as unknown[] }));
vi.mock("./editorApi", () => ({
  checkDesign: vi.fn(async () => recorded.plan),
  setDesign: vi.fn(async (...args: unknown[]) => {
    recorded.sets.push(args);
    return { message: "Recorded 3 changes." };
  }),
  attachSheet: vi.fn(),
  useDesignEditor: vi.fn(),
}));

const view = editorJson as unknown as EditorView;
recorded.plan = planJson;
const noQuotes = () => undefined;
const draftOf = (d: Draft) => [...d.values()];

afterEach(cleanup);

function wrap(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("the draft", () => {
  it("is what the recorded file needs: two targets undecided, eight study samples", () => {
    expect(view.targets.map((t) => [t.target, t.role])).toEqual([
      ["REF", null],
      ["GOI", null],
    ]);
    expect(view.samples.filter((s) => s.role === "unkn")).toHaveLength(8);
    expect(view.needs.map((n) => n.code)).toContain("reference");
    // blind: no sample row carries a group (memberships are a separate list)
    expect(view.samples.every((s) => !("group" in s))).toBe(true);
  });

  it("applies the person's changes on top of the design so far", () => {
    const members = new Map(view.membership.map((m) => [m.sample, m]));
    let d = withItems(EMPTY_DRAFT, [
      { kind: "design.group", subject: "S1", payload: { group: "A" } },
      { kind: "design.group", subject: "S5", payload: { group: "B" } },
    ]);
    const s1 = view.samples.find((s) => s.sample === "S1")!;
    expect(sampleNow(s1, members.get("S1"), d)).toMatchObject({ group: "A", role: "unkn" });
    expect([...groupsNow(view, d)]).toEqual([
      ["A", 1],
      ["B", 1],
    ]);
    // the last change to an item wins
    d = withItems(d, [{ kind: "design.group", subject: "S1", payload: { group: null } }]);
    expect(sampleNow(s1, members.get("S1"), d).group).toBeNull();
    expect(d.size).toBe(2);
  });

  it("puts standards in one series with their quantities, and takes them out again", () => {
    let d = withSampleType(
      EMPTY_DRAFT,
      [
        { sample: "S1", experiment: "qpilot_import" },
        { sample: "S2", experiment: "qpilot_import" },
      ],
      "std",
      { S1: 1e6, S2: 1e5 },
    );
    const [series] = draftOf(d);
    expect(series).toMatchObject({
      kind: "design.dilution_series",
      payload: { experiment_id: "qpilot_import", samples: { S1: 1e6, S2: 1e5 } },
    });
    d = withSampleType(d, [{ sample: "S2", experiment: "qpilot_import" }], "unkn");
    expect(draftOf(d).map((i) => [i.kind, i.subject])).toEqual([
      ["design.dilution_series", series!.subject],
      ["design.well_role", "S2"],
    ]);
    expect(draftOf(d)[0]!.payload).toMatchObject({ samples: { S1: 1e6 } });
  });

  it("selects by a wildcard, a regular expression or part of a name", () => {
    const names = ["S1", "S12", "NTC", "KO_d7", "WT_d7"];
    expect(names.filter(patternTest("S?")!)).toEqual(["S1"]);
    expect(names.filter(patternTest("*_d7")!)).toEqual(["KO_d7", "WT_d7"]);
    expect(names.filter(patternTest("/^S1\\d$/")!)).toEqual(["S12"]);
    expect(names.filter(patternTest("ntc")!)).toEqual(["NTC"]);
    expect(patternTest("  ")).toBeNull();
  });

  it("reads a list pasted from Excel and names what it cannot use", () => {
    const match = sampleMatcher(view.samples, () => null);
    const rows = parsePasted(
      "Sample\tGroup\ns1\tcontrol\nS2\tcontrol\tmouse 1\nS9\ttreated\nS5\t<b>\nS2\tagain",
      match,
    );
    expect(rows.map((r) => [r.sample, r.problem])).toEqual([
      ["S1", null], // a header row is skipped; case is ignored
      ["S2", null],
      [null, "no sample in this file has this name"],
      ["S5", "a group name uses letters, digits, spaces and _ - . ( ), at most 64 characters"],
      ["S2", "this sample is already on line 3"],
    ]);
    expect(pastedItems(rows)).toEqual([
      { kind: "design.group", subject: "S1", payload: { group: "control" } },
      { kind: "design.group", subject: "S2", payload: { group: "control" } },
      { kind: "design.bio_unit", subject: "S2", payload: { biological_unit: "mouse 1" } },
    ]);
  });
});

describe("the target list", () => {
  it("sets a target's role with one click (into the draft, nothing recorded)", () => {
    const onChange = vi.fn();
    wrap(<TargetsPanel view={view} draft={EMPTY_DRAFT} quotes={noQuotes} onChange={onChange} />);
    const ref = screen.getByRole("radiogroup", { name: "Role of target REF" });
    fireEvent.click(within(ref).getByRole("radio", { name: "Reference gene" }));
    expect(onChange).toHaveBeenCalledWith([targetRoleItem("REF", "ref")]);
    expect(screen.getAllByText("not decided")).toHaveLength(2);
  });
});

describe("the sample table", () => {
  it("selects by name, then puts the selection in a group; controls are left out", () => {
    const onSelect = vi.fn();
    const onDraft = vi.fn();
    const { rerender } = wrap(
      <SamplesPanel
        view={view}
        draft={EMPTY_DRAFT}
        quotes={noQuotes}
        selected={new Set()}
        onSelect={onSelect}
        onDraft={onDraft}
        proposed={new Map()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Select by name"), { target: { value: "S?" } });
    fireEvent.click(screen.getByRole("button", { name: "Select matching" }));
    const chosen = onSelect.mock.calls.at(-1)![0] as Set<string>;
    expect([...chosen].sort()).toEqual(["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]);

    const withControl = new Set(["S1", "S2", "NTC"]);
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <SamplesPanel
            view={view}
            draft={EMPTY_DRAFT}
            quotes={noQuotes}
            selected={withControl}
            onSelect={onSelect}
            onDraft={onDraft}
            proposed={new Map()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const bar = screen.getByRole("group", { name: "Set the selected samples" }).textContent;
    expect(bar).toContain("3 samples selected");
    expect(bar).toContain("1 is a control");
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "control" } });
    fireEvent.click(screen.getByRole("button", { name: "Put in group" }));
    const draft = onDraft.mock.calls.at(-1)![0] as Draft;
    expect(draftOf(draft)).toEqual([
      { kind: "design.group", subject: "S1", payload: { group: "control" } },
      { kind: "design.group", subject: "S2", payload: { group: "control" } },
    ]);
  });

  it("takes what the sheet proposed with one click", () => {
    const onDraft = vi.fn();
    const proposed = new Map([
      ["S1", { group: "A" }],
      ["S5", { group: "B" }],
    ]);
    wrap(
      <SamplesPanel
        view={view}
        draft={EMPTY_DRAFT}
        quotes={noQuotes}
        selected={new Set()}
        onSelect={vi.fn()}
        onDraft={onDraft}
        proposed={proposed}
      />,
    );
    expect(screen.getAllByText(/proposed: /)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Take what is proposed" }));
    expect(draftOf(onDraft.mock.calls.at(-1)![0] as Draft).map((i) => i.payload)).toEqual([
      { group: "A" },
      { group: "B" },
    ]);
  });

  it("refuses a group name the engine would not keep, in words", () => {
    wrap(
      <SamplesPanel
        view={view}
        draft={EMPTY_DRAFT}
        quotes={noQuotes}
        selected={new Set(["S1"])}
        onSelect={vi.fn()}
        onDraft={vi.fn()}
        proposed={new Map()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "a/b" } });
    expect(screen.getByText(/A group name uses letters, digits/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Put in group" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("pasting a list", () => {
  it("adds the matched lines to the draft", () => {
    const onDraft = vi.fn();
    wrap(<PastePanel view={view} draft={EMPTY_DRAFT} quotes={noQuotes} onDraft={onDraft} />);
    fireEvent.change(screen.getByLabelText("Paste a sample list"), {
      target: { value: "S1\tA\nS2\tA\nnobody\tB" },
    });
    expect(screen.getByText(/2 of 3 lines match a sample/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add 2 samples to the changes" }));
    expect(draftOf(onDraft.mock.calls[0]![0] as Draft)).toHaveLength(2);
  });
});

describe("review and record", () => {
  const draft = withItems(EMPTY_DRAFT, [
    targetRoleItem("REF", "ref"),
    { kind: "design.group", subject: "S1", payload: { group: "A" } },
    { kind: "design.group", subject: "S5", payload: { group: "Z" } },
    { kind: "design.group", subject: "NTC", payload: { group: "A" } },
  ]);

  it("shows the engine's check of each change and what is refused, before anything is written", async () => {
    const onDraft = vi.fn();
    wrap(
      <ReviewDialog
        sid="bd275bf6e009"
        draft={draft}
        open
        onOpenChange={vi.fn()}
        onRecorded={vi.fn()}
        onDraft={onDraft}
      />,
    );
    await screen.findByText(/To record \(3\)/);
    expect(screen.getByText(/Refused \(1\)/)).toBeTruthy();
    expect(screen.getByText("A control cannot join a biological group or unit.")).toBeTruthy();
    expect(screen.getByText(/accepts the waiting proposal that says the same/)).toBeTruthy();
    expect(screen.getByText(/rejects 1 waiting proposal that says otherwise/)).toBeTruthy();
    const record = screen.getByRole("button", { name: "Record 3 changes" }) as HTMLButtonElement;
    expect(record.disabled).toBe(true); // nothing is recorded while a change is refused
    fireEvent.click(screen.getByRole("button", { name: "Remove the refused changes" }));
    const kept = draftOf(onDraft.mock.calls[0]![0] as Draft).map((i) => i.subject);
    expect(kept).toEqual(["REF", "S1", "S5"]);
    expect(recorded.sets).toHaveLength(0);
  });

  it("records with the person's reason only", async () => {
    const clean = withItems(EMPTY_DRAFT, [targetRoleItem("REF", "ref")]);
    recorded.plan = { ...planJson, items: planJson.items.slice(0, 1) };
    const onRecorded = vi.fn();
    wrap(
      <ReviewDialog
        sid="bd275bf6e009"
        draft={clean}
        open
        onOpenChange={vi.fn()}
        onRecorded={onRecorded}
        onDraft={vi.fn()}
      />,
    );
    const record = await screen.findByRole("button", { name: "Record 1 change" });
    fireEvent.click(record);
    expect(await screen.findByRole("alert")).toBeTruthy(); // say why first
    expect(recorded.sets).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "From my lab notebook" }));
    fireEvent.click(record);
    await waitFor(() => expect(onRecorded).toHaveBeenCalled());
    expect(recorded.sets[0]).toEqual([
      "bd275bf6e009",
      [targetRoleItem("REF", "ref")],
      "From my lab notebook",
      planJson.head,
      false,
    ]);
    recorded.plan = planJson;
  });
});

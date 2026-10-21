/**
 * The Controls section on JSON recorded from the real route (`recorded/record.py`): the demo study
 * analysed outside Studio (64 plates, three auto-decided cards, read-only) and the Studio tests'
 * mini file with an early no-template control (one open card a person decides here; the same
 * card with an agent's request waiting; and the new analysis after a person left the wells out),
 * and a file with reverse-transcription replicates and a run file a person linked to one plate
 * (G-RT and G-INSTR warn there). No number is typed in: every expectation is read from a
 * recording or formatted from it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { plural } from "@/lib/format";
import { TooltipProvider } from "@/ui";
import type { GateView } from "../api";
import { GatePage } from "../index";
import {
  DEFAULT_FILTER,
  VERDICT_WORD,
  filterEvaluations,
  leadOption,
  plateLabel,
  runSourceText,
  verdictCounts,
  wellText,
  whereText,
} from "../words";
import demoJson from "./recorded/gate-demo.json";
import leftOutJson from "./recorded/gate-mini-left-out.json";
import miniJson from "./recorded/gate-mini.json";
import requestJson from "./recorded/gate-mini-request.json";
import rtJson from "./recorded/gate-rt-linked.json";

const DEMO = demoJson as unknown as GateView;
const MINI = miniJson as unknown as GateView;
const REQUEST = requestJson as unknown as GateView;
const LEFT_OUT = leftOutJson as unknown as GateView;
const RT = rtJson as unknown as GateView;
const BANNED = /\b(valid|validated|invalid|compliant|diagnostic|QC passed)\b/i;
/** Testing Library folds the page's narrow no-break spaces into plain ones. */
const text = (s: string) => s.replace(/\s+/g, " ");

function workspace(view: GateView): Schemas["WorkspaceView"] {
  return {
    key: view.session ?? view.study_id,
    kind: view.session ? "session" : "study",
    study_id: view.study_id,
  } as unknown as Schemas["WorkspaceView"];
}

function page(view: GateView) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <GatePage view={view} workspace={workspace(view)} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

/** Answer every POST with what the route answers to a person's choice (no network). */
function answering() {
  const done = {
    status: "left_out",
    message: "Left out 3 wells: the study is being analysed again without them.",
    study_id: MINI.study_id,
    left_out: [],
    put_back: [],
    inbox_head: MINI.inbox_head,
    job: null,
  };
  return vi
    .spyOn(api, "POST")
    .mockImplementation((() =>
      Promise.resolve({ data: done, response: new Response(null, { status: 200 }) })) as never);
}

type Sent = [
  string,
  {
    params: { path: { study_id: string; card_id: string } };
    body: { option: string; reason: string; expected_head: string; expected_inbox: string };
  },
];

const cardsRegion = () => screen.getByRole("region", { name: "Decision Cards from the controls" });

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    (q: string) =>
      ({
        matches: q.includes("reduce"),
        media: q,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        onchange: null,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the gate's words", () => {
  it("uses the four status words and never a clinical or QC claim", () => {
    expect(Object.values(VERDICT_WORD)).toEqual(["Fail", "Warn", "Pass", "Not applicable"]);
    for (const view of [DEMO, MINI]) {
      const lines = [
        view.headline.plain,
        view.how_to_apply,
        view.pack.label,
        ...view.consequences.map((c) => c.triage_text),
        ...view.cards.map((c) => c.status_line),
      ];
      for (const line of lines) expect(line).not.toMatch(BANNED);
    }
    for (const view of [REQUEST, LEFT_OUT]) {
      for (const c of view.cards) expect(c.status_line).not.toMatch(BANNED);
      for (const c of view.consequences) expect(c.triage_text).not.toMatch(BANNED);
    }
  });

  it("names plates, wells and places the way a scientist reads them", () => {
    expect(plateLabel("CAMTA2_20080227")).toBe("CAMTA2");
    expect(plateLabel("1-Mar_plate")).toBe("1-Mar_plate");
    expect(wellText("CAMTA2_20080227/F24")).toBe("CAMTA2 · F24");
    const ntc = DEMO.evaluations.find((e) => e.rule_id === "G-NTC-1" && e.verdict === "fail")!;
    expect(whereText(ntc)).toBe(`Plate ${plateLabel(ntc.plate)}`); // the target is the plate's gene
    const rep = DEMO.evaluations.find((e) => e.level === "sample")!;
    expect(whereText(rep)).toContain(`sample ${rep.sample}`);
  });

  it("filters problems first and counts exactly what the server counts", () => {
    expect(verdictCounts(DEMO.evaluations)).toEqual(DEMO.counts);
    const attention = filterEvaluations(DEMO.evaluations, DEFAULT_FILTER);
    expect(attention).toHaveLength(DEMO.counts.fail! + DEMO.counts.warn!);
    expect(attention.slice(0, DEMO.counts.fail).every((e) => e.verdict === "fail")).toBe(true);
    const all = filterEvaluations(DEMO.evaluations, { ...DEFAULT_FILTER, verdict: "all" });
    expect(all).toHaveLength(DEMO.evaluations.length);
    const plate = DEMO.plates[0]!.plate;
    const onPlate = filterEvaluations(DEMO.evaluations, {
      verdict: "all",
      rule: "G-STD",
      plate,
    });
    expect(onPlate.map((e) => e.id)).toEqual(
      DEMO.evaluations.filter((e) => e.rule_id === "G-STD" && e.plate === plate).map((e) => e.id),
    );
  });

  it("leads with the option that changes the most", () => {
    for (const c of [...DEMO.consequences, ...MINI.consequences]) {
      const lead = leadOption(c)!;
      for (const o of c.options) expect(lead.n_flipped).toBeGreaterThanOrEqual(o.n_flipped);
    }
  });
});

describe("the Controls page", { timeout: 30_000 }, () => {
  it("says the headline, the verdict counts and every plate", () => {
    page(DEMO);
    expect(text(screen.getByRole("heading", { level: 1 }).textContent ?? "")).toContain(
      "What the controls on each plate say",
    );
    const summary = screen.getByRole("region", { name: "In one line" });
    expect(text(summary.textContent ?? "")).toContain(text(DEMO.headline.plain));
    const counts = within(summary).getByRole("list", { name: "Rule checks by verdict" });
    for (const [verdict, n] of Object.entries(DEMO.counts)) {
      const word = VERDICT_WORD[verdict as keyof typeof VERDICT_WORD];
      const item = within(counts).getByText(word).closest("li")!;
      expect(text(item.textContent ?? "")).toContain(String(n));
    }
    const plates = screen.getByRole("list", { name: "Plates" });
    expect(within(plates).getAllByRole("button")).toHaveLength(DEMO.plates.length);
    expect(screen.getAllByText(/research use/i).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(BANNED);
  });

  it("lists the checks that warn or fail, each opening to its reason, wells and consequence", () => {
    page(DEMO);
    const list = screen.getByRole("list", { name: "Rule checks" });
    const rows = within(list).getAllByRole("button", { expanded: false });
    expect(rows).toHaveLength(DEMO.counts.fail! + DEMO.counts.warn!);
    const ntc = DEMO.evaluations.find((e) => e.rule_id === "G-NTC-1" && e.consequence)!;
    const row = rows.find(
      (r) =>
        r.textContent?.includes(`Plate ${plateLabel(ntc.plate)}`) &&
        r.textContent.includes("G-NTC-1"),
    )!;
    fireEvent.click(row);
    expect(row.getAttribute("aria-expanded")).toBe("true");
    const body = document.getElementById(row.getAttribute("aria-controls")!)!;
    expect(text(body.textContent ?? "")).toContain(text(ntc.reason.plain));
    for (const w of ntc.flagged)
      expect(within(body).getAllByText(wellText(w)).length).toBeGreaterThan(0);
    const conseq = DEMO.consequences.find((c) => c.id === ntc.consequence)!;
    expect(text(body.textContent ?? "")).toContain(conseq.triage_text);
    expect(text(body.textContent ?? "")).toContain(text(conseq.options[0]!.text.plain));
  });

  it("filters to one plate from the plate strip", () => {
    page(DEMO);
    const plate = DEMO.plates.find((p) => p.worst === "fail")!;
    const button = within(screen.getByRole("list", { name: "Plates" })).getByRole("button", {
      name: new RegExp(`^${plateLabel(plate.plate).replace(/[()]/g, "\\$&")}:`),
    });
    fireEvent.click(button);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    const rows = within(screen.getByRole("list", { name: "Rule checks" })).getAllByRole("button");
    const expected = DEMO.evaluations.filter(
      (e) => e.plate === plate.plate && (e.verdict === "fail" || e.verdict === "warn"),
    );
    expect(rows).toHaveLength(expected.length);
  });

  it("opens a check from the list of what leaving wells out changes", () => {
    page(DEMO);
    const region = screen.getByRole("region", { name: "What leaving the wells out would change" });
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(DEMO.consequences.length);
    fireEvent.click(within(items[0]!).getByRole("button", { name: "Show the check" }));
    const opened = within(screen.getByRole("list", { name: "Rule checks" })).getAllByRole(
      "button",
      { expanded: true },
    );
    expect(opened).toHaveLength(1);
    expect(document.activeElement).toBe(opened[0]);
  });

  it("shows the demo's cards as decided automatically, read-only, with a way to Trace", () => {
    page(DEMO);
    const cards = screen.getByRole("region", { name: "Decision Cards from the controls" });
    const articles = within(cards).getAllByRole("article");
    expect(articles).toHaveLength(DEMO.cards.length);
    for (const [i, card] of DEMO.cards.entries()) {
      const a = articles[i]!;
      expect(text(a.textContent ?? "")).toContain("Decided automatically");
      expect(text(a.textContent ?? "")).toContain(text(card.impact.plain));
      expect(text(a.textContent ?? "")).toContain(card.status_line);
      expect(within(a).getByRole("link", { name: /Trace/ }).getAttribute("href")).toBe(
        `/r/${DEMO.study_id}/trace`,
      );
    }
    expect(within(cards).queryByRole("radio")).toBeNull(); // nothing is decided here
    expect(within(cards).queryByRole("textbox")).toBeNull();
  });

  it("shows an open card a person decides here: an option, a reason, then Decide", async () => {
    const post = answering();
    page(MINI);
    const [card] = MINI.cards;
    const conseq = MINI.consequences.find((c) => c.card_id === card!.card.id)!;
    expect(card!.card.status).toBe("open");
    expect(MINI.can_decide && conseq.can_decide).toBe(true);
    const region = cardsRegion();
    expect(text(region.textContent ?? "")).toContain(MINI.decide_note);
    const article = within(region).getByRole("article");
    expect(text(article.textContent ?? "")).toContain("A person decides");
    const leaveOut = card!.options.find((o) => o.id !== "keep")!;
    expect(leaveOut.effects).toHaveLength(0);
    expect(text(article.textContent ?? "")).toContain(
      `${card!.genes[0]}no call: it can no longer be compared`,
    );
    const radios = within(article).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(
      card!.options.map((o) => o.id),
    );
    expect((radios[0] as HTMLInputElement).checked).toBe(true); // the recommended option
    fireEvent.click(radios[1]!);
    const decide = within(article).getByRole("button", { name: `Decide: ${leaveOut.label}` });
    expect((decide as HTMLButtonElement).disabled).toBe(true); // a reason first
    fireEvent.change(within(article).getByRole("textbox"), {
      target: { value: "The NTC amplified on this plate" },
    });
    fireEvent.click(decide);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as Sent;
    expect(route).toBe("/api/studies/{study_id}/gate/cards/{card_id}/decide");
    expect(init.params.path).toEqual({ study_id: MINI.study_id, card_id: conseq.decision_id });
    expect(init.body).toEqual({
      option: leaveOut.id,
      reason: "The NTC amplified on this plate",
      expected_head: MINI.head,
      expected_inbox: MINI.inbox_head,
    });
    expect(within(article).queryByRole("link", { name: /Trace/ })).toBeNull();
    expect(text(document.body.textContent ?? "")).toContain(text(MINI.headline.plain));
  });

  it("shows an agent's request on its card: Approve or Turn down, with a reason", async () => {
    const post = answering();
    page(REQUEST);
    const conseq = REQUEST.consequences.find((c) => c.card_id)!;
    const [request] = conseq.requests;
    expect(request!.left_out).toBe(true);
    const article = within(cardsRegion()).getByRole("article");
    expect(text(article.textContent ?? "")).toContain("Agent request");
    expect(text(article.textContent ?? "")).toContain(`“${request!.reason}”`);
    expect(within(article).getByText("Agent asked")).toBeTruthy();
    expect(within(article).queryByRole("radio")).toBeNull();
    fireEvent.change(within(article).getByRole("textbox"), {
      target: { value: "Not before the repeat plate" },
    });
    fireEvent.click(within(article).getByRole("button", { name: "Turn down" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [, init] = post.mock.calls[0] as unknown as Sent;
    expect(init.body.option).toBe("keep"); // turning it down keeps every well
    expect(init.body.reason).toBe("Not before the repeat plate");
    const approve = within(article).getByRole("button", {
      name: `Approve: ${request!.option_label}`,
    });
    expect(approve).toBeTruthy();
  });

  it("lists the wells a person left out, with why, and puts them back with a reason", async () => {
    const post = answering();
    page(LEFT_OUT);
    expect(LEFT_OUT.cards).toHaveLength(0);
    const conseq = LEFT_OUT.consequences.find((c) => c.decision)!;
    const decision = conseq.decision!;
    expect(decision.action).toBe("left_out");
    expect(conseq.options[0]!.code).toBe("already_left_out");
    const article = within(cardsRegion()).getByRole("article");
    expect(text(article.textContent ?? "")).toContain("Decided by a person");
    expect(text(article.textContent ?? "")).toContain(`Why: ${decision.reason}`);
    for (const w of decision.left_out) expect(article.textContent).toContain(wellText(w));
    fireEvent.click(within(article).getByRole("button", { name: "Put the wells back" }));
    fireEvent.change(within(article).getByRole("textbox"), {
      target: { value: "The repeat plate's NTC stayed flat" },
    });
    fireEvent.click(within(article).getByRole("button", { name: "Put the wells back" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [, init] = post.mock.calls[0] as unknown as Sent;
    expect(init.params.path.card_id).toBe(conseq.decision_id);
    expect(init.body.option).toBe("keep");
    expect(init.body.expected_head).toBe(LEFT_OUT.head);
  });
});

describe("G-RT and G-INSTR on the Controls page", { timeout: 30_000 }, () => {
  const rtRow = RT.evaluations.find((e) => e.rule_id === "G-RT" && e.verdict === "warn")!;
  const instrRow = RT.evaluations.find((e) => e.rule_id === "G-INSTR" && e.verdict === "warn")!;
  const linked = RT.runs.find((r) => r.source === "linked")!;

  it("names a unit's check and the run file each plate's check read", () => {
    expect(rtRow.level).toBe("unit");
    expect(whereText(rtRow)).toBe(`Unit ${rtRow.unit} · ${rtRow.target}`);
    expect(whereText(instrRow)).toBe(`Plate ${plateLabel(instrRow.plate)}`);
    expect(linked.evaluation).toBe(instrRow.id);
    expect(runSourceText(linked)).toBe(`${linked.name} (an .eds file), linked by a person`);
    const own = RT.runs.find((r) => r.source === "study_file")!;
    expect(runSourceText(own)).toMatch(/^The study's own file \(RDML/);
    expect(runSourceText({ ...linked, problem: "changed" })).toContain("has changed");
    for (const line of [RT.headline.plain, RT.run_note, ...RT.cards.map((c) => c.status_line)])
      expect(line).not.toMatch(BANNED);
  });

  it("lists both checks with the problems, a unit's and a run's, each opening to its reason", () => {
    page(RT);
    const list = screen.getByRole("list", { name: "Rule checks" });
    const rows = within(list).getAllByRole("button", { expanded: false });
    expect(rows).toHaveLength(RT.counts.fail! + RT.counts.warn!);
    const unit = rows.find((r) => r.textContent?.includes(whereText(rtRow)))!;
    expect(unit.textContent).toContain("G-RT");
    const run = rows.find((r) => r.textContent?.includes("G-INSTR"))!;
    fireEvent.click(run);
    const body = document.getElementById(run.getAttribute("aria-controls")!)!;
    expect(text(body.textContent ?? "")).toContain(text(instrRow.reason.plain));
    // a whole run's wells: the first ones as chips, the rest folded away
    expect(instrRow.flagged.length).toBeGreaterThan(24);
    expect(within(body).getAllByText(wellText(instrRow.flagged[0]!)).length).toBeGreaterThan(0);
    // the rule's wells and the option's (the same run) fold the same way
    expect(
      within(body).getAllByText(`and ${plural(instrRow.flagged.length - 24, "more well")}`),
    ).toHaveLength(2);
    expect(text(body.textContent ?? "")).toContain(`Run file read: ${runSourceText(linked)}.`);
    fireEvent.click(
      within(body).getByRole("button", { name: "Link another run file for this plate" }),
    );
    expect(document.activeElement?.textContent).toBe(
      `Choose the run file for plate ${plateLabel(linked.plate)}`,
    );
  });

  it("says which plates read a linked run file, and unlinks one", async () => {
    const post = vi.spyOn(api, "POST").mockImplementation((() =>
      Promise.resolve({
        data: {
          plate: linked.plate,
          linked: false,
          name: linked.name,
          kind: "eds",
          message: "Unlinked.",
        },
        response: new Response(null, { status: 200 }),
      })) as never);
    page(RT);
    const region = screen.getByRole("region", { name: "Run files" });
    expect(text(region.textContent ?? "")).toContain(text(RT.run_note));
    const own = RT.runs.filter((r) => r.source === "study_file").length;
    expect(text(region.textContent ?? "")).toContain(
      `G-INSTR reads a run file a person linked for 1 of the ${plural(RT.runs.length, "plate")}, the study's own file for ${own}.`,
    );
    const items = within(
      within(region).getByRole("list", { name: "Linked run files" }),
    ).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(text(items[0]!.textContent ?? "")).toContain(runSourceText(linked));
    fireEvent.click(
      within(items[0]!).getByRole("button", {
        name: `Unlink the run file of plate ${plateLabel(linked.plate)}`,
      }),
    );
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [
      string,
      { params: { path: { study_id: string } }; body: { plate: string } },
    ];
    expect(route).toBe("/api/studies/{study_id}/gate/run-files/unlink");
    expect(init.params.path.study_id).toBe(RT.study_id);
    expect(init.body).toEqual({ plate: linked.plate });
  });

  it("links a run file to the chosen plate as a form upload", async () => {
    const sent: { url: string; form: FormData }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        sent.push({ url, form: init.body as FormData });
        const done = {
          plate: RT.runs[0]!.plate,
          linked: true,
          name: "run.eds",
          kind: "eds",
          message: "Linked.",
        };
        return Promise.resolve(
          new Response(JSON.stringify(done), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }),
    );
    page(RT);
    const first = RT.runs[0]!.plate;
    const input = screen.getByLabelText(`Run file for plate ${plateLabel(first)}`);
    const file = new File(["run"], "run.eds", { type: "application/octet-stream" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.url).toBe(`/api/studies/${RT.study_id}/gate/run-files`);
    expect(sent[0]!.form.get("plate")).toBe(first);
    expect((sent[0]!.form.get("run") as File).name).toBe("run.eds");
  });

  it("says the demo's checks read the study's own file on every plate", () => {
    page(DEMO);
    const region = screen.getByRole("region", { name: "Run files" });
    expect(DEMO.runs.every((r) => r.source === "study_file")).toBe(true);
    expect(text(region.textContent ?? "")).toContain(
      `G-INSTR reads the study's own file for every one of the ${plural(DEMO.runs.length, "plate")}.`,
    );
    expect(within(region).queryByRole("list", { name: "Linked run files" })).toBeNull();
  });
});

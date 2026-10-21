/**
 * The Controls section on JSON recorded from the real route (`recorded/record.py`): the demo study
 * analysed outside Studio (64 plates, three auto-decided cards) and the Studio tests' mini file
 * with an early no-template control (one open card). No number is typed in: every expectation is
 * read from a recording or formatted from it.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { TooltipProvider } from "@/ui";
import type { GateView } from "../api";
import { GatePage } from "../index";
import {
  DEFAULT_FILTER,
  VERDICT_WORD,
  filterEvaluations,
  leadOption,
  plateLabel,
  verdictCounts,
  wellText,
  whereText,
} from "../words";
import demoJson from "./recorded/gate-demo.json";
import miniJson from "./recorded/gate-mini.json";

const DEMO = demoJson as unknown as GateView;
const MINI = miniJson as unknown as GateView;
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
  return render(
    <TooltipProvider>
      <GatePage view={view} workspace={workspace(view)} />
    </TooltipProvider>,
  );
}

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

  it("shows an open card: a person decides, and a gene that can no longer be compared", () => {
    page(MINI);
    const [card] = MINI.cards;
    expect(card!.card.status).toBe("open");
    const article = within(
      screen.getByRole("region", { name: "Decision Cards from the controls" }),
    ).getByRole("article");
    expect(text(article.textContent ?? "")).toContain("A person decides");
    const leaveOut = card!.options.find((o) => o.id !== "keep")!;
    expect(leaveOut.effects).toHaveLength(0);
    expect(text(article.textContent ?? "")).toContain(
      `${card!.genes[0]}no call: it can no longer be compared`,
    );
    const link = within(article).getByRole("link", { name: "Leave wells out in Curves" });
    expect(link.getAttribute("href")).toBe(`/s/${MINI.session}/curves`);
    expect(text(document.body.textContent ?? "")).toContain(text(MINI.headline.plain));
  });
});

/**
 * "Also test efficiency models" on the API's own views of the demo session, before and after a
 * person accepted the proposal (recorded from the real server: ./recorded/README.md).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { describeProposal, type Proposal } from "@/lib/vocab";
import { TooltipProvider } from "@/ui";
import {
  AXIS_STATUS,
  AxisPanel,
  OptionsEditor,
  asksToTest,
  consequenceWords,
  namedOptions,
  type AxisView,
} from "../FurtherChoices";
import off from "./recorded/axes-off.json";
import decidedInbox from "./recorded/proposals-choices-decided.json";
import pendingInbox from "./recorded/proposals-choices-pending.json";
import swept from "./recorded/axes-swept.json";

const offAxis = off.axes[0] as unknown as AxisView;
const sweptAxis = swept.axes[0] as unknown as AxisView;
const pending = pendingInbox as unknown as Schemas["ProposalList"];
const decided = decidedInbox as unknown as Schemas["ProposalList"];
const workspace = {
  key: off.session,
  kind: "session",
} as unknown as Schemas["WorkspaceView"];

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

/** Serve the inbox the page reads for the choices stage (and an empty quarantine). */
function serve(inbox: Schemas["ProposalList"]) {
  return vi
    .spyOn(api, "GET")
    .mockImplementation(((route: string) =>
      route === "/api/sessions/{sid}/proposals"
        ? ok(inbox)
        : ok({ entries: [], sheet_cells: {}, n_flagged: 0 })) as never);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the efficiency models, not tested yet", () => {
  it("say what qPilot uses and offer the proposal, which writes nothing by itself", async () => {
    serve({ ...decided, proposals: [] });
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() =>
        ok({ outcome: null, message: "Proposed: test the efficiency models." })) as never);
    wrap(<AxisPanel axis={offAxis} workspace={workspace} />);
    const panel = screen.getByRole("region", { name: "Also test efficiency models" });
    // the badge, and every model but LinRegPCR's
    expect(within(panel).getAllByText(AXIS_STATUS.off.word)).toHaveLength(1);
    expect(within(panel).getAllByText("Not in the grid")).toHaveLength(offAxis.options.length - 1);
    expect(panel.textContent).toContain(offAxis.text.plain);
    for (const o of offAxis.options) expect(panel.textContent).toContain(o.label);
    expect(within(panel).getByText("In use")).toBeTruthy();
    const propose = await within(panel).findByRole("button", {
      name: "Propose testing the efficiency models",
    });
    await act(async () => fireEvent.click(propose));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [
      string,
      { params: { path: { sid: string } }; body: { axis: string; on: boolean } },
    ];
    expect(route).toBe("/api/sessions/{sid}/propose/axis");
    expect(init.params.path.sid).toBe(off.session);
    expect(init.body).toEqual({ axis: "efficiency", on: true });
  });
});

describe("the proposal", () => {
  const proposal = pending.proposals.find((p) => p.status === "proposed") as Proposal;

  it("reads the same in the page as in the server's words", () => {
    expect(proposal.kind).toBe("choice.axis");
    expect(describeProposal(proposal)).toBe(pending.descriptions[proposal.id]);
    expect(asksToTest(proposal)).toBe(true);
  });

  it("is edited only among the models the rule found to apply", () => {
    const named = namedOptions(proposal);
    expect(named).toEqual((proposal.payload as { options: string[] }).options);
    wrap(
      <OptionsEditor axis={offAxis} value={proposal.payload} onChange={() => {}} allowed={named} />,
    );
    const expected = offAxis.options.filter((o) => !o.primary && named.includes(o.id));
    expect(screen.getAllByRole("switch")).toHaveLength(expected.length);
    expect(offAxis.options.some((o) => !o.primary && !named.includes(o.id))).toBe(true);
  });

  it("is decided in the panel, as a person, with the head the inbox showed", async () => {
    serve(pending);
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() =>
        ok({ outcome: { status: "accepted" }, message: "Accepted.", head: "x" })) as never);
    wrap(<AxisPanel axis={offAxis} workspace={workspace} />);
    const heading = await screen.findByRole("heading", { name: pending.descriptions[proposal.id] });
    const card = heading.closest("article") ?? heading.parentElement!.parentElement!;
    expect(card.textContent).toContain(consequenceWords(true));
    expect(screen.queryByRole("button", { name: /Propose/ })).toBeNull();
    await act(async () => fireEvent.click(within(card).getByRole("button", { name: "Accept" })));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [
      string,
      { params: { path: { pid: string } }; body: { expected_head: string } },
    ];
    expect(route).toBe("/api/sessions/{sid}/proposals/{pid}/accept");
    expect(init.params.path.pid).toBe(proposal.id);
    expect(init.body.expected_head).toBe(pending.head);
  });

  it("is edited with one switch per model that applies, LinRegPCR's always first", () => {
    let value: Record<string, unknown> = { options: ["linregpcr"] };
    const onChange = (next: Record<string, unknown>) => (value = next);
    const { rerender } = wrap(<OptionsEditor axis={sweptAxis} value={value} onChange={onChange} />);
    const switches = screen.getAllByRole("switch");
    const applies = sweptAxis.options.filter((o) => !o.primary && !o.unavailable);
    expect(switches).toHaveLength(applies.length);
    expect(screen.queryByText(/One efficiency per amplicon/)).toBeNull(); // does not apply here
    fireEvent.click(screen.getByRole("switch", { name: applies[applies.length - 1]!.label }));
    rerender(<OptionsEditor axis={sweptAxis} value={value} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch", { name: applies[0]!.label }));
    expect(value.options).toEqual(["linregpcr", applies[0]!.id, applies[applies.length - 1]!.id]);
  });
});

describe("the efficiency models, tested", () => {
  it("show what each model alone changes, as facts, and lead to the card", async () => {
    serve(decided);
    wrap(<AxisPanel axis={sweptAxis} workspace={workspace} />);
    const panel = screen.getByRole("region", { name: "Also test efficiency models" });
    expect(within(panel).getByText(AXIS_STATUS.swept.word)).toBeTruthy();
    expect(panel.textContent).toContain(sweptAxis.text.plain);
    for (const o of sweptAxis.options.filter((x) => x.flips)) {
      const fact = within(panel).getByTitle(`From the result: ${o.flips!.path}`);
      expect(fact.textContent).toBe(o.flips!.text);
    }
    const why = sweptAxis.options.find((o) => o.unavailable)!;
    expect(panel.textContent).toContain(why.unavailable!.slice(1)); // as a sentence
    expect(panel.textContent).toContain(sweptAxis.notes[0]!.plain);
    const link = within(panel).getByRole("link", { name: /Go to its Decision Card/ });
    expect(link.getAttribute("href")).toContain(`/results/card/${sweptAxis.card_id}`);
    await within(panel).findByRole("button", { name: "Propose to stop testing them" });
    fireEvent.click(within(panel).getByRole("button", { name: /Show what was decided \(1\)/ }));
    expect(panel.textContent).toContain("Accepted by you");
  });

  it("outside Studio, give the command instead of a proposal", () => {
    const get = serve(decided);
    const study = { key: swept.study_id, kind: "study" } as unknown as Schemas["WorkspaceView"];
    const axis = { ...sweptAxis, can_propose: false, command: "qpilot run --efficiency all" };
    wrap(<AxisPanel axis={axis} workspace={study} />);
    expect(screen.getByText("qpilot run --efficiency all")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Propose/ })).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});

/**
 * The Import Trust card on JSON recorded from the real route (`recorded/record_trust.py`): the
 * Studio tests' mini file opened as if from a CFX export with baseline-subtracted curves, before
 * anyone decides; the same card with an agent's request waiting; and the new analysis after a
 * person chose the instrument's Cq values only. No value is typed in: every expectation is read
 * from a recording.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { TooltipProvider } from "@/ui";
import type { TrustView } from "../api";
import { ImportTrustCard, ImportTrustView } from "../ImportTrust";
import cqOnlyJson from "./recorded/trust-cq-only.json";
import openJson from "./recorded/trust-open.json";
import requestJson from "./recorded/trust-request.json";

const OPEN = openJson as unknown as TrustView;
const REQUEST = requestJson as unknown as TrustView;
const CQ_ONLY = cqOnlyJson as unknown as TrustView;
const KEY = "the-session"; // the workspace key (only used in the reject call's path)

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
}

function card(view: TrustView) {
  // The write hook needs a query client; the view itself is passed in (no fetch).
  function WithWrite() {
    return <ImportTrustCard workspaceKey={KEY} studyId={view.study_id} isSession />;
  }
  const qc = client();
  qc.setQueryData(["w", KEY, "import-trust", view.study_id], view);
  // a read after a write answers the same recording (no network)
  vi.spyOn(api, "GET").mockImplementation((() =>
    Promise.resolve({ data: view, response: new Response(null, { status: 200 }) })) as never);
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <WithWrite />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function answering(answer: object) {
  return vi
    .spyOn(api, "POST")
    .mockImplementation((() =>
      Promise.resolve({ data: answer, response: new Response(null, { status: 200 }) })) as never);
}

const article = () => screen.getByRole("article", { name: /Import Trust/ });
const reasonBox = () => within(article()).getByRole("textbox");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the Import Trust card before anyone decides", () => {
  it("says what the export is, the cap in force and each option's cap", () => {
    card(OPEN);
    const box = article();
    expect(within(box).getByText("A person decides")).toBeTruthy();
    expect(box.textContent).toContain(OPEN.verdict_title);
    expect(box.textContent).toContain(OPEN.verdict_meaning);
    expect(box.textContent).toContain(`${OPEN.connector_label} export`);
    const radios = within(box).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(OPEN.options.map((o) => o.id));
    for (const o of OPEN.options) {
      expect(box.textContent).toContain(o.label);
      expect(box.textContent).toContain(o.effect);
    }
    const inUse = OPEN.options.find((o) => o.in_use)!;
    expect(inUse.id).toBe(OPEN.in_use);
    expect(within(box).getByText("In use")).toBeTruthy();
    expect(within(box).getByText("Recommended")).toBeTruthy();
    // the recommended option (re-export) is selected first and its recipe shown
    const recommended = OPEN.options.find((o) => o.recommended)!;
    expect((radios.find((r) => (r as HTMLInputElement).checked) as HTMLInputElement).value).toBe(
      recommended.id,
    );
    expect(box.textContent).toContain(OPEN.recipe);
    expect(box.textContent).toContain(`${OPEN.cap} confidence`);
  });

  it("decides an option with a reason, and needs one", async () => {
    const sent = answering({
      status: "decided",
      option: "cq_only",
      message: "Recorded.",
      study_id: OPEN.study_id,
      changed: true,
      inbox_head: OPEN.inbox_head,
      job: null,
    });
    card(OPEN);
    const box = article();
    fireEvent.click(within(box).getByRole("radio", { name: /instrument's Cq values only/ }));
    const cq = OPEN.options.find((o) => o.id === "cq_only")!;
    const decideButton = within(box).getByRole("button", { name: `Decide: ${cq.label}` });
    expect((decideButton as HTMLButtonElement).disabled).toBe(true); // no reason yet
    expect(box.textContent).toContain(OPEN.decide_note); // a new analysis: said before deciding
    fireEvent.change(reasonBox(), { target: { value: "  baseline-subtracted export  " } });
    fireEvent.click(decideButton);
    await waitFor(() => expect(sent).toHaveBeenCalledTimes(1));
    const [url, init] = sent.mock.calls[0] as unknown as [
      string,
      { params: { path: { study_id: string } }; body: Record<string, unknown> },
    ];
    expect(url).toBe("/api/studies/{study_id}/import-trust/decide");
    expect(init.params.path.study_id).toBe(OPEN.study_id);
    expect(init.body).toEqual({
      option: "cq_only",
      reason: "baseline-subtracted export",
      expected_inbox: OPEN.inbox_head,
    });
  });

  it("does not offer Cq only when the export has no instrument Cq", () => {
    const view = {
      ...OPEN,
      options: OPEN.options.map((o) =>
        o.id === "cq_only" ? { ...o, available: false, why_not: "no Cq values" } : o,
      ),
    } as TrustView;
    card(view);
    const radio = within(article()).getByRole("radio", { name: /instrument's Cq values only/ });
    expect((radio as HTMLInputElement).disabled).toBe(true);
    expect(article().textContent).toContain("no Cq values");
  });
});

describe("an agent's request on the card", () => {
  it("shows what the agent asked and lets a person approve it", async () => {
    const sent = answering({ status: "decided", message: "Recorded." });
    card(REQUEST);
    const box = article();
    expect(REQUEST.status).toBe("pending_human");
    expect(within(box).getByText("Agent request")).toBeTruthy();
    const request = REQUEST.requests[0]!;
    expect(box.textContent).toContain(request.reason);
    expect(within(box).getByText("Agent asked")).toBeTruthy();
    expect(within(box).queryAllByRole("radio")).toEqual([]); // the answer is to the request
    fireEvent.change(reasonBox(), { target: { value: "agreed" } });
    fireEvent.click(within(box).getByRole("button", { name: `Approve: ${request.option_label}` }));
    await waitFor(() => expect(sent).toHaveBeenCalledTimes(1));
    const [url, init] = sent.mock.calls[0] as unknown as [string, { body: { option: string } }];
    expect(url).toBe("/api/studies/{study_id}/import-trust/decide");
    expect(init.body.option).toBe(request.option);
  });

  it("turns the request down through the inbox, with the reason", async () => {
    const sent = answering({ message: "Rejected." });
    card(REQUEST);
    fireEvent.change(reasonBox(), { target: { value: "we will re-export instead" } });
    fireEvent.click(within(article()).getByRole("button", { name: "Turn down" }));
    await waitFor(() => expect(sent).toHaveBeenCalledTimes(1));
    const [url, init] = sent.mock.calls[0] as unknown as [
      string,
      { params: { path: { sid: string; pid: string } }; body: Record<string, unknown> },
    ];
    expect(url).toBe("/api/sessions/{sid}/proposals/{pid}/reject");
    expect(init.params.path).toEqual({ sid: KEY, pid: REQUEST.requests[0]!.proposal_id });
    expect(init.body).toEqual({
      reason: "we will re-export instead",
      expected_head: REQUEST.inbox_head,
    });
  });
});

describe("the card after a person chose Cq only", () => {
  it("says who decided, why and when, with the lower cap, and can be changed", () => {
    render(
      <QueryClientProvider client={client()}>
        <TooltipProvider>
          <ImportTrustView view={CQ_ONLY} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const box = article();
    expect(CQ_ONLY.decision?.option).toBe("cq_only");
    expect(within(box).getByText("Decided by a person")).toBeTruthy();
    expect(box.textContent).toContain(CQ_ONLY.decision!.reason);
    expect(box.textContent).toContain(`${CQ_ONLY.cap} confidence`);
    expect(CQ_ONLY.cap).toBe("Low");
    // read-only without a write: no form, no change button
    expect(within(box).queryByRole("textbox")).toBeNull();
    expect(within(box).queryByRole("button", { name: "Change the decision" })).toBeNull();
  });

  it("offers Change the decision where a person can decide", () => {
    card(CQ_ONLY);
    const box = article();
    expect(within(box).queryByRole("textbox")).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "Change the decision" }));
    expect(within(box).getAllByRole("radio")).toHaveLength(CQ_ONLY.options.length);
    expect(within(box).getByRole("textbox")).toBeTruthy();
  });
});

describe("a study whose curves call for no card", () => {
  it("shows nothing", () => {
    const { container } = card({ ...OPEN, applies: false } as TrustView);
    expect(container.textContent).toBe("");
  });
});

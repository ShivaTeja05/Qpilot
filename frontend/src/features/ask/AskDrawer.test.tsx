/** The drawer on a recorded real session frame: open, blind, refused, answered, retried. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import frame from "@/test/recorded/shell-session-frame.json";
import { TooltipProvider } from "@/ui";
import model from "./__recorded__/model-none.json";
import request from "./__recorded__/ask-request.json";
import robustness from "./__recorded__/ask-robustness.json";
import noRoute from "./__recorded__/no-route.json";
import AskDrawer from "./AskDrawer";
import { resetAllTurns } from "./history";
import { asWritten } from "./testText";

const session = frame as unknown as Schemas["WorkspaceView"];

function renderDrawer(workspace: Schemas["WorkspaceView"] | null, qc = client()) {
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <AskDrawer workspace={workspace} open onClose={() => {}} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function client(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // The shell's ["system"] query, as the server answered it (only the model is read here).
  qc.setQueryData(["system"], { model });
  return qc;
}

/** The server accepts the question with this (recorded, finished) job, and the job reads as recorded. */
function answerWith(job: { id: string }, qc: QueryClient) {
  qc.setQueryData(["job", job.id], job);
  vi.mocked(fetch).mockImplementation((url) =>
    String(url).endsWith("/ask") ? respond(202, { job }) : respond(404, noRoute),
  );
}

function ask(question: string) {
  const box = screen.getByLabelText<HTMLTextAreaElement>("Your question about this study");
  fireEvent.change(box, { target: { value: question } });
  fireEvent.keyDown(box, { key: "Enter" });
}

function respond(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
}

beforeEach(() => {
  // jsdom has neither media queries nor element scrolling.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} })),
  );
  Element.prototype.scrollTo = () => {};
  // The results route answers 404 on this store until it lands; Ask's route as recorded.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => respond(404, noRoute)),
  );
});

afterEach(() => {
  cleanup();
  resetAllTurns();
  vi.unstubAllGlobals();
});

describe("AskDrawer", () => {
  it("says honestly that no model is configured and templates answer", () => {
    renderDrawer(session);
    expect(screen.getByText("No model configured:")).toBeTruthy();
    expect(screen.getByText(/templates write the answers/)).toBeTruthy();
  });

  it("offers example questions and the question box when the results are visible", async () => {
    renderDrawer(session);
    expect(screen.getByRole("heading", { name: "Ask about this study" })).toBeTruthy();
    await screen.findByRole("button", { name: /plates, samples and genes/ });
    expect(screen.getByLabelText("Your question about this study")).toBeTruthy();
    // An audited study can be asked of the audit directly.
    expect(screen.getByLabelText("Answer from")).toBeTruthy();
    expect(screen.getByText("Audit")).toBeTruthy();
  });

  it("waits while the study is blind, says why and links to the stage to confirm", () => {
    const blind = {
      ...session,
      results_visible: false,
      stages: session.stages.map((s) => (s.stage === "curves" ? { ...s, confirmed: false } : s)),
    };
    renderDrawer(blind);
    expect(screen.getByText("Ask waits until the study is unblinded")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Confirm the curves" });
    expect(link.getAttribute("href")).toBe(`#/s/${session.key}/curves`);
    expect(screen.queryByLabelText("Your question about this study")).toBeNull();
  });

  it("shows the server's refusal in its words, with Try again, and keeps the question for ↑", async () => {
    renderDrawer(session);
    const box = screen.getByLabelText<HTMLTextAreaElement>("Your question about this study");
    fireEvent.change(box, { target: { value: "What should I check first in this data?" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByText(noRoute.error.message, asWritten);
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    const [url, init] = vi.mocked(fetch).mock.calls.find(([u]) => String(u).endsWith("/ask"))!;
    expect(String(url)).toBe(`/api/studies/${session.study_id}/ask`);
    expect(JSON.parse(String(init?.body))).toEqual({
      question: "What should I check first in this data?",
      source: "auto",
    });
    await waitFor(() => expect(box.value).toBe(""));
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(box.value).toBe("What should I check first in this data?");
  });

  it("Try again sends the same question once more, in the same place", async () => {
    const qc = client();
    renderDrawer(session, qc);
    ask(robustness.result.question);
    const retry = await screen.findByRole("button", { name: "Try again" });
    // This time the server answers.
    answerWith(robustness, qc);
    fireEvent.click(retry);
    await screen.findByText(robustness.result.answer, asWritten);
    const asks = vi.mocked(fetch).mock.calls.filter(([u]) => String(u).endsWith("/ask"));
    expect(asks.map(([, init]) => JSON.parse(String(init?.body)).question)).toEqual([
      robustness.result.question,
      robustness.result.question,
    ]);
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("answers a question with the recorded job: words, tool, writer and the cited facts", async () => {
    const qc = client();
    answerWith(robustness, qc);
    renderDrawer(session, qc);
    ask(robustness.result.question);
    await screen.findByText(robustness.result.answer, asWritten);
    for (const f of robustness.result.facts)
      expect(screen.getByText(f.meaning, asWritten)).toBeTruthy();
    expect(screen.getByText(robustness.result.writer_words, asWritten)).toBeTruthy();
    expect(screen.getByRole("link", { name: `Open ${robustness.result.args.gene}` })).toBeTruthy();
  });

  it("a change request answers in the drawer with its card, and nothing is re-read", async () => {
    const qc = client();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    answerWith(request, qc);
    renderDrawer(session, qc);
    ask(request.result.question);
    await screen.findByText(request.result.answer, asWritten);
    expect(screen.getByRole("link", { name: "Open the card" })).toBeTruthy();
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["w", session.key] });
  });
});

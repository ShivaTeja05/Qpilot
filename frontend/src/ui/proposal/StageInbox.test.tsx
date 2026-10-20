// Recorded from the real API (see ./recorded/README.md); nothing hand-written.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Proposal } from "@/lib/vocab";
import { TooltipProvider } from "../overlay";
import { StageInbox, decidedLine } from "./StageInbox";
import proposals from "./recorded/untergasser-design-proposals.json";
import quarantine from "./recorded/untergasser-quarantine.json";

// The API client captures `fetch` and `Request` when it is created, and builds same-origin
// (relative) URLs: give it both before any import runs.
const net = vi.hoisted(() => {
  const Base = globalThis.Request;
  class SameOrigin extends Base {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string" && input.startsWith("/") ? `http://127.0.0.1${input}` : input,
        init,
      );
    }
  }
  const state = {
    handle: (_req: Request): Promise<Response> => Promise.reject(new Error("no handler")),
  };
  globalThis.Request = SameOrigin as typeof Request;
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
    state.handle(input instanceof Request ? input : new SameOrigin(input, init));
  return state;
});

const SID = "2529de8272eb";
let posts: { url: string; body: unknown }[] = [];
let reads = 0;
let answer: { status: number; body: unknown } = {
  status: 403,
  body: { error: { code: "refused", message: "Not done: recorded data only" } },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  posts = [];
  reads = 0;
  answer = {
    status: 403,
    body: { error: { code: "refused", message: "Not done: recorded data only" } },
  };
  net.handle = async (req) => {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === `/api/sessions/${SID}/proposals`) {
      reads += 1;
      return json(proposals);
    }
    if (req.method === "GET" && url.pathname === `/api/sessions/${SID}/quarantine`)
      return json(quarantine);
    if (req.method === "POST") {
      posts.push({ url: url.pathname, body: await req.json() });
      return json(answer.body, answer.status);
    }
    return json({ error: { code: "not_found", message: "not recorded" } }, 404);
  };
});

afterEach(cleanup);

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <StageInbox sid={SID} stage="design" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const all = proposals.proposals as unknown as Proposal[];
const pending = all.filter((p) => p.status === "proposed");
const decided = all.filter((p) => p.status !== "proposed");

describe("StageInbox", () => {
  it("lists what is waiting and folds what is decided", async () => {
    wrap();
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(pending.length));
    expect(screen.getByText(`Decided in this stage (${decided.length})`)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Contradicted/, pressed: false })).toBeTruthy();
  });

  it("moves with j and rejects the focused card with x, sending the head it showed", async () => {
    wrap();
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(pending.length));
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "x" });
    fireEvent.change(screen.getByLabelText("Why do you reject it?"), {
      target: { value: "no well amplified" },
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Reject" })));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toBe(`/api/sessions/${SID}/proposals/${pending[0]!.id}/reject`);
    expect(posts[0]!.body).toEqual({ reason: "no well amplified", expected_head: proposals.head });
    // The refusal is shown on the card, in the server's words.
    expect(await screen.findByText("Not done: recorded data only")).toBeTruthy();
  });

  it("re-reads the inbox and says so when someone decided first (stale)", async () => {
    // The server's answer when the head the view showed is out of date (core.proposals STALE).
    answer = {
      status: 409,
      body: { error: { code: "stale", message: "stale", details: { head: proposals.head } } },
    };
    wrap();
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(pending.length));
    const before = reads;
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "x" });
    fireEvent.change(screen.getByLabelText("Why do you reject it?"), {
      target: { value: "no well amplified" },
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Reject" })));
    expect(await screen.findByText("Something was decided since you loaded this")).toBeTruthy();
    await waitFor(() => expect(reads).toBeGreaterThan(before));
  });

  it("lists each decided proposal with who decided, when and the reason (parity S15)", async () => {
    wrap();
    const fold = await screen.findByText(`Decided in this stage (${decided.length})`);
    fireEvent.click(fold);
    const rejected = decided.find((p) => p.status === "rejected")!;
    const row = screen
      .getAllByRole("button", { expanded: false })
      .find((b) => b.textContent?.includes(`“${rejected.reason}”`))!;
    expect(row.textContent).toContain(decidedLine(rejected));
    expect(decidedLine(rejected)).toMatch(
      /^Rejected by a person · \d{1,2} \w{3} \d{4}, \d{2}:\d{2} \(/,
    );
    // Only the decisions: filtering by "Rejected" leaves the rejected ones.
    fireEvent.click(screen.getByRole("button", { name: /^Rejected \d/, pressed: false }));
    const rows = screen.getAllByText(/^— reason:/);
    expect(rows).toHaveLength(decided.filter((p) => p.status === "rejected").length);
  });

  it("opens a decided proposal read-only", async () => {
    wrap();
    await waitFor(() => screen.getByText(`Decided in this stage (${decided.length})`));
    fireEvent.click(screen.getByText(`Decided in this stage (${decided.length})`));
    const first = decided[0]!;
    fireEvent.click(
      screen
        .getAllByRole("button", { expanded: false })
        .find((b) => b.textContent?.includes(first.subject))!,
    );
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(pending.length + 1);
    expect(cards[cards.length - 1]!.textContent).not.toMatch(/Accept|Reject…/);
  });
});

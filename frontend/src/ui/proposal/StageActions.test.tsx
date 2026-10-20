// Recorded from the real API (see ./recorded/README.md); nothing hand-written.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "../overlay";
import { BulkActions, REJECT_ALL_LABEL } from "./StageActions";
import inbox from "./recorded/probes-design-proposals.json";
import rejectAi from "./recorded/probes-bulk-reject-ai.json";
import rejectAll from "./recorded/probes-bulk-reject-all.json";

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

const SID = "49fba8329cdf";
let gets: string[] = [];
let posts: { url: string; body: Record<string, unknown> }[] = [];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  gets = [];
  posts = [];
  net.handle = async (req) => {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === `/api/sessions/${SID}/proposals`)
      return json(inbox);
    if (req.method === "GET" && url.pathname === `/api/sessions/${SID}/bulk/reject`) {
      gets.push(url.search);
      return json(url.searchParams.get("makers") === "all" ? rejectAll : rejectAi);
    }
    if (req.method === "POST") {
      posts.push({ url: url.pathname, body: (await req.json()) as Record<string, unknown> });
      return json({ error: { code: "refused", message: "Not done: recorded data only" } }, 403);
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
        <BulkActions sid={SID} stage="design" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Reject contradicted… (scope)", () => {
  it("covers the rules' contradictions when no AI call is contradicted, and posts that scope", async () => {
    wrap();
    const open = await screen.findByRole("button", { name: REJECT_ALL_LABEL });
    await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(open);
    const dialog = await screen.findByRole("dialog");
    const all = within(dialog).getByRole("radio", {
      name: /Every contradicted proposal, rules included/,
    });
    expect(all.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(gets).toContain("?stage=design&makers=all"));
    expect(await within(dialog).findByText("made by rule")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("One reason for all of them"), {
      target: { value: "no well of this standard amplified" },
    });
    await act(async () =>
      fireEvent.click(
        within(dialog).getByRole("button", { name: `Reject these ${rejectAll.ids.length}` }),
      ),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toBe(`/api/sessions/${SID}/bulk/reject`);
    expect(posts[0]!.body).toEqual({
      stage: "design",
      ids: rejectAll.ids,
      reason: "no well of this standard amplified",
      makers: "all",
      expected_head: rejectAll.head,
    });
  });

  it("lists only the AI's calls when that scope is chosen", async () => {
    wrap();
    fireEvent.click(await screen.findByRole("button", { name: REJECT_ALL_LABEL }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: /The AI's calls/ }));
    await waitFor(() => expect(gets).toContain("?stage=design&makers=ai"));
    expect(
      await within(dialog).findByText(
        /No waiting proposal from a model or an agent is contradicted/,
      ),
    ).toBeTruthy();
    expect(
      (within(dialog).getByRole("button", { name: "Reject these 0" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
